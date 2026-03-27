"""Tests for incident management and BI allocation routes defined in claims_incidents.py.

Covers:
- POST /incidents         (create_incident)
- GET  /incidents/{id}    (get_incident)
- POST /claim-links       (create_claim_link)
- GET  /claims/{id}/related (get_related_claims)
- POST /bi-allocation     (allocate_bi)
"""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared test payloads
# ---------------------------------------------------------------------------

VEHICLE_PAYLOAD = {
    "policy_number": "POL-001",
    "vin": "1HGCM82633A004352",
    "vehicle_year": 2020,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "damage_description": "Rear bumper cracked, trunk lid damaged.",
}

INCIDENT_PAYLOAD = {
    "incident_date": "2024-01-15",
    "incident_description": "Two-car collision at intersection.",
    "vehicles": [VEHICLE_PAYLOAD],
}

MULTI_VEHICLE_INCIDENT_PAYLOAD = {
    "incident_date": "2024-01-15",
    "incident_description": "Multi-vehicle pile-up on highway.",
    "vehicles": [
        VEHICLE_PAYLOAD,
        {
            "policy_number": "POL-002",
            "vin": "2T1BURHE0JC012345",
            "vehicle_year": 2019,
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "damage_description": "Front bumper and hood damage.",
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all tests in this module."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Reset rate-limit buckets before each test to avoid spurious 429s."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Test client wired to the FastAPI application."""
    from claim_agent.api.server import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /incidents - create_incident
# ---------------------------------------------------------------------------


def test_create_incident(client):
    """create_incident creates an incident and returns incident_id and claim_ids."""
    resp = client.post("/api/v1/incidents", json=INCIDENT_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "incident_id" in data
    assert isinstance(data["incident_id"], str)
    assert len(data["incident_id"]) > 0
    assert "claim_ids" in data
    assert isinstance(data["claim_ids"], list)
    assert len(data["claim_ids"]) == 1
    assert "message" in data


def test_create_incident_multi_vehicle(client):
    """create_incident creates one claim per vehicle in a multi-vehicle incident."""
    resp = client.post("/api/v1/incidents", json=MULTI_VEHICLE_INCIDENT_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "incident_id" in data
    assert len(data["claim_ids"]) == 2


def test_create_incident_idempotency(client):
    """create_incident returns cached result for duplicate idempotency key."""
    idem_key = "test-idem-incident-001"
    resp1 = client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()

    resp2 = client.post(
        "/api/v1/incidents",
        json=INCIDENT_PAYLOAD,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data1["incident_id"] == data2["incident_id"]


def test_create_incident_missing_vehicles_returns_422(client):
    """create_incident rejects payloads with no vehicles."""
    resp = client.post(
        "/api/v1/incidents",
        json={"incident_date": "2024-01-15", "incident_description": "No vehicles"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /incidents/{incident_id} - get_incident
# ---------------------------------------------------------------------------


def test_get_incident(client):
    """get_incident returns incident details and linked claims."""
    create_resp = client.post("/api/v1/incidents", json=INCIDENT_PAYLOAD)
    assert create_resp.status_code == 200
    incident_id = create_resp.json()["incident_id"]

    resp = client.get(f"/api/v1/incidents/{incident_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "incident" in data
    assert "claims" in data
    assert data["incident"]["id"] == incident_id
    assert isinstance(data["claims"], list)
    assert len(data["claims"]) == 1


def test_get_incident_not_found_returns_404(client):
    """get_incident returns 404 for unknown incident IDs."""
    resp = client.get("/api/v1/incidents/DOES-NOT-EXIST")
    assert resp.status_code == 404


def test_get_incident_multi_vehicle_returns_all_claims(client):
    """get_incident returns all linked claims for a multi-vehicle incident."""
    create_resp = client.post("/api/v1/incidents", json=MULTI_VEHICLE_INCIDENT_PAYLOAD)
    assert create_resp.status_code == 200
    incident_id = create_resp.json()["incident_id"]

    resp = client.get(f"/api/v1/incidents/{incident_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["claims"]) == 2


# ---------------------------------------------------------------------------
# POST /claim-links - create_claim_link
# ---------------------------------------------------------------------------


def test_create_claim_link(client):
    """create_claim_link links two claims and returns a link_id."""
    resp = client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST002",
            "link_type": "same_incident",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "link_id" in data
    assert "message" in data


def test_create_claim_link_opposing_carrier(client):
    """create_claim_link supports opposing_carrier link type."""
    resp = client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST002",
            "link_type": "opposing_carrier",
            "opposing_carrier": "OtherInsuranceCo",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "link_id" in data


def test_create_claim_link_subrogation(client):
    """create_claim_link supports subrogation link type."""
    resp = client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST002",
            "link_type": "subrogation",
        },
    )
    assert resp.status_code == 200


def test_create_claim_link_duplicate_returns_409(client):
    """create_claim_link returns 409 when link already exists."""
    link_payload = {
        "claim_id_a": "CLM-TEST001",
        "claim_id_b": "CLM-TEST002",
        "link_type": "same_incident",
    }
    resp1 = client.post("/api/v1/claim-links", json=link_payload)
    assert resp1.status_code == 200

    resp2 = client.post("/api/v1/claim-links", json=link_payload)
    assert resp2.status_code == 409


def test_create_claim_link_self_link_returns_422(client):
    """create_claim_link rejects self-links (same claim_id_a and claim_id_b)."""
    resp = client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST001",
            "link_type": "same_incident",
        },
    )
    assert resp.status_code == 422


def test_create_claim_link_unknown_claim_returns_404(client):
    """create_claim_link returns 404 for unknown claim IDs."""
    resp = client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-DOES-NOT-EXIST",
            "link_type": "same_incident",
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/related - get_related_claims
# ---------------------------------------------------------------------------


def test_get_related_claims(client):
    """get_related_claims returns related claim IDs after linking."""
    client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST002",
            "link_type": "same_incident",
        },
    )

    resp = client.get("/api/v1/claims/CLM-TEST001/related")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert "related_claim_ids" in data
    assert "CLM-TEST002" in data["related_claim_ids"]


def test_get_related_claims_no_links(client):
    """get_related_claims returns empty list when claim has no links."""
    resp = client.get("/api/v1/claims/CLM-TEST001/related")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert data["related_claim_ids"] == []


def test_get_related_claims_filter_by_link_type(client):
    """get_related_claims filters by link_type query parameter."""
    client.post(
        "/api/v1/claim-links",
        json={
            "claim_id_a": "CLM-TEST001",
            "claim_id_b": "CLM-TEST002",
            "link_type": "subrogation",
        },
    )

    resp_filtered = client.get("/api/v1/claims/CLM-TEST001/related?link_type=subrogation")
    assert resp_filtered.status_code == 200
    data = resp_filtered.json()
    assert "CLM-TEST002" in data["related_claim_ids"]

    resp_other = client.get("/api/v1/claims/CLM-TEST001/related?link_type=same_incident")
    assert resp_other.status_code == 200
    assert "CLM-TEST002" not in resp_other.json()["related_claim_ids"]


def test_get_related_claims_unknown_claim_returns_404(client):
    """get_related_claims returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOES-NOT-EXIST/related")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /bi-allocation - allocate_bi
# ---------------------------------------------------------------------------


def test_bi_allocation_proportional(client):
    """allocate_bi returns proportional allocations when limit is exceeded."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-TEST001",
            "bi_per_accident_limit": 100000.0,
            "allocation_method": "proportional",
            "claimant_demands": [
                {"claimant_id": "C1", "demanded_amount": 80000.0},
                {"claimant_id": "C2", "demanded_amount": 60000.0},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "allocations" in data
    assert data["limit_exceeded"] is True
    assert len(data["allocations"]) == 2
    total_allocated = sum(a["allocated"] for a in data["allocations"])
    assert abs(total_allocated - 100000.0) < 0.01


def test_bi_allocation_equal(client):
    """allocate_bi supports equal allocation method."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-TEST001",
            "bi_per_accident_limit": 100000.0,
            "allocation_method": "equal",
            "claimant_demands": [
                {"claimant_id": "C1", "demanded_amount": 80000.0},
                {"claimant_id": "C2", "demanded_amount": 60000.0},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit_exceeded"] is True
    assert len(data["allocations"]) == 2


def test_bi_allocation_severity_weighted(client):
    """allocate_bi supports severity_weighted allocation method."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-TEST001",
            "bi_per_accident_limit": 100000.0,
            "allocation_method": "severity_weighted",
            "claimant_demands": [
                {"claimant_id": "C1", "demanded_amount": 80000.0, "injury_severity": 8.0},
                {"claimant_id": "C2", "demanded_amount": 60000.0, "injury_severity": 4.0},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit_exceeded"] is True


def test_bi_allocation_no_excess(client):
    """allocate_bi returns full demands when total is within limit."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-TEST001",
            "bi_per_accident_limit": 200000.0,
            "allocation_method": "proportional",
            "claimant_demands": [
                {"claimant_id": "C1", "demanded_amount": 50000.0},
                {"claimant_id": "C2", "demanded_amount": 30000.0},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit_exceeded"] is False
    for alloc in data["allocations"]:
        assert alloc["shortfall"] == 0


def test_bi_allocation_unknown_claim_returns_404(client):
    """allocate_bi returns 404 for unknown claim IDs."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-DOES-NOT-EXIST",
            "bi_per_accident_limit": 100000.0,
            "claimant_demands": [
                {"claimant_id": "C1", "demanded_amount": 50000.0},
            ],
        },
    )
    assert resp.status_code == 404


def test_bi_allocation_missing_fields_returns_422(client):
    """allocate_bi rejects payloads missing required fields."""
    resp = client.post(
        "/api/v1/bi-allocation",
        json={
            "claim_id": "CLM-TEST001",
            # missing bi_per_accident_limit and claimant_demands
        },
    )
    assert resp.status_code == 422
