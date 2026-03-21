"""Unit tests for Georgia 17c-style diminished value and state routing."""

import json

import pytest

from claim_agent.compliance.diminished_value import (
    calculate_ga_17c_diminished_value,
    compute_diminished_value_payload,
)
from claim_agent.tools.valuation_logic import calculate_diminished_value_impl


class TestGeorgia17c:
    def test_known_repair_ratio_and_mileage(self):
        # FMV 25_000, repair 10_000 => ratio 0.40 => mult 0.20; mileage 50_000 => 0.90
        # base 2_500; DV = 2500 * 0.20 * 0.90 = 450
        out = calculate_ga_17c_diminished_value(
            25_000.0,
            mileage=50_000,
            repair_cost=10_000.0,
        )
        assert out["formula"] == "ga_17c"
        assert out["base_value_loss_cap"] == 2500.0
        assert out["damage_multiplier"] == 0.20
        assert out["mileage_multiplier"] == 0.90
        assert out["diminished_value"] == 450.0
        assert out["repair_cost_ratio"] == pytest.approx(0.4)

    def test_low_repair_ratio_zero_damage_multiplier(self):
        out = calculate_ga_17c_diminished_value(
            20_000.0,
            mileage=10_000,
            repair_cost=3000.0,
        )
        assert out["damage_multiplier"] == 0.0
        assert out["diminished_value"] == 0.0

    def test_tier_structural_when_no_repair_cost(self):
        out = calculate_ga_17c_diminished_value(
            30_000.0,
            mileage=15_000,
            damage_severity_tier="structural",
        )
        assert out["damage_multiplier"] == 0.80
        assert out["damage_basis"] == "tier"
        assert out["diminished_value"] == round(3000.0 * 0.80 * 1.0, 2)

    def test_default_assumption_without_repair_or_tier(self):
        out = calculate_ga_17c_diminished_value(18_000.0, mileage=None)
        assert out["damage_basis"] == "default_assumption"
        assert out["damage_multiplier"] == 0.40
        assert out["mileage_multiplier"] == 1.0
        assert out["diminished_value"] == round(1800.0 * 0.40, 2)


class TestComputePayloadRouting:
    def test_california_not_required(self):
        p = compute_diminished_value_payload(50_000.0, "California")
        assert p["required"] is False
        assert p["diminished_value"] == 0.0

    def test_georgia_uses_17c(self):
        p = compute_diminished_value_payload(
            20_000.0,
            "Georgia",
            mileage=25_000,
            repair_cost=8_000.0,
        )
        assert p["formula"] == "ga_17c"
        assert p["required"] is True
        assert p["diminished_value"] > 0

    def test_vehicle_year_echoed(self):
        p = compute_diminished_value_payload(
            22_000.0,
            "GA",
            vehicle_year=2019,
            repair_cost=9_000.0,
        )
        assert p["vehicle_year"] == 2019


class TestCalculateDiminishedValueImpl:
    def test_impl_json_georgia(self):
        raw = calculate_diminished_value_impl(
            25_000.0,
            "Georgia",
            mileage=50_000,
            repair_cost=10_000.0,
        )
        data = json.loads(raw)
        assert data["diminished_value"] == 450.0
