"""Tests for the RentalAuthorizationRepository."""

import pytest

from claim_agent.db.rental_repository import RentalAuthorizationRepository


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB (with claim records) for all rental repository tests."""
    yield


@pytest.fixture
def repo(seeded_temp_db):
    return RentalAuthorizationRepository(db_path=seeded_temp_db)


class TestUpsertAuthorization:
    """Tests for upsert_authorization (insert and update paths)."""

    def test_insert_returns_positive_id(self, repo):
        """upsert_authorization inserts a new row and returns a positive id."""
        row_id = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=35.0,
            reimbursement_id="RENT-ABCD1234",
            amount_approved=245.0,
        )
        assert row_id > 0

    def test_insert_persists_all_fields(self, repo):
        """Inserted row is retrievable with all fields intact."""
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=10,
            daily_cap=40.0,
            reservation_ref="RES-XYZ",
            agency_ref="AGY-123",
            direct_bill=True,
            status="authorized",
            reimbursement_id="RENT-TEST0001",
            amount_approved=400.0,
        )
        record = repo.get_authorization("CLM-TEST001")
        assert record is not None
        assert record["claim_id"] == "CLM-TEST001"
        assert record["authorized_days"] == 10
        assert record["daily_cap"] == 40.0
        assert record["reservation_ref"] == "RES-XYZ"
        assert record["agency_ref"] == "AGY-123"
        assert record["direct_bill"] is True
        assert record["status"] == "authorized"
        assert record["reimbursement_id"] == "RENT-TEST0001"
        assert record["amount_approved"] == 400.0

    def test_direct_bill_false_stored_correctly(self, repo):
        """direct_bill=False is stored and returned as Python False."""
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            direct_bill=False,
            reimbursement_id="RENT-FALSE001",
        )
        record = repo.get_authorization("CLM-TEST001")
        assert record["direct_bill"] is False

    def test_update_by_reimbursement_id_is_idempotent(self, repo):
        """Second upsert with the same reimbursement_id updates the existing row."""
        row_id1 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            reimbursement_id="RENT-IDEM0001",
            amount_approved=175.0,
        )
        row_id2 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            reimbursement_id="RENT-IDEM0001",
            amount_approved=175.0,
            status="completed",
        )
        assert row_id1 == row_id2, "Should update the same row, not insert a new one"
        record = repo.get_authorization("CLM-TEST001")
        assert record["status"] == "completed"

    def test_new_reimbursement_id_inserts_row_preserving_prior_id(self, repo):
        """A distinct reimbursement_id must not update the prior row for the same claim."""
        row_id1 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            reimbursement_id="RENT-FIRST",
            amount_approved=175.0,
        )
        row_id2 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=40.0,
            reimbursement_id="RENT-SECOND",
            amount_approved=280.0,
        )
        assert row_id1 != row_id2
        first = repo.get_by_reimbursement_id("RENT-FIRST")
        second = repo.get_by_reimbursement_id("RENT-SECOND")
        assert first is not None and second is not None
        assert first["amount_approved"] == 175.0
        assert second["amount_approved"] == 280.0
        latest = repo.get_authorization("CLM-TEST001")
        assert latest["reimbursement_id"] == "RENT-SECOND"

    def test_update_by_claim_id_when_no_reimbursement_id(self, repo):
        """Second upsert for same claim_id (no reimbursement_id) updates existing row."""
        row_id1 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
        )
        row_id2 = repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=35.0,
            status="in_progress",
        )
        assert row_id1 == row_id2
        record = repo.get_authorization("CLM-TEST001")
        assert record["authorized_days"] == 7
        assert record["status"] == "in_progress"

    def test_upsert_invalid_status_raises(self, repo):
        """Invalid status raises ValueError before touching the DB."""
        with pytest.raises(ValueError, match="Invalid rental authorization status"):
            repo.upsert_authorization(
                claim_id="CLM-TEST001",
                authorized_days=5,
                daily_cap=35.0,
                reimbursement_id="RENT-BADSTAT",
                status="bogus",
            )


class TestGetAuthorization:
    """Tests for get_authorization (internal full view)."""

    def test_returns_none_when_no_record(self, repo):
        """Returns None when no authorization has been persisted."""
        assert repo.get_authorization("CLM-NONEXISTENT") is None

    def test_returns_most_recent_when_multiple(self, repo, seeded_temp_db):
        """Returns the most recent row when multiple exist for a claim."""
        repo.upsert_authorization(
            claim_id="CLM-TEST001", authorized_days=3, daily_cap=35.0
        )
        # Force a second insert (different reimbursement_id → new row)
        from sqlalchemy import text
        from claim_agent.db.database import get_connection

        with get_connection(seeded_temp_db) as conn:
            conn.execute(
                text("""
                INSERT INTO rental_authorizations
                    (claim_id, authorized_days, daily_cap, reimbursement_id, status)
                VALUES ('CLM-TEST001', 14, 40.0, 'RENT-SECOND', 'in_progress')
                """)
            )
        record = repo.get_authorization("CLM-TEST001")
        assert record["reimbursement_id"] == "RENT-SECOND"
        assert record["authorized_days"] == 14


class TestGetPortalSummary:
    """Tests for get_portal_summary (sanitized claimant-facing view)."""

    def test_returns_none_when_no_record(self, repo):
        """Returns None when no authorization has been persisted."""
        assert repo.get_portal_summary("CLM-NONEXISTENT") is None

    def test_excludes_vendor_sensitive_fields(self, repo):
        """Portal summary omits reservation_ref and agency_ref."""
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=35.0,
            reservation_ref="RES-SECRET",
            agency_ref="AGY-SECRET",
            reimbursement_id="RENT-PORTAL01",
            amount_approved=245.0,
        )
        summary = repo.get_portal_summary("CLM-TEST001")
        assert summary is not None
        assert "reservation_ref" not in summary
        assert "agency_ref" not in summary

    def test_includes_safe_fields(self, repo):
        """Portal summary includes all claimant-safe fields."""
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=35.0,
            direct_bill=False,
            status="authorized",
            reimbursement_id="RENT-SAFE0001",
            amount_approved=245.0,
        )
        summary = repo.get_portal_summary("CLM-TEST001")
        assert summary["claim_id"] == "CLM-TEST001"
        assert summary["authorized_days"] == 7
        assert summary["daily_cap"] == 35.0
        assert summary["direct_bill"] is False
        assert summary["status"] == "authorized"
        assert summary["reimbursement_id"] == "RENT-SAFE0001"
        assert summary["amount_approved"] == 245.0
        assert "created_at" in summary
        assert "updated_at" in summary
        assert "id" not in summary


class TestGetByReimbursementId:
    """Tests for get_by_reimbursement_id."""

    def test_returns_none_when_not_found(self, repo):
        assert repo.get_by_reimbursement_id("RENT-UNKNOWN") is None

    def test_returns_matching_record(self, repo):
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            reimbursement_id="RENT-LOOKUP01",
            amount_approved=175.0,
        )
        record = repo.get_by_reimbursement_id("RENT-LOOKUP01")
        assert record is not None
        assert record["claim_id"] == "CLM-TEST001"
        assert record["reimbursement_id"] == "RENT-LOOKUP01"


class TestUpdateStatus:
    """Tests for update_status."""

    def test_update_status_returns_true_on_success(self, repo):
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
        )
        result = repo.update_status("CLM-TEST001", "completed")
        assert result is True

    def test_update_status_returns_false_when_no_record(self, repo):
        result = repo.update_status("CLM-NONEXISTENT", "completed")
        assert result is False

    def test_update_status_persists(self, repo):
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
            status="authorized",
        )
        repo.update_status("CLM-TEST001", "completed")
        record = repo.get_authorization("CLM-TEST001")
        assert record["status"] == "completed"

    def test_update_status_invalid_status_raises(self, repo):
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=35.0,
        )
        with pytest.raises(ValueError, match="Invalid rental authorization status"):
            repo.update_status("CLM-TEST001", "not_a_status")

    def test_update_status_only_updates_latest_row(self, repo, seeded_temp_db):
        """When multiple rows exist, only the most recent row is updated."""
        from sqlalchemy import text

        from claim_agent.db.database import get_connection

        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=3,
            daily_cap=35.0,
            reimbursement_id="RENT-OLDER",
            status="authorized",
        )
        with get_connection(seeded_temp_db) as conn:
            conn.execute(
                text("""
                INSERT INTO rental_authorizations
                    (claim_id, authorized_days, daily_cap, reimbursement_id, status)
                VALUES ('CLM-TEST001', 14, 40.0, 'RENT-NEWER', 'authorized')
                """)
            )
        assert repo.update_status("CLM-TEST001", "completed") is True
        latest = repo.get_authorization("CLM-TEST001")
        assert latest["reimbursement_id"] == "RENT-NEWER"
        assert latest["status"] == "completed"
        older = repo.get_by_reimbursement_id("RENT-OLDER")
        assert older is not None
        assert older["status"] == "authorized"
