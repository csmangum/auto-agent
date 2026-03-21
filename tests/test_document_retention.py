"""Tests for claim_documents retention enforcement (issue #284)."""

import json

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection
from claim_agent.db.document_repository import DocumentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.main import app
from claim_agent.models.claim import ClaimInput
from claim_agent.services.document_retention import run_document_retention_enforce


@pytest.fixture
def claim_with_documents(temp_db):
    """Single claim with two documents: one past retention, one future."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-DOC-RET",
        vin="1HGBH41JXMN109186",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test.",
        damage_description="Dent.",
    )
    claim_id = repo.create_claim(claim_input)
    doc_repo = DocumentRepository(db_path=temp_db)
    past_id = doc_repo.add_document(
        claim_id,
        "past_ret.pdf",
        document_type="pdf",
        retention_date="2020-06-01",
    )
    future_id = doc_repo.add_document(
        claim_id,
        "future_ret.pdf",
        document_type="pdf",
        retention_date="2035-06-01",
    )
    return {
        "db_path": temp_db,
        "claim_id": claim_id,
        "past_id": past_id,
        "future_id": future_id,
    }


def test_list_documents_past_retention_filters_cutoff(claim_with_documents):
    db_path = claim_with_documents["db_path"]
    doc_repo = DocumentRepository(db_path=db_path)
    rows = doc_repo.list_documents_past_retention("2025-01-01")
    ids = {int(r["id"]) for r in rows}
    assert claim_with_documents["past_id"] in ids
    assert claim_with_documents["future_id"] not in ids


def test_run_document_retention_enforce_dry_run(claim_with_documents):
    db_path = claim_with_documents["db_path"]
    out = run_document_retention_enforce(
        db_path=db_path, cutoff_date="2025-01-01", dry_run=True
    )
    assert out["dry_run"] is True
    assert out["document_count"] >= 1
    assert any(d["id"] == claim_with_documents["past_id"] for d in out["documents"])


def test_run_document_retention_enforce_soft_archives_and_audits(claim_with_documents):
    db_path = claim_with_documents["db_path"]
    claim_id = claim_with_documents["claim_id"]
    past_id = claim_with_documents["past_id"]

    out = run_document_retention_enforce(
        db_path=db_path, cutoff_date="2025-01-01", dry_run=False
    )
    assert out["enforced_count"] >= 1
    assert past_id in out["enforced_document_ids"]
    assert out["failed_count"] == 0

    doc_repo = DocumentRepository(db_path=db_path)
    doc = doc_repo.get_document(past_id)
    assert doc is not None
    assert doc.get("retention_enforced_at")

    with get_connection(db_path) as conn:
        row = conn.execute(
            text(
                "SELECT action, after_state FROM claim_audit_log "
                "WHERE claim_id = :cid AND action = 'document_retention_enforced' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"cid": claim_id},
        ).fetchone()
    assert row is not None
    state = json.loads(row[1])
    assert state["document_id"] == past_id


def test_second_enforce_is_idempotent(claim_with_documents):
    db_path = claim_with_documents["db_path"]
    run_document_retention_enforce(db_path=db_path, cutoff_date="2025-01-01", dry_run=False)
    with get_connection(db_path) as conn:
        n1 = conn.execute(
            text(
                "SELECT COUNT(*) FROM claim_audit_log WHERE action = 'document_retention_enforced'"
            )
        ).scalar()
    run_document_retention_enforce(db_path=db_path, cutoff_date="2025-01-01", dry_run=False)
    with get_connection(db_path) as conn:
        n2 = conn.execute(
            text(
                "SELECT COUNT(*) FROM claim_audit_log WHERE action = 'document_retention_enforced'"
            )
        ).scalar()
    assert n2 == n1


def test_cli_document_retention_enforce_dry_run(claim_with_documents, monkeypatch):
    db_path = claim_with_documents["db_path"]
    monkeypatch.setenv("CLAIMS_DB_PATH", db_path)
    reload_settings()
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["document-retention-enforce", "--dry-run", "--as-of", "2025-01-01"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert data["document_count"] >= 1
