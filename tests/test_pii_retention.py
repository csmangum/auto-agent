"""Tests for PII masking and data retention."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest


class TestPIIMasking:
    """Tests for PII masking utilities."""

    def test_mask_policy_number(self):
        """mask_policy_number should mask middle characters."""
        from claim_agent.utils.pii_masking import mask_policy_number

        assert mask_policy_number("POL-12345-001") == "POL***001"
        assert mask_policy_number("ABC123") == "ABC***"  # 6 chars: first 3 + ***
        assert mask_policy_number("X") == "*"
        assert mask_policy_number("") == "***"
        assert mask_policy_number(None) == "***"

    def test_mask_vin(self):
        """mask_vin should mask middle of 17-char VIN."""
        from claim_agent.utils.pii_masking import mask_vin

        assert mask_vin("1HGCM82633A123456") == "1HG***3456"
        assert mask_vin("1HGCM82633A123456".lower()) == "1HG***3456"
        assert mask_vin("short") == "***"
        assert mask_vin(None) == "***"

    def test_mask_claimant_name(self):
        """mask_claimant_name should mask names."""
        from claim_agent.utils.pii_masking import mask_claimant_name

        assert mask_claimant_name("John Smith") == "J*** S***"
        assert mask_claimant_name("Alice") == "A***"
        assert mask_claimant_name(None) == "***"

    def test_mask_dict(self):
        """mask_dict should recursively mask PII keys."""
        from claim_agent.utils.pii_masking import mask_dict

        data = {
            "policy_number": "POL-12345-001",
            "vin": "1HGCM82633A123456",
            "other": "keep",
        }
        masked = mask_dict(data)
        assert masked["policy_number"] == "POL***001"
        assert masked["vin"] == "1HG***3456"
        assert masked["other"] == "keep"

    def test_mask_text_vin(self):
        """mask_text should mask VIN-like 17-char sequences in free text."""
        from claim_agent.utils.pii_masking import mask_text

        assert (
            mask_text("VIN 1HGCM82633A123456 was processed")
            == "VIN 1HG***3456 was processed"
        )

    def test_mask_text_policy_number(self):
        """mask_text should mask policy-number-like patterns in free text."""
        from claim_agent.utils.pii_masking import mask_text

        assert (
            mask_text("Policy POL-12345-001 failed")
            == "Policy POL***001 failed"
        )
        assert mask_text("Ref ABC123XYZ") == "Ref ABC***XYZ"


class TestPIIInLogger:
    """Tests for PII masking in log formatters."""

    def test_structured_formatter_masks_pii_when_enabled(self):
        """StructuredFormatter should mask policy_number and vin when CLAIM_AGENT_MASK_PII=true."""
        import logging

        from claim_agent.observability.logger import StructuredFormatter, _set_claim_context

        with mock.patch("claim_agent.observability.logger.get_mask_pii", return_value=True):
            formatter = StructuredFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )
            _set_claim_context({
                "claim_id": "CLM-1",
                "policy_number": "POL-12345-001",
                "vin": "1HGCM82633A123456",
            })
            try:
                output = formatter.format(record)
                parsed = json.loads(output)
                assert parsed.get("policy_number") == "POL***001"
                assert parsed.get("vin") == "1HG***3456"
            finally:
                _set_claim_context({})

    def test_structured_formatter_no_mask_when_disabled(self):
        """StructuredFormatter should not mask when CLAIM_AGENT_MASK_PII=false."""
        import logging

        from claim_agent.observability.logger import StructuredFormatter, _set_claim_context

        with mock.patch("claim_agent.observability.logger.get_mask_pii", return_value=False):
            formatter = StructuredFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )
            _set_claim_context({
                "claim_id": "CLM-1",
                "policy_number": "POL-12345-001",
                "vin": "1HGCM82633A123456",
            })
            try:
                output = formatter.format(record)
                parsed = json.loads(output)
                assert parsed.get("policy_number") == "POL-12345-001"
                assert parsed.get("vin") == "1HGCM82633A123456"
            finally:
                _set_claim_context({})

    def test_formatter_masks_policy_in_message_when_enabled(self):
        """When CLAIM_AGENT_MASK_PII=true, message body with policy number is masked."""
        import logging

        from claim_agent.observability.logger import StructuredFormatter, _set_claim_context

        with mock.patch("claim_agent.observability.logger.get_mask_pii", return_value=True):
            formatter = StructuredFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Policy POL-12345-001 lookup failed",
                args=(),
                exc_info=None,
            )
            _set_claim_context({})
            try:
                output = formatter.format(record)
                parsed = json.loads(output)
                assert "POL***001" in parsed.get("message", "")
                assert "POL-12345-001" not in parsed.get("message", "")
            finally:
                _set_claim_context({})


class TestRetentionConfig:
    """Tests for retention config."""

    def test_get_retention_period_from_env(self):
        """get_retention_period_years should use RETENTION_PERIOD_YEARS when set."""
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {"RETENTION_PERIOD_YEARS": "7"}):
            assert get_retention_period_years() == 7

    def test_get_retention_period_default(self):
        """get_retention_period_years should default to 5 from compliance when env unset."""
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.tools.data_loader.load_california_compliance",
                return_value={
                    "electronic_claims_requirements": {
                        "provisions": [
                            {"id": "ECR-003", "retention_period_years": 5},
                        ],
                    },
                },
            ):
                assert get_retention_period_years() == 5

    def test_get_retention_period_fallback_when_compliance_missing(self):
        """get_retention_period_years returns 5 when compliance returns None."""
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.tools.data_loader.load_california_compliance",
                return_value=None,
            ):
                assert get_retention_period_years() == 5

    def test_get_retention_period_fallback_when_ecr003_absent(self):
        """get_retention_period_years returns 5 when ECR-003 not in provisions."""
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.tools.data_loader.load_california_compliance",
                return_value={"electronic_claims_requirements": {"provisions": []}},
            ):
                assert get_retention_period_years() == 5

    def test_get_retention_period_invalid_env_fallback(self):
        """get_retention_period_years falls back when RETENTION_PERIOD_YEARS is invalid."""
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {"RETENTION_PERIOD_YEARS": "x"}):
            with mock.patch(
                "claim_agent.tools.data_loader.load_california_compliance",
                return_value={
                    "electronic_claims_requirements": {
                        "provisions": [{"id": "ECR-003", "retention_period_years": 5}],
                    },
                },
            ):
                assert get_retention_period_years() == 5


class TestRetentionRepository:
    """Tests for retention repository methods."""

    def test_list_claims_for_retention_empty(self):
        """list_claims_for_retention returns empty when no claims exceed retention."""
        from claim_agent.db.database import init_db
        from claim_agent.db.repository import ClaimRepository

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            # Retention 100 years - no claims will be that old
            claims = repo.list_claims_for_retention(100)
            assert claims == []
        finally:
            os.unlink(db_path)

    def test_list_claims_for_retention_includes_old_claim(self):
        """list_claims_for_retention returns claims older than retention; archive removes them."""
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-1",
                vin="1HGCM82633A123456",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2020-01-15",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            # Backdate created_at so claim is older than 5 years
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE claims SET created_at = datetime('now', '-10 years') WHERE id = ?",
                    (claim_id,),
                )
            claims = repo.list_claims_for_retention(5)
            assert len(claims) == 1
            assert claims[0]["id"] == claim_id
            repo.archive_claim(claim_id)
            claims_after = repo.list_claims_for_retention(5)
            assert len(claims_after) == 0
        finally:
            os.unlink(db_path)

    def test_archive_claim(self):
        """archive_claim should set status archived and archived_at."""
        from claim_agent.db.database import init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.db.constants import STATUS_ARCHIVED

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-123",
                vin="1HGCM82633A123456",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2024-01-15",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            repo.archive_claim(claim_id)

            claim = repo.get_claim(claim_id)
            assert claim["status"] == STATUS_ARCHIVED
            assert claim["archived_at"] is not None

            history = repo.get_claim_history(claim_id)
            retention_actions = [h for h in history if h["action"] == "retention_archived"]
            assert len(retention_actions) == 1
        finally:
            os.unlink(db_path)


class TestRetentionCLI:
    """Tests for retention-enforce CLI command."""

    def test_retention_enforce_dry_run(self):
        """retention-enforce --dry-run should print without archiving."""
        import subprocess
        import sys

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.db.database import init_db
            init_db(db_path)

            result = subprocess.run(
                [sys.executable, "-m", "claim_agent.main", "retention-enforce", "--dry-run"],
                cwd=str(Path(__file__).resolve().parent.parent),
                capture_output=True,
                text=True,
                env={**os.environ, "CLAIMS_DB_PATH": db_path},
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data["dry_run"] is True
            assert "retention_period_years" in data
            assert "claims_to_archive" in data
        finally:
            os.unlink(db_path)
