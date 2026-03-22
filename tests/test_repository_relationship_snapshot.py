"""Tests for ClaimRepository.build_relationship_snapshot (fraud graph)."""

from sqlalchemy import text

from claim_agent.db.database import get_connection
from claim_agent.db.repository import (
    RELATION_SHARED_ADDRESS,
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


def test_build_relationship_snapshot_2hop_path_exists(temp_db):
    """2-hop path: root→hop1 via shared address, hop1→hop2 via shared phone.

    At depth 1 only hop1 is visible; at depth 2 hop2 appears and has an edge
    from hop1.
    """
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINROOT11111111111")
    hop1_id = _claim(repo, vin="VINHOP1AAAAAAAAAAAA")
    hop2_id = _claim(repo, vin="VINHOP2BBBBBBBBBBB")

    shared_address = "123 Fraud St, Testville CA 90001"
    repo.add_claim_party(root_id, ClaimPartyInput(party_type="claimant", address=shared_address))
    repo.add_claim_party(hop1_id, ClaimPartyInput(party_type="claimant", address=shared_address))

    shared_phone = "4155550100"
    repo.add_claim_party(hop1_id, ClaimPartyInput(party_type="claimant", phone=shared_phone))
    repo.add_claim_party(hop2_id, ClaimPartyInput(party_type="claimant", phone=shared_phone))

    # Depth 1: only hop1 visible (hop2 not reachable from root in one hop)
    snap1 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10, max_depth=1)
    node_ids_1 = {n["id"] for n in snap1["nodes"]}
    assert hop1_id in node_ids_1
    assert hop2_id not in node_ids_1
    assert snap1["node_count"] == 2  # root + hop1

    # Depth 2: hop2 now visible
    snap2 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10, max_depth=2)
    node_ids_2 = {n["id"] for n in snap2["nodes"]}
    assert hop2_id in node_ids_2
    assert snap2["node_count"] == 3  # root + hop1 + hop2

    # Edge from hop1 to hop2 exists with shared_phone relation
    hop1_to_hop2 = next(
        (e for e in snap2["edges"] if e["from"] == hop1_id and e["to"] == hop2_id),
        None,
    )
    assert hop1_to_hop2 is not None
    assert RELATION_SHARED_PHONE in hop1_to_hop2["relations"]

    # Edge from root to hop1 still exists
    root_to_hop1 = next(
        (e for e in snap2["edges"] if e["from"] == root_id and e["to"] == hop1_id),
        None,
    )
    assert root_to_hop1 is not None
    assert RELATION_SHARED_ADDRESS in root_to_hop1["relations"]


def test_build_relationship_snapshot_2hop_budget_caps_hop2(temp_db):
    """Node budget is shared across hops: when hop1 fills the budget, hop2 is excluded."""
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINROOT22222222222")
    hop1_ids = [_claim(repo, vin=f"VINLNK{i}XXXXXXXXXX") for i in range(3)]
    hop2_id = _claim(repo, vin="VINHOP2CCCCCCCCCCC")

    shared_address = "456 Budget Ave, Testville CA 90002"
    shared_phone = "8005550199"

    repo.add_claim_party(root_id, ClaimPartyInput(party_type="claimant", address=shared_address))
    for hid in hop1_ids:
        repo.add_claim_party(hid, ClaimPartyInput(party_type="claimant", address=shared_address))

    # hop1[0] → hop2 via shared phone
    repo.add_claim_party(hop1_ids[0], ClaimPartyInput(party_type="claimant", phone=shared_phone))
    repo.add_claim_party(hop2_id, ClaimPartyInput(party_type="claimant", phone=shared_phone))

    # max_nodes=3 means hop1 fills the budget exactly; hop2 should be excluded
    snap3 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=3, max_depth=2)
    assert snap3["node_count"] == 4  # root + 3 hop1 nodes
    assert hop2_id not in {n["id"] for n in snap3["nodes"]}

    # max_nodes=4 leaves room for one hop2 node
    snap4 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=4, max_depth=2)
    assert snap4["node_count"] == 5  # root + 3 hop1 + 1 hop2
    assert hop2_id in {n["id"] for n in snap4["nodes"]}


def test_build_relationship_snapshot_depth_gt_2_treated_as_2(temp_db):
    """max_depth values greater than 2 are capped to 2 (not an error)."""
    repo = ClaimRepository(db_path=temp_db)
    root_id = _claim(repo, vin="VINROOT33333333333")
    hop1_id = _claim(repo, vin="VINHOP1DDDDDDDDDDD")
    hop2_id = _claim(repo, vin="VINHOP2EEEEEEEEEEE")

    shared_address = "789 Cap Blvd, Testville CA 90003"
    shared_phone = "6505551234"

    repo.add_claim_party(root_id, ClaimPartyInput(party_type="claimant", address=shared_address))
    repo.add_claim_party(hop1_id, ClaimPartyInput(party_type="claimant", address=shared_address))
    repo.add_claim_party(hop1_id, ClaimPartyInput(party_type="claimant", phone=shared_phone))
    repo.add_claim_party(hop2_id, ClaimPartyInput(party_type="claimant", phone=shared_phone))

    # max_depth=3 should behave identically to max_depth=2
    snap3 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10, max_depth=3)
    snap2 = repo.build_relationship_snapshot(claim_id=root_id, max_nodes=10, max_depth=2)

    assert snap3["node_count"] == snap2["node_count"]
    assert snap3["edge_count"] == snap2["edge_count"]
    assert {n["id"] for n in snap3["nodes"]} == {n["id"] for n in snap2["nodes"]}
