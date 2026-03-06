"""Tests for the FastAPI backend API endpoints."""

import pytest
from fastapi.testclient import TestClient

from claim_agent.db.database import init_db, get_connection


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    """Use a temporary database for all tests."""
    db_path = str(tmp_path / "test_claims.db")
    monkeypatch.setenv("CLAIMS_DB_PATH", db_path)
    # Reset the schema init cache so the new path is picked up
    from claim_agent.db import database
    database._schema_initialized.clear()
    init_db(db_path)
    # Seed some test data
    _seed_test_data(db_path)
    yield


def _seed_test_data(db_path: str):
    """Insert test claims, audit log entries, and workflow runs."""
    with get_connection(db_path) as conn:
        # Claims
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST001", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord",
             "2025-01-15", "Rear-ended at stoplight", "Rear bumper damage", 2500.0,
             "new", "open"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST002", "POL-002", "5YJSA1E26HF123456", 2020, "Tesla", "Model 3",
             "2025-01-20", "Flash flood", "Vehicle submerged", 45000.0,
             "total_loss", "closed"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST003", "POL-003", "3VWDX7AJ5DM999999", 2019, "Volkswagen", "Jetta",
             "2025-01-22", "Staged accident", "Front bumper destroyed", 35000.0,
             "fraud", "fraud_suspected"),
        )

        # Audit log entries
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, new_status, details) "
            "VALUES (?, ?, ?, ?)",
            ("CLM-TEST001", "created", "pending", "Claim record created"),
        )
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details) "
            "VALUES (?, ?, ?, ?, ?)",
            ("CLM-TEST001", "status_changed", "pending", "open", "Processed successfully"),
        )

        # Workflow run
        conn.execute(
            "INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output) "
            "VALUES (?, ?, ?, ?)",
            ("CLM-TEST001", "new", "new\nFirst-time claim", "Claim assigned and opened"),
        )


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app
    return TestClient(app)


# -------------------------------------------------------------------
# Claims endpoints
# -------------------------------------------------------------------

class TestClaimsStats:
    def test_returns_stats(self, client):
        resp = client.get("/api/claims/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_claims"] == 3
        assert "by_status" in data
        assert "by_type" in data
        assert data["by_status"]["open"] == 1
        assert data["by_status"]["closed"] == 1
        assert data["by_status"]["fraud_suspected"] == 1


class TestClaimsList:
    def test_list_all(self, client):
        resp = client.get("/api/claims")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["claims"]) == 3

    def test_filter_by_status(self, client):
        resp = client.get("/api/claims?status=open")
        data = resp.json()
        assert data["total"] == 1
        assert data["claims"][0]["id"] == "CLM-TEST001"

    def test_filter_by_type(self, client):
        resp = client.get("/api/claims?claim_type=fraud")
        data = resp.json()
        assert data["total"] == 1
        assert data["claims"][0]["id"] == "CLM-TEST003"

    def test_pagination(self, client):
        resp = client.get("/api/claims?limit=1&offset=0")
        data = resp.json()
        assert len(data["claims"]) == 1
        assert data["total"] == 3


class TestClaimDetail:
    def test_get_existing(self, client):
        resp = client.get("/api/claims/CLM-TEST001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "CLM-TEST001"
        assert data["policy_number"] == "POL-001"
        assert data["status"] == "open"

    def test_not_found(self, client):
        resp = client.get("/api/claims/CLM-NOTEXIST")
        assert resp.status_code == 404


class TestClaimHistory:
    def test_get_history(self, client):
        resp = client.get("/api/claims/CLM-TEST001/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST001"
        assert len(data["history"]) == 2
        assert data["history"][0]["action"] == "created"

    def test_not_found(self, client):
        resp = client.get("/api/claims/CLM-NOTEXIST/history")
        assert resp.status_code == 404


class TestClaimWorkflows:
    def test_get_workflows(self, client):
        resp = client.get("/api/claims/CLM-TEST001/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["claim_type"] == "new"

    def test_empty_workflows(self, client):
        resp = client.get("/api/claims/CLM-TEST002/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["workflows"]) == 0


# -------------------------------------------------------------------
# Metrics endpoints
# -------------------------------------------------------------------

class TestMetrics:
    def test_global_metrics_empty(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["global_stats"]["total_claims"] == 0

    def test_claim_metrics_not_found(self, client):
        resp = client.get("/api/metrics/CLM-TEST001")
        assert resp.status_code == 404


# -------------------------------------------------------------------
# Documentation endpoints
# -------------------------------------------------------------------

class TestDocs:
    def test_list_docs(self, client):
        resp = client.get("/api/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert "pages" in data
        assert len(data["pages"]) > 0
        # Check some known pages exist
        slugs = [p["slug"] for p in data["pages"]]
        assert "architecture" in slugs
        assert "observability" in slugs

    def test_get_doc_page(self, client):
        resp = client.get("/api/docs/architecture")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "architecture"
        assert data["title"] == "Architecture"
        assert "# Architecture" in data["content"]

    def test_doc_not_found(self, client):
        resp = client.get("/api/docs/nonexistent-page")
        assert resp.status_code == 404


# -------------------------------------------------------------------
# Skills endpoints
# -------------------------------------------------------------------

class TestSkills:
    def test_list_skills(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "Core Routing" in data["groups"]
        # Router should be in Core Routing
        router_skills = data["groups"]["Core Routing"]
        assert any(s["name"] == "router" for s in router_skills)

    def test_get_skill(self, client):
        resp = client.get("/api/skills/router")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "router"
        assert data["role"]  # Should have a role
        assert data["content"]  # Should have content

    def test_skill_not_found(self, client):
        resp = client.get("/api/skills/nonexistent_skill")
        assert resp.status_code == 404


# -------------------------------------------------------------------
# System endpoints
# -------------------------------------------------------------------

class TestSystemConfig:
    def test_get_config(self, client):
        resp = client.get("/api/system/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "escalation" in data
        assert "fraud" in data
        assert "valuation" in data
        assert "partial_loss" in data
        assert "token_budgets" in data
        assert "crew_verbose" in data
        # Check specific values exist
        assert "confidence_threshold" in data["escalation"]
        assert "max_tokens_per_claim" in data["token_budgets"]


class TestSystemHealth:
    def test_health_check(self, client):
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["total_claims"] == 3


class TestAgentsCatalog:
    def test_get_catalog(self, client):
        resp = client.get("/api/system/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "crews" in data
        crews = data["crews"]
        assert len(crews) == 6
        # Check crew names
        crew_names = [c["name"] for c in crews]
        assert "Router Crew" in crew_names
        assert "Fraud Detection Crew" in crew_names
        # Check agents within a crew
        router_crew = next(c for c in crews if c["name"] == "Router Crew")
        assert len(router_crew["agents"]) == 1
        assert router_crew["agents"][0]["name"] == "Claim Router Supervisor"


class TestHealthEndpoint:
    def test_basic_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
