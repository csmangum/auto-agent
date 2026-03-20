"""Tests for DSAR (Data Subject Access Request) service."""

import pytest

from claim_agent.config import reload_settings
from claim_agent.db.database import init_db
from claim_agent.services.dsar import (
    fulfill_access_request,
    fulfill_deletion_request,
    get_dsar_request,
    list_dsar_requests,
    revoke_consent_by_email,
    submit_access_request,
    submit_deletion_request,
)


@pytest.fixture
def dsar_db(tmp_path):
    """Create a temporary DB with dsar tables and a sample claim."""
    db_path = str(tmp_path / "dsar_test.db")
    init_db(db_path)
    # Insert a sample claim and party
    from claim_agent.db.database import get_connection
    from sqlalchemy import text

    with get_connection(db_path) as conn:
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                incident_date, incident_description, damage_description, status, claim_type)
            VALUES ('CLM-TEST1', 'POL-123', '1HGCM82633A123456', 2020, 'Honda', 'Accord',
                '2024-01-15', 'Parking lot', 'Fender damage', 'closed', 'partial_loss')
        """)
        )
        conn.execute(
            text("""
            INSERT INTO claim_parties (claim_id, party_type, name, email, consent_status)
            VALUES ('CLM-TEST1', 'claimant', 'Jane Doe', 'jane@example.com', 'granted')
        """)
        )
    return db_path


class TestDSARAccess:
    def test_submit_and_fulfill_access(self, dsar_db):
        request_id = submit_access_request(
            claimant_identifier="jane@example.com",
            verification_data={"claim_id": "CLM-TEST1"},
            db_path=dsar_db,
        )
        assert request_id
        req = get_dsar_request(request_id, db_path=dsar_db)
        assert req["status"] == "pending"
        assert req["request_type"] == "access"

        export = fulfill_access_request(request_id, db_path=dsar_db)
        assert export["request_id"] == request_id
        assert len(export["claims"]) == 1
        assert export["claims"][0]["id"] == "CLM-TEST1"
        assert len(export["parties"]) == 1
        assert export["parties"][0]["email"] == "jane@example.com"

    def test_list_requests(self, dsar_db):
        submit_access_request("a@x.com", {"claim_id": "CLM-TEST1"}, db_path=dsar_db)
        requests, total = list_dsar_requests(db_path=dsar_db)
        assert total >= 1
        assert len(requests) >= 1

    def test_list_requests_pagination(self, dsar_db):
        requests, total = list_dsar_requests(limit=1, offset=0, db_path=dsar_db)
        assert len(requests) <= 1
        assert total >= 0

    def test_verification_required_rejects_claimant_only(self, dsar_db, monkeypatch):
        """When DSAR_VERIFICATION_REQUIRED=true, claimant_identifier-only lookup raises."""
        monkeypatch.setenv("DSAR_VERIFICATION_REQUIRED", "true")
        reload_settings()

        # Create a request with empty verification_data (simulates direct service call)
        request_id = submit_access_request(
            claimant_identifier="jane@example.com",
            verification_data={},
            db_path=dsar_db,
        )
        with pytest.raises(ValueError, match="Verification required"):
            fulfill_access_request(request_id, db_path=dsar_db)


class TestDSARDeletion:
    def test_submit_and_fulfill_deletion(self, dsar_db):
        request_id = submit_deletion_request(
            claimant_identifier="jane@example.com",
            verification_data={"claim_id": "CLM-TEST1"},
            db_path=dsar_db,
        )
        result = fulfill_deletion_request(request_id, db_path=dsar_db)
        assert result["anonymized_claims"] == 1
        assert result["skipped_litigation_hold"] == 0

        from claim_agent.db.database import get_connection
        from claim_agent.db.database import row_to_dict
        from sqlalchemy import text

        with get_connection(dsar_db) as conn:
            row = conn.execute(
                text(
                    "SELECT policy_number, vin, incident_description, damage_description "
                    "FROM claims WHERE id = 'CLM-TEST1'"
                )
            ).fetchone()
            assert row
            d = row_to_dict(row)
            assert d["policy_number"] == "[REDACTED]"
            assert d["vin"] == "[REDACTED]"
            assert d["incident_description"] == "[REDACTED]"
            assert d["damage_description"] == "[REDACTED]"

    def test_deletion_redacts_claim_notes(self, dsar_db):
        """Deletion redacts claim_notes which may contain PII."""
        from claim_agent.db.database import get_connection
        from sqlalchemy import text

        with get_connection(dsar_db) as conn:
            conn.execute(
                text(
                    "INSERT INTO claim_notes (claim_id, note, actor_id) VALUES (:cid, :note, 'test')"
                ),
                {
                    "cid": "CLM-TEST1",
                    "note": "Claimant Jane Doe called re: settlement. Address: 123 Main St.",
                },
            )

        request_id = submit_deletion_request(
            claimant_identifier="jane@example.com",
            verification_data={"claim_id": "CLM-TEST1"},
            db_path=dsar_db,
        )
        fulfill_deletion_request(request_id, db_path=dsar_db)

        with get_connection(dsar_db) as conn:
            row = conn.execute(
                text("SELECT note FROM claim_notes WHERE claim_id = 'CLM-TEST1'")
            ).fetchone()
            assert row
            assert row[0] == "[REDACTED - DSAR deletion]"

    def test_deletion_skips_litigation_hold(self, dsar_db):
        from claim_agent.db.database import get_connection
        from sqlalchemy import text

        with get_connection(dsar_db) as conn:
            conn.execute(text("UPDATE claims SET litigation_hold = 1 WHERE id = 'CLM-TEST1'"))

        request_id = submit_deletion_request(
            claimant_identifier="jane@example.com",
            verification_data={"claim_id": "CLM-TEST1"},
            db_path=dsar_db,
        )
        result = fulfill_deletion_request(request_id, db_path=dsar_db)
        assert result["skipped_litigation_hold"] == 1
        assert result["anonymized_claims"] == 0

    def test_deletion_anonymizes_when_litigation_hold_blocks_disabled(self, dsar_db, monkeypatch):
        """When LITIGATION_HOLD_BLOCKS_DELETION=false, anonymize even litigation_hold claims."""
        monkeypatch.setenv("LITIGATION_HOLD_BLOCKS_DELETION", "false")
        reload_settings()

        from claim_agent.db.database import get_connection
        from sqlalchemy import text

        with get_connection(dsar_db) as conn:
            conn.execute(text("UPDATE claims SET litigation_hold = 1 WHERE id = 'CLM-TEST1'"))

        request_id = submit_deletion_request(
            claimant_identifier="jane@example.com",
            verification_data={"claim_id": "CLM-TEST1"},
            db_path=dsar_db,
        )
        result = fulfill_deletion_request(request_id, db_path=dsar_db)
        assert result["skipped_litigation_hold"] == 0
        assert result["anonymized_claims"] == 1


class TestConsentRevoke:
    def test_revoke_consent_by_email(self, dsar_db):
        count = revoke_consent_by_email("jane@example.com", db_path=dsar_db)
        assert count >= 1

        from claim_agent.db.database import get_connection
        from sqlalchemy import text

        with get_connection(dsar_db) as conn:
            row = conn.execute(
                text("SELECT consent_status FROM claim_parties WHERE email = 'jane@example.com'")
            ).fetchone()
            assert row
            assert row[0] == "revoked"
