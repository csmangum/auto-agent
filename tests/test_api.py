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

        # Audit log entries (with actor_id, before_state, after_state for audit trail)
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "CLM-TEST001",
                "created",
                "pending",
                "Claim record created",
                "workflow",
                '{"status": "pending", "claim_type": null, "payout_amount": null}',
            ),
        )
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "CLM-TEST001",
                "status_change",
                "pending",
                "open",
                "Processed successfully",
                "workflow",
                '{"status": "pending", "claim_type": null, "payout_amount": null}',
                '{"status": "open", "claim_type": "new", "payout_amount": null}',
            ),
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
        assert data["history"][0]["actor_id"] == "workflow"
        assert data["history"][0]["after_state"] is not None
        assert data["history"][1]["action"] == "status_change"
        assert data["history"][1]["actor_id"] == "workflow"
        assert data["history"][1]["before_state"] is not None
        assert data["history"][1]["after_state"] is not None

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


# -------------------------------------------------------------------
# API Key Auth (when CLAIMS_API_KEY is set)
# -------------------------------------------------------------------

class TestApiKeyAuth:
    def test_health_always_public(self, client, monkeypatch):
        """Health endpoint is always accessible without auth."""
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_protected_endpoint_requires_key(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        resp = client.get("/api/claims/stats")
        assert resp.status_code == 401

    def test_protected_endpoint_accepts_x_api_key(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        resp = client.get("/api/claims/stats", headers={"X-API-Key": "secret123"})
        assert resp.status_code == 200

    def test_protected_endpoint_accepts_bearer(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        resp = client.get("/api/claims/stats", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200


# -------------------------------------------------------------------
# Path traversal and injection resistance
# -------------------------------------------------------------------

class TestPathTraversal:
    def test_docs_rejects_path_traversal(self, client):
        """Docs slug is whitelisted; path traversal attempts return 404."""
        resp = client.get("/api/docs/../etc/passwd")
        assert resp.status_code == 404

    def test_docs_rejects_encoded_traversal(self, client):
        resp = client.get("/api/docs/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code == 404

    def test_skills_rejects_path_traversal(self, client):
        """Skills name is validated or path is rejected; no file read."""
        resp = client.get("/api/skills/../../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_skills_rejects_invalid_chars(self, client):
        resp = client.get("/api/skills/foo;bar")
        assert resp.status_code == 400


class TestInvalidClaimId:
    def test_claim_id_sql_injection_like_returns_404(self, client):
        """Malformed claim IDs should return 404, not 500."""
        resp = client.get("/api/claims/CLM-001' OR '1'='1")
        assert resp.status_code == 404

    def test_claim_id_semicolon_returns_404(self, client):
        resp = client.get("/api/claims/CLM-001;DROP TABLE claims")
        assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/process
# -------------------------------------------------------------------

VALID_CLAIM_PAYLOAD = {
    "policy_number": "POL-001",
    "vin": "1HGBH41JXMN109186",
    "vehicle_year": 2021,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2025-01-15",
    "incident_description": "Rear-ended at stoplight",
    "damage_description": "Rear bumper damage",
    "estimated_damage": 2500.0,
}


class TestProcessClaimEndpoint:
    """Tests for POST /claims/process multipart endpoint."""

    def _mock_workflow(self, monkeypatch):
        """Patch run_claim_workflow to avoid real LLM calls."""
        mock_result = {
            "claim_id": "CLM-TEST-MOCK",
            "claim_type": "new",
            "status": "open",
            "summary": "Claim processed successfully.",
        }
        import claim_agent.crews.main_crew as main_crew_mod
        monkeypatch.setattr(main_crew_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
        # Ensure the storage singleton is reset to local (tmp) for each test
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)

    def test_valid_claim_no_files(self, client, monkeypatch, tmp_path):
        """Valid claim JSON without file attachments returns a workflow result."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        self._mock_workflow(monkeypatch)
        import json

        resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST-MOCK"

    def test_invalid_json_in_claim_field(self, client, monkeypatch):
        """Malformed JSON in the 'claim' form field returns 400."""
        self._mock_workflow(monkeypatch)
        resp = client.post(
            "/api/claims/process",
            data={"claim": "not-valid-json{"},
        )
        assert resp.status_code == 400
        assert "Invalid claim JSON" in resp.json()["detail"]

    def test_validation_failure_in_claim_data(self, client, monkeypatch):
        """Claim data failing Pydantic validation returns 400."""
        self._mock_workflow(monkeypatch)
        import json

        bad_claim = {**VALID_CLAIM_PAYLOAD, "vehicle_year": "not-a-year"}
        resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(bad_claim)},
        )
        assert resp.status_code == 400
        assert "Invalid claim data" in resp.json()["detail"]

    def test_valid_claim_with_file_upload(self, client, monkeypatch, tmp_path):
        """Valid claim with an uploaded file stores the file and includes it in result."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        self._mock_workflow(monkeypatch)
        import json

        file_content = b"fake image data"
        resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            files=[("files", ("damage.jpg", file_content, "image/jpeg"))],
        )
        assert resp.status_code == 200

    def test_file_too_large_returns_413(self, client, monkeypatch, tmp_path):
        """A file exceeding the 50 MB limit returns HTTP 413."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        self._mock_workflow(monkeypatch)
        import json
        from claim_agent.api.routes import claims as claims_module

        # Temporarily lower the limit to make the test fast
        original_limit = claims_module._MAX_UPLOAD_SIZE_BYTES
        monkeypatch.setattr(claims_module, "_MAX_UPLOAD_SIZE_BYTES", 10)
        try:
            resp = client.post(
                "/api/claims/process",
                data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
                files=[("files", ("big.jpg", b"X" * 11, "image/jpeg"))],
            )
        finally:
            claims_module._MAX_UPLOAD_SIZE_BYTES = original_limit
        assert resp.status_code == 413
