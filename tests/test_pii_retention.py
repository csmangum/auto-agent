"""Tests for PII masking and data retention."""

import json
import os
import tempfile
from unittest import mock

import pytest
from sqlalchemy import text


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

        mock_settings = mock.Mock()
        mock_settings.logging.mask_pii = True
        with mock.patch("claim_agent.observability.logger.get_settings", return_value=mock_settings):
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

        mock_settings = mock.Mock()
        mock_settings.logging.mask_pii = False
        with mock.patch("claim_agent.observability.logger.get_settings", return_value=mock_settings):
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

        mock_settings = mock.Mock()
        mock_settings.logging.mask_pii = True
        with mock.patch("claim_agent.observability.logger.get_settings", return_value=mock_settings):
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
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {"RETENTION_PERIOD_YEARS": "7"}):
            reload_settings()
            assert get_retention_period_years() == 7

    def test_get_retention_period_default(self):
        """get_retention_period_years should default to 5 from compliance when env unset."""
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.config.settings_model.Settings._load_compliance_retention",
                return_value=5,
            ):
                reload_settings()
                assert get_retention_period_years() == 5

    def test_get_retention_period_fallback_when_compliance_missing(self):
        """get_retention_period_years returns 5 when compliance returns None."""
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.config.settings_model.Settings._load_compliance_retention",
                return_value=None,
            ):
                reload_settings()
                assert get_retention_period_years() == 5

    def test_get_retention_period_fallback_when_ecr003_absent(self):
        """get_retention_period_years returns 5 when ECR-003 not in provisions."""
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.config.settings_model.Settings._load_compliance_retention",
                return_value=None,
            ):
                reload_settings()
                assert get_retention_period_years() == 5

    def test_get_retention_period_invalid_env_fallback(self):
        """get_retention_period_years falls back when RETENTION_PERIOD_YEARS is invalid."""
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {"RETENTION_PERIOD_YEARS": "x"}):
            with mock.patch(
                "claim_agent.config.settings_model.Settings._load_compliance_retention",
                return_value=5,
            ):
                reload_settings()
                assert get_retention_period_years() == 5

    def test_get_retention_period_fallback_when_ecr003_invalid(self):
        """get_retention_period_years returns 5 when ECR-003 has invalid retention_period_years."""
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_period_years

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "claim_agent.config.settings_model.Settings._load_compliance_retention",
                return_value=None,
            ):
                reload_settings()
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
            # Transition to closed (required for archiving) and backdate
            from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING

            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            with get_connection(db_path) as conn:
                conn.execute(
                    text("UPDATE claims SET created_at = datetime('now', '-10 years') WHERE id = :id"),
                    {"id": claim_id},
                )
            claims = repo.list_claims_for_retention(5)
            assert len(claims) == 1
            assert claims[0]["id"] == claim_id
            repo.archive_claim(claim_id)
            claims_after = repo.list_claims_for_retention(5)
            assert len(claims_after) == 0
        finally:
            os.unlink(db_path)

    def test_list_claims_for_retention_excludes_litigation_hold(self):
        """list_claims_for_retention excludes claims with litigation_hold when exclude_litigation_hold=True."""
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-LH",
                vin="1HGCM82633A999999",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2020-01-15",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING

            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            repo.set_litigation_hold(claim_id, True)
            with get_connection(db_path) as conn:
                conn.execute(
                    text("UPDATE claims SET created_at = datetime('now', '-10 years') WHERE id = :id"),
                    {"id": claim_id},
                )
            claims = repo.list_claims_for_retention(5, exclude_litigation_hold=True)
            assert len(claims) == 0
            claims_incl = repo.list_claims_for_retention(
                5, exclude_litigation_hold=False
            )
            assert len(claims_incl) == 1
        finally:
            os.unlink(db_path)

    def test_list_claims_for_retention_state_specific(self):
        """State-specific retention: Texas 7yr vs 10yr; claim 8yr old is past 7yr but not 10yr."""
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-TX",
                vin="1HGCM82633A999999",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2020-01-15",
                incident_description="Test",
                damage_description="Test",
                loss_state="Texas",
            )
            claim_id = repo.create_claim(claim_input)
            from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING

            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            with get_connection(db_path) as conn:
                conn.execute(
                    text("UPDATE claims SET created_at = datetime('now', '-8 years') WHERE id = :id"),
                    {"id": claim_id},
                )
            retention_by_state = {"California": 5, "Texas": 7}
            claims_7yr = repo.list_claims_for_retention(
                7, retention_by_state=retention_by_state
            )
            assert len(claims_7yr) == 1
            assert claims_7yr[0]["id"] == claim_id
            retention_by_state_long = {"Texas": 10}
            claims_10yr = repo.list_claims_for_retention(
                10, retention_by_state=retention_by_state_long
            )
            assert len(claims_10yr) == 0
        finally:
            os.unlink(db_path)

    def test_retention_report_output_shape_and_counts(self):
        """retention_report returns expected keys and counts."""
        from claim_agent.db.database import init_db
        from claim_agent.db.repository import ClaimRepository

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            report = repo.retention_report(5)
            assert "retention_period_years" in report
            assert report["retention_period_years"] == 5
            assert "retention_by_state" in report
            assert "claims_by_status" in report
            assert "active_count" in report
            assert "closed_count" in report
            assert "archived_count" in report
            assert "litigation_hold_count" in report
            assert "closed_with_litigation_hold" in report
            assert "pending_archive_count" in report
            assert "audit_log_rows" in report
            assert report["active_count"] >= 0
            assert report["closed_count"] >= 0
            assert report["archived_count"] >= 0
            assert report["litigation_hold_count"] >= 0
        finally:
            os.unlink(db_path)

    def test_archive_claim(self):
        """archive_claim should set status archived and archived_at."""
        from claim_agent.db.constants import STATUS_ARCHIVED, STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING
        from claim_agent.db.database import init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput

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
            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            repo.archive_claim(claim_id)

            claim = repo.get_claim(claim_id)
            assert claim["status"] == STATUS_ARCHIVED
            assert claim["archived_at"] is not None

            history, _ = repo.get_claim_history(claim_id)
            retention_actions = [h for h in history if h["action"] == "retention_archived"]
            assert len(retention_actions) == 1
        finally:
            os.unlink(db_path)


class TestRetentionCLI:
    """Tests for retention-enforce CLI command."""

    def test_retention_enforce_dry_run(self, capsys):
        """retention-enforce --dry-run should print without archiving."""
        from claim_agent.db.database import init_db
        from claim_agent.main import cmd_retention_enforce

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            with mock.patch.dict(os.environ, {"CLAIMS_DB_PATH": db_path}):
                cmd_retention_enforce(dry_run=True)
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["dry_run"] is True
            assert "retention_period_years" in data
            assert "claims_to_archive" in data
        finally:
            os.unlink(db_path)

    def test_retention_enforce_exits_1_when_archive_fails(self):
        """retention-enforce exits with code 1 when any archive fails."""
        from claim_agent.db.database import init_db
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

            with mock.patch.dict(os.environ, {"CLAIMS_DB_PATH": db_path}):
                with mock.patch.object(
                    ClaimRepository,
                    "list_claims_for_retention",
                    return_value=[{"id": claim_id}],
                ):
                    with mock.patch.object(
                        ClaimRepository,
                        "archive_claim",
                        side_effect=ValueError("Claim not found: " + claim_id),
                    ):
                        from claim_agent.main import cmd_retention_enforce

                        with pytest.raises(SystemExit) as exc_info:
                            cmd_retention_enforce(dry_run=False)
                        assert exc_info.value.code == 1
        finally:
            os.unlink(db_path)

    def test_retention_enforce_include_litigation_hold(self, capsys):
        """retention-enforce with include_litigation_hold=True archives held claims."""
        from claim_agent.config import reload_settings
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.main import cmd_retention_enforce
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-LH",
                vin="1HGCM82633A999999",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2020-01-15",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING

            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            repo.set_litigation_hold(claim_id, True)
            with get_connection(db_path) as conn:
                conn.execute(
                    text("UPDATE claims SET created_at = datetime('now', '-10 years') WHERE id = :id"),
                    {"id": claim_id},
                )
            with mock.patch.dict(os.environ, {"CLAIMS_DB_PATH": db_path}):
                reload_settings()
                cmd_retention_enforce(dry_run=True, include_litigation_hold=False)
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["claims_to_archive"] == 0

            with mock.patch.dict(os.environ, {"CLAIMS_DB_PATH": db_path}):
                reload_settings()
                cmd_retention_enforce(dry_run=True, include_litigation_hold=True)
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["claims_to_archive"] == 1
            assert claim_id in data["claim_ids"]
        finally:
            os.unlink(db_path)
