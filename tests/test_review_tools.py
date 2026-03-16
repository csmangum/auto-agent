"""Unit tests for claim review tools."""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


@pytest.fixture(autouse=True)
def _temp_claims_db(tmp_path, monkeypatch):
    """Use a temporary SQLite DB for all review tests."""
    from claim_agent.db.database import init_db

    db_path = tmp_path / "claims.db"
    monkeypatch.setenv("CLAIMS_DB_PATH", str(db_path))
    init_db(str(db_path))


def _seed_claim(status: str = "settled", claim_type: str = "partial_loss") -> str:
    """Seed a claim and workflow run, return claim_id."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    repo = ClaimRepository()
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Rear-ended at stoplight.",
            damage_description="Rear bumper damage.",
            estimated_damage=4500.0,
        )
    )
    repo.update_claim_status(claim_id, status, claim_type=claim_type, skip_validation=True)
    repo.save_workflow_result(claim_id, claim_type, '{"claim_type":"partial_loss"}', "Workflow output summary.")
    return claim_id


class TestGetClaimProcessContext:
    def test_returns_context_for_existing_claim(self):
        from claim_agent.tools.review_tools import get_claim_process_context

        claim_id = _seed_claim()
        result = json.loads(get_claim_process_context.run(claim_id=claim_id))
        assert result["claim"]["id"] == claim_id
        assert result["claim"]["status"] == "settled"
        assert result["claim"]["claim_type"] == "partial_loss"
        assert "audit_log" in result
        assert "workflow_runs" in result
        assert len(result["workflow_runs"]) >= 1
        assert "notes" in result

    def test_raises_for_nonexistent_claim(self):
        from claim_agent.exceptions import ClaimNotFoundError
        from claim_agent.tools.review_tools import get_claim_process_context

        with pytest.raises(ClaimNotFoundError):
            get_claim_process_context.run(claim_id="CLM-NONEXISTENT")


class TestRecordClaimReview:
    def test_record_claim_review_persists_to_audit_log(self):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.db.audit_events import AUDIT_EVENT_CLAIM_REVIEW

        claim_id = _seed_claim()
        repo = ClaimRepository()
        report_json = '{"claim_id":"' + claim_id + '","overall_pass":true,"issues":[],"compliance_checks":[],"recommendations":[]}'
        repo.record_claim_review(claim_id, report_json, "supervisor-1")

        history, _ = repo.get_claim_history(claim_id)
        review_entries = [h for h in history if h["action"] == AUDIT_EVENT_CLAIM_REVIEW]
        assert len(review_entries) == 1
        assert "overall_pass" in review_entries[0]["details"]

    def test_record_claim_review_raises_for_nonexistent_claim(self):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.exceptions import ClaimNotFoundError

        repo = ClaimRepository()
        with pytest.raises(ClaimNotFoundError):
            repo.record_claim_review("CLM-NONEXISTENT", "{}", "supervisor")
