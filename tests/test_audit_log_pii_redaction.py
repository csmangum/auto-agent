"""Tests for audit log PII redaction (issue: Redact before_state / after_state)."""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest
from sqlalchemy import text

from claim_agent.db.database import get_connection, init_db
from claim_agent.db.pii_redaction import (
    PII_REDACTED_PLACEHOLDER,
    _redact_json_field,
    _redact_json_pii,
    redact_audit_log_pii,
    anonymize_claim_pii,
)


# ---------------------------------------------------------------------------
# Unit tests for the JSON redaction helper
# ---------------------------------------------------------------------------


class TestRedactJsonPii:
    """Unit tests for _redact_json_pii (pure function, no DB)."""

    def test_redacts_policy_number(self):
        data = {"policy_number": "POL-12345-001", "status": "open"}
        result = _redact_json_pii(data)
        assert result["policy_number"] == PII_REDACTED_PLACEHOLDER
        assert result["status"] == "open"

    def test_redacts_vin(self):
        data = {"vin": "1HGCM82633A123456", "claim_type": "partial_loss"}
        result = _redact_json_pii(data)
        assert result["vin"] == PII_REDACTED_PLACEHOLDER
        assert result["claim_type"] == "partial_loss"

    def test_redacts_incident_and_damage_description(self):
        data = {
            "incident_description": "Hit a deer on Route 66",
            "damage_description": "Front bumper dented",
        }
        result = _redact_json_pii(data)
        assert result["incident_description"] == PII_REDACTED_PLACEHOLDER
        assert result["damage_description"] == PII_REDACTED_PLACEHOLDER

    def test_replaces_attachments_with_empty_list(self):
        data = {"attachments": [{"url": "s3://bucket/file.jpg"}]}
        result = _redact_json_pii(data)
        assert result["attachments"] == []

    def test_redacts_nested_party_pii(self):
        data = {
            "parties": [
                {
                    "name": "Jane Doe",
                    "email": "jane@example.com",
                    "phone": "555-1234",
                    "address": "123 Main St",
                    "role": "claimant",
                }
            ]
        }
        result = _redact_json_pii(data)
        party = result["parties"][0]
        assert party["name"] == PII_REDACTED_PLACEHOLDER
        assert party["email"] == PII_REDACTED_PLACEHOLDER
        assert party["phone"] == PII_REDACTED_PLACEHOLDER
        assert party["address"] == PII_REDACTED_PLACEHOLDER
        # Non-PII field preserved
        assert party["role"] == "claimant"

    def test_preserves_non_pii_fields(self):
        data = {
            "status": "open",
            "claim_type": "partial_loss",
            "payout_amount": 5000.0,
            "repair_ready_for_settlement": False,
            "payment_due": None,
        }
        result = _redact_json_pii(data)
        assert result == data

    def test_handles_none_pii_value(self):
        """A PII key with a None value should remain None, not become [REDACTED]."""
        data = {"policy_number": None}
        result = _redact_json_pii(data)
        assert result["policy_number"] is None

    def test_custom_placeholder(self):
        data = {"vin": "1HGCM82633A123456"}
        result = _redact_json_pii(data, placeholder="***")
        assert result["vin"] == "***"

    def test_non_dict_passthrough(self):
        assert _redact_json_pii("plain string") == "plain string"
        assert _redact_json_pii(42) == 42

    def test_list_of_dicts(self):
        data = [{"vin": "1HGCM82633A123456"}, {"status": "closed"}]
        result = _redact_json_pii(data)
        assert result[0]["vin"] == PII_REDACTED_PLACEHOLDER
        assert result[1]["status"] == "closed"

    def test_redact_json_field_preserves_invalid_json(self):
        raw = "{not valid json"
        assert _redact_json_field(raw) == raw


# ---------------------------------------------------------------------------
# Integration tests using a real (in-memory / tmp) SQLite DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def audit_db(tmp_path):
    """Create a temp SQLite DB, a claim row, and audit rows with PII in JSON."""
    db_path = str(tmp_path / "audit_test.db")
    init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                vehicle_model, incident_date, incident_description, damage_description,
                status, claim_type)
            VALUES ('CLM-AUDIT1', 'POL-99999', '1HGCM82633A000001', 2022, 'Honda',
                'Civic', '2024-06-01', 'Rear-ended on highway', 'Rear bumper cracked',
                'open', 'partial_loss')
            """)
        )
        before = json.dumps(
            {
                "policy_number": "POL-99999",
                "vin": "1HGCM82633A000001",
                "status": "open",
                "payout_amount": None,
                "incident_description": "Rear-ended on highway",
                "damage_description": "Rear bumper cracked",
                "attachments": [{"url": "s3://bucket/photo.jpg"}],
            }
        )
        after = json.dumps(
            {
                "policy_number": "POL-99999",
                "vin": "1HGCM82633A000001",
                "status": "closed",
                "payout_amount": 1500.0,
            }
        )
        conn.execute(
            text("""
            INSERT INTO claim_audit_log
                (claim_id, action, old_status, new_status, actor_id, before_state, after_state)
            VALUES
                ('CLM-AUDIT1', 'status_change', 'open', 'closed', 'system',
                 :before, :after)
            """),
            {"before": before, "after": after},
        )
        # A row with no JSON state (should be left alone)
        conn.execute(
            text("""
            INSERT INTO claim_audit_log
                (claim_id, action, old_status, new_status, actor_id)
            VALUES
                ('CLM-AUDIT1', 'created', NULL, 'open', 'system')
            """)
        )

    return db_path


class TestRedactAuditLogPii:
    """Integration tests for redact_audit_log_pii()."""

    def test_pii_keys_replaced_in_before_and_after_state(self, audit_db):
        """PII keys in before_state and after_state are replaced with [REDACTED]."""
        with get_connection(audit_db) as conn:
            updated = redact_audit_log_pii(conn, "CLM-AUDIT1")

        # Exactly one row has JSON state in the fixture (the status_change row).
        assert updated == 1
        with get_connection(audit_db) as conn:
            rows = conn.execute(
                text(
                    "SELECT before_state, after_state FROM claim_audit_log "
                    "WHERE claim_id = 'CLM-AUDIT1' AND action = 'status_change'"
                )
            ).fetchall()

        assert len(rows) == 1
        before = json.loads(rows[0][0])
        after = json.loads(rows[0][1])

        assert before["policy_number"] == PII_REDACTED_PLACEHOLDER
        assert before["vin"] == PII_REDACTED_PLACEHOLDER
        assert before["incident_description"] == PII_REDACTED_PLACEHOLDER
        assert before["damage_description"] == PII_REDACTED_PLACEHOLDER
        assert before["attachments"] == []
        # Non-PII preserved
        assert before["status"] == "open"
        assert before["payout_amount"] is None

        assert after["policy_number"] == PII_REDACTED_PLACEHOLDER
        assert after["vin"] == PII_REDACTED_PLACEHOLDER
        assert after["status"] == "closed"
        assert after["payout_amount"] == 1500.0

    def test_rows_without_json_state_are_not_counted(self, audit_db):
        """Rows with NULL before_state and after_state are skipped (not counted)."""
        with get_connection(audit_db) as conn:
            # The fixture has two rows: one with JSON state, one with NULLs.
            # Only the JSON-state row should be updated; the NULL row is skipped.
            updated = redact_audit_log_pii(conn, "CLM-AUDIT1")
        assert updated == 1

    def test_non_pii_columns_unchanged(self, audit_db):
        """action, actor_id, old_status, new_status, created_at are untouched."""
        with get_connection(audit_db) as conn:
            before_rows = conn.execute(
                text(
                    "SELECT id, action, old_status, new_status, actor_id, created_at "
                    "FROM claim_audit_log WHERE claim_id = 'CLM-AUDIT1'"
                )
            ).fetchall()
            redact_audit_log_pii(conn, "CLM-AUDIT1")
            after_rows = conn.execute(
                text(
                    "SELECT id, action, old_status, new_status, actor_id, created_at "
                    "FROM claim_audit_log WHERE claim_id = 'CLM-AUDIT1'"
                )
            ).fetchall()

        assert len(before_rows) == len(after_rows)
        for b, a in zip(before_rows, after_rows):
            # All non-PII columns must be identical after redaction.
            assert list(b) == list(a)

    def test_unknown_claim_id_returns_zero(self, audit_db):
        with get_connection(audit_db) as conn:
            updated = redact_audit_log_pii(conn, "CLM-DOES-NOT-EXIST")
        assert updated == 0

    def test_trigger_blocks_non_pii_column_update(self, audit_db):
        """The DB trigger must still reject updates to non-PII columns."""
        from sqlalchemy.exc import OperationalError, DBAPIError

        with get_connection(audit_db) as conn:
            row = conn.execute(
                text("SELECT id FROM claim_audit_log LIMIT 1")
            ).fetchone()
            row_id = row[0]

        with get_connection(audit_db) as conn:
            with pytest.raises((OperationalError, DBAPIError)):
                conn.execute(
                    text("UPDATE claim_audit_log SET action = 'tampered' WHERE id = :id"),
                    {"id": row_id},
                )


class TestAnonymizeClaimPiiWithAuditRedact:
    """Tests for the redact_audit_log flag in anonymize_claim_pii()."""

    def test_audit_log_redacted_when_flag_true(self, audit_db):
        """When redact_audit_log=True, PII is redacted from audit rows too."""
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_connection(audit_db) as conn:
            anonymize_claim_pii(
                conn,
                "CLM-AUDIT1",
                now_iso=now_iso,
                notes_redaction_text="[REDACTED - test]",
                redact_audit_log=True,
            )

        with get_connection(audit_db) as conn:
            rows = conn.execute(
                text(
                    "SELECT before_state FROM claim_audit_log "
                    "WHERE claim_id = 'CLM-AUDIT1' AND action = 'status_change'"
                )
            ).fetchall()

        assert len(rows) == 1
        before = json.loads(rows[0][0])
        assert before["policy_number"] == PII_REDACTED_PLACEHOLDER

    def test_audit_log_untouched_when_flag_false(self, audit_db):
        """Default behavior: audit log is NOT touched when redact_audit_log=False."""
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_connection(audit_db) as conn:
            anonymize_claim_pii(
                conn,
                "CLM-AUDIT1",
                now_iso=now_iso,
                notes_redaction_text="[REDACTED - test]",
                redact_audit_log=False,
            )

        with get_connection(audit_db) as conn:
            rows = conn.execute(
                text(
                    "SELECT before_state FROM claim_audit_log "
                    "WHERE claim_id = 'CLM-AUDIT1' AND action = 'status_change'"
                )
            ).fetchall()

        assert len(rows) == 1
        before = json.loads(rows[0][0])
        # Original PII value still present (not redacted)
        assert before["policy_number"] == "POL-99999"


class TestSettingsGate:
    """Tests for AUDIT_LOG_STATE_REDACTION_ENABLED settings gate."""

    def test_default_is_false(self):
        """audit_log_state_redaction_enabled defaults to False."""
        from claim_agent.config import reload_settings

        with mock.patch.dict(os.environ, {}, clear=True):
            reload_settings()
            from claim_agent.config import get_settings

            assert get_settings().privacy.audit_log_state_redaction_enabled is False

    def test_env_var_enables_redaction(self):
        """AUDIT_LOG_STATE_REDACTION_ENABLED=true enables the setting."""
        from claim_agent.config import reload_settings

        with mock.patch.dict(
            os.environ, {"AUDIT_LOG_STATE_REDACTION_ENABLED": "true"}
        ):
            reload_settings()
            from claim_agent.config import get_settings

            assert get_settings().privacy.audit_log_state_redaction_enabled is True

    def test_env_var_false_disables_redaction(self):
        """AUDIT_LOG_STATE_REDACTION_ENABLED=false keeps redaction disabled."""
        from claim_agent.config import reload_settings

        with mock.patch.dict(
            os.environ, {"AUDIT_LOG_STATE_REDACTION_ENABLED": "false"}
        ):
            reload_settings()
            from claim_agent.config import get_settings

            assert get_settings().privacy.audit_log_state_redaction_enabled is False
