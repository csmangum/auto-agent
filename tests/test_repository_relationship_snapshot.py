"""Tests for ClaimRepository.build_relationship_snapshot (fraud graph)."""

from sqlalchemy import text

from claim_agent.db.database import get_connection
from claim_agent.db.repository import (
    RELATION_SHARED_EMAIL,
    RELATION_SHARED_PHONE,
    ClaimRepository,
)
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from claim_agent.utils.graph_contact_normalize import normalize_party_phone_for_graph


def _claim(repo: ClaimRepository, vin: str) -> str:
    return repo.create_claim(
        ClaimInput(
            policy_number=f"POL-{vin[:8]}",
            vin=vin,
            vehicle_year=2022,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-03-01",
            incident_description="Test incident.",
            damage_description="Scratch.",
        )
    )


def test_build_relationship_snapshot_shared_phone_different_formatting(temp_db):
    """Same normalized phone links claims; edge lists shared_phone and counts high-risk."""
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINROOT1111111111")
    other_id = _claim(repo, vin="VINOTH22222222222")
    repo.add_claim_party(
        root_id,
        ClaimPartyInput(party_type="claimant", phone="(555) 123-4567"),
    )
    repo.add_claim_party(
        other_id,
        ClaimPartyInput(party_type="claimant", phone="5551234567"),
    )

    snap = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10)
    assert snap["edge_count"] == 1
    assert snap["high_risk_link_count"] == 1
    assert snap["edges"][0]["to"] == other_id
    assert RELATION_SHARED_PHONE in snap["edges"][0]["relations"]
    assert "shared_vin" not in snap["edges"][0]["relations"]


def test_build_relationship_snapshot_shared_email_case_insensitive(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINAAAAAAAAAAAAAA")
    other_id = _claim(repo, vin="VINBBBBBBBBBBBBBB")
    repo.add_claim_party(
        root_id,
        ClaimPartyInput(party_type="claimant", email="  Person@Example.COM "),
    )
    repo.add_claim_party(
        other_id,
        ClaimPartyInput(party_type="witness", email="person@example.com"),
    )

    snap = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10)
    assert snap["edge_count"] == 1
    assert snap["high_risk_link_count"] == 1
    assert RELATION_SHARED_EMAIL in snap["edges"][0]["relations"]


def test_build_relationship_snapshot_respects_max_nodes(temp_db):
    """Related id set is capped to max_nodes (lexicographic sort of ids)."""
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINZZZZZZZZZZZZZZ")
    other_ids = [_claim(repo, vin=f"VINLINK{i}XXXXXXXX") for i in range(3)]
    repo.add_claim_party(root_id, ClaimPartyInput(party_type="claimant", phone="9998887777"))
    for cid in other_ids:
        repo.add_claim_party(cid, ClaimPartyInput(party_type="claimant", phone="9998887777"))

    snap = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=1)
    assert snap["node_count"] == 2
    assert snap["edge_count"] == 1


def test_normalize_helpers_match_sqlite_udf(temp_db):
    """SQLite graph_phone_digits UDF is registered and matches repository normalization."""
    with get_connection(temp_db) as conn:
        row = conn.execute(
            text("SELECT graph_phone_digits(:p)"),
            {"p": "+1 (555) 234-5678"},
        ).fetchone()
    assert row is not None
    assert row[0] == normalize_party_phone_for_graph("+1 (555) 234-5678")
