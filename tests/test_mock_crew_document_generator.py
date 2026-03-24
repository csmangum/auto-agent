"""Tests for mock crew document generator."""

import hashlib
import json
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.document_generator import (
    generate_damage_photo_url,
    generate_repair_estimate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def base_claim_context():
    return {
        "claim_id": "CLM-001",
        "vehicle_year": 2020,
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
        "damage_description": "front bumper and hood damage",
        "incident_description": "collision at intersection",
    }


def _make_settings(seed=None, generator_enabled=False, tmp_path=None, enabled=True):
    """Build a minimal mock settings object."""
    m = type("S", (), {})()
    m.mock_crew = type("MC", (), {"seed": seed})()
    m.mock_image = type("MI", (), {"generator_enabled": generator_enabled})()
    m.mock_document = type("MD", (), {"enabled": enabled})()
    if tmp_path is not None:
        m.get_attachment_storage_base_path = lambda: tmp_path
    return m


# ---------------------------------------------------------------------------
# generate_repair_estimate tests
# ---------------------------------------------------------------------------


class TestGenerateRepairEstimate:
    """Tests for generate_repair_estimate."""

    def test_returns_required_keys(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)

        required = {
            "claim_id", "vehicle", "shop_name", "line_items",
            "subtotal_parts", "subtotal_labor", "subtotal", "tax", "total", "currency",
        }
        assert required <= result.keys()

    def test_currency_is_usd(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert result["currency"] == "USD"

    def test_total_equals_subtotal_plus_tax(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert result["total"] == round(result["subtotal"] + result["tax"], 2)

    def test_subtotal_equals_parts_plus_labor(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert result["subtotal"] == round(result["subtotal_parts"] + result["subtotal_labor"], 2)

    def test_line_items_are_non_empty(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert len(result["line_items"]) > 0

    def test_line_item_keys(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        for item in result["line_items"]:
            assert {"description", "part_cost", "labor_hours", "labor_cost", "line_total"} <= item.keys()

    def test_claim_id_propagated(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert result["claim_id"] == "CLM-001"

    def test_vehicle_propagated(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(base_claim_context)
        assert "2020" in result["vehicle"]
        assert "Toyota" in result["vehicle"]
        assert "Camry" in result["vehicle"]

    def test_deterministic_with_seed(self, base_claim_context):
        """Same context + seed always produces identical output."""
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            r1 = generate_repair_estimate(base_claim_context)
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            r2 = generate_repair_estimate(base_claim_context)
        assert r1 == r2

    def test_different_seed_different_output(self, base_claim_context):
        """Different seeds should produce different shops / totals most of the time."""
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=1)
            r1 = generate_repair_estimate(base_claim_context)
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=9999)
            r2 = generate_repair_estimate(base_claim_context)
        # At minimum, totals or shop names should differ for radically different seeds
        assert r1 != r2

    def test_estimated_damage_override_scales_total(self, base_claim_context):
        """When estimated_damage is provided the final total should match it approximately."""
        ctx = {**base_claim_context, "estimated_damage": 1500.0}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        # Scaling is exact to within a few cents (rounding across line items)
        assert abs(result["total"] - 1500.0) < 2.0

    def test_no_claim_id_in_context(self):
        ctx = {"damage_description": "rear bumper dent"}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate(ctx)
        assert result["claim_id"] is None

    def test_empty_context_still_returns_estimate(self):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None)
            result = generate_repair_estimate({})
        assert result["total"] > 0

    def test_front_damage_includes_front_parts(self):
        ctx = {"damage_description": "front bumper cracked"}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        descriptions = [item["description"] for item in result["line_items"]]
        assert any("Bumper" in d or "Hood" in d or "Headlight" in d for d in descriptions)

    def test_total_loss_context_includes_many_parts(self):
        ctx = {"damage_description": "total loss after collision"}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        assert len(result["line_items"]) >= 5

    def test_raises_when_disabled(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, enabled=False)
            with pytest.raises(ValueError, match="disabled"):
                generate_repair_estimate(base_claim_context)

    def test_estimated_damage_zero_ignored(self, base_claim_context):
        ctx = {**base_claim_context, "estimated_damage": 0}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        ctx_no_override = {**base_claim_context}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            baseline = generate_repair_estimate(ctx_no_override)
        assert result["total"] == baseline["total"]

    def test_estimated_damage_negative_ignored(self, base_claim_context):
        ctx = {**base_claim_context, "estimated_damage": -500.0}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        ctx_no_override = {**base_claim_context}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            baseline = generate_repair_estimate(ctx_no_override)
        assert result["total"] == baseline["total"]

    def test_estimated_damage_non_numeric_ignored(self, base_claim_context):
        ctx = {**base_claim_context, "estimated_damage": "not a number"}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(ctx)
        assert result["total"] > 0

    def test_line_items_sum_matches_subtotal(self, base_claim_context):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42)
            result = generate_repair_estimate(base_claim_context)
        line_total_sum = sum(item["line_total"] for item in result["line_items"])
        assert abs(line_total_sum - result["subtotal"]) < 0.02


# ---------------------------------------------------------------------------
# generate_damage_photo_url tests
# ---------------------------------------------------------------------------


class TestGenerateDamagePhotoUrl:
    """Tests for generate_damage_photo_url."""

    def test_returns_string(self, base_claim_context, tmp_path):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, generator_enabled=False, tmp_path=tmp_path)
            result = generate_damage_photo_url(base_claim_context)
        assert isinstance(result, str)

    def test_placeholder_path_contains_claim_id(self, base_claim_context, tmp_path):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, generator_enabled=False, tmp_path=tmp_path)
            result = generate_damage_photo_url(base_claim_context)
        assert "CLM-001" in result

    def test_placeholder_path_is_file_url(self, base_claim_context, tmp_path):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, generator_enabled=False, tmp_path=tmp_path)
            result = generate_damage_photo_url(base_claim_context)
        assert result.startswith("file://")

    def test_deterministic_with_seed(self, base_claim_context, tmp_path):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42, generator_enabled=False, tmp_path=tmp_path)
            r1 = generate_damage_photo_url(base_claim_context)
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=42, generator_enabled=False, tmp_path=tmp_path)
            r2 = generate_damage_photo_url(base_claim_context)
        assert r1 == r2

    def test_delegates_to_image_generator_when_enabled(self, base_claim_context, tmp_path):
        """When MOCK_IMAGE_GENERATOR_ENABLED, generate_damage_image is called."""
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, generator_enabled=True, tmp_path=tmp_path)
            with patch(
                "claim_agent.mock_crew.image_generator.generate_damage_image"
            ) as mock_gen:
                mock_gen.return_value = "file:///tmp/mock_damage_abc123.png"
                result = generate_damage_photo_url(base_claim_context)
        mock_gen.assert_called_once_with(base_claim_context, fallback_on_error=True)
        assert result == "file:///tmp/mock_damage_abc123.png"

    def test_seeded_filename_matches_expected_hash(self, tmp_path):
        ctx = {"claim_id": "CLM-999", "damage_description": "rear bumper"}
        seed = 7
        ctx_str = json.dumps(ctx, sort_keys=True)
        h = hashlib.sha256(f"{ctx_str}:{seed}".encode()).hexdigest()[:12]
        expected_filename = f"mock_damage_{h}.png"

        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=seed, generator_enabled=False, tmp_path=tmp_path)
            result = generate_damage_photo_url(ctx)

        assert expected_filename in result

    def test_raises_when_disabled(self, base_claim_context, tmp_path):
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(
                seed=None, generator_enabled=False, tmp_path=tmp_path, enabled=False,
            )
            with pytest.raises(ValueError, match="disabled"):
                generate_damage_photo_url(base_claim_context)

    def test_claim_id_special_chars_sanitized(self, tmp_path):
        ctx = {"claim_id": "CLM/001 (test)"}
        with patch("claim_agent.mock_crew.document_generator.get_settings") as ms:
            ms.return_value = _make_settings(seed=None, generator_enabled=False, tmp_path=tmp_path)
            result = generate_damage_photo_url(ctx)
        assert "/" not in result.split("mock_generated/")[-1]
        assert " " not in result.split("mock_generated/")[-1]
        assert "(" not in result.split("mock_generated/")[-1]
