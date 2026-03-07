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
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status, priority, due_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST004", "POL-004", "2HGFG3B54CH123456", 2022, "Toyota", "Camry",
             "2025-01-25", "Low confidence routing", "Minor scratch", 500.0,
             "new", "needs_review", "high", "2025-01-26T12:00:00Z"),
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
        assert data["total_claims"] == 4
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
        assert data["total"] == 4
        assert len(data["claims"]) == 4

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
        assert data["total"] == 4


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


class TestReviewQueue:
    """Test review queue and adjuster action endpoints."""

    def test_review_queue_lists_needs_review(self, client):
        resp = client.get("/api/claims/review-queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "claims" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["claims"]) == 1
        assert data["claims"][0]["id"] == "CLM-TEST004"
        assert data["claims"][0]["status"] == "needs_review"
        assert data["claims"][0]["priority"] == "high"

    def test_assign_claim(self, client):
        resp = client.patch(
            "/api/claims/CLM-TEST004/assign",
            json={"assignee": "adjuster-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST004"
        assert data["assignee"] == "adjuster-1"

    def test_assign_not_found(self, client):
        resp = client.patch(
            "/api/claims/CLM-NOTEXIST/assign",
            json={"assignee": "adjuster-1"},
        )
        assert resp.status_code == 404

    def test_reject_claim(self, client):
        resp = client.post(
            "/api/claims/CLM-TEST004/review/reject",
            json={"reason": "Duplicate claim"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST004"
        assert data["status"] == "denied"

    def test_request_info(self, client):
        from claim_agent.db.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "UPDATE claims SET status = ?, priority = ?, due_at = ? WHERE id = ?",
                ("needs_review", "high", "2025-01-26T12:00:00Z", "CLM-TEST003"),
            )
        resp = client.post(
            "/api/claims/CLM-TEST003/review/request-info",
            json={"note": "Please provide damage photos"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST003"
        assert data["status"] == "pending_info"

    def test_escalate_to_siu(self, client):
        from claim_agent.db.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "UPDATE claims SET status = ?, priority = ?, due_at = ? WHERE id = ?",
                ("needs_review", "high", "2025-01-26T12:00:00Z", "CLM-TEST002"),
            )
        resp = client.post("/api/claims/CLM-TEST002/review/escalate-to-siu")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST002"
        assert data["status"] == "under_investigation"

    def test_approve_reprocesses_claim(self, client, monkeypatch):
        """Supervisor can approve claim and re-run workflow."""
        import claim_agent.api.routes.claims as claims_mod

        mock_result = {"claim_id": "CLM-TEST004", "status": "open", "claim_type": "new"}
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
        resp = client.post("/api/claims/CLM-TEST004/review/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST004"
        assert data["status"] == "open"

    def test_approve_requires_supervisor(self, client, monkeypatch):
        """Adjuster gets 403 for approve (supervisor+ only)."""
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster,sk-sup:supervisor")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        resp = client.post(
            "/api/claims/CLM-TEST004/review/approve",
            headers={"X-API-Key": "sk-adj"},
        )
        assert resp.status_code == 403

    def test_assign_not_needs_review_returns_400(self, client):
        """Assign on claim not in needs_review returns 400."""
        resp = client.patch(
            "/api/claims/CLM-TEST001/assign",
            json={"assignee": "adjuster-1"},
        )
        assert resp.status_code == 400
        assert "not in needs_review" in resp.json()["detail"]

    def test_reject_not_needs_review_returns_400(self, client):
        """Reject on claim not in needs_review returns 400."""
        resp = client.post(
            "/api/claims/CLM-TEST001/review/reject",
            json={"reason": "Duplicate"},
        )
        assert resp.status_code == 400
        assert "not in needs_review" in resp.json()["detail"]

    def test_review_queue_invalid_priority_returns_400(self, client):
        """Review queue with invalid priority returns 400."""
        resp = client.get("/api/claims/review-queue?priority=invalid")
        assert resp.status_code == 400
        assert "Invalid priority" in resp.json()["detail"]

    def test_assign_empty_assignee_returns_422(self, client):
        """Assign with empty assignee returns 422 (validation error)."""
        resp = client.patch(
            "/api/claims/CLM-TEST004/assign",
            json={"assignee": ""},
        )
        assert resp.status_code == 422


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
        assert data["total_claims"] == 4


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
# API Key Auth (when CLAIMS_API_KEY or API_KEYS is set)
# -------------------------------------------------------------------

def _auth_headers(key: str, use_bearer: bool = False):
    if use_bearer:
        return {"Authorization": f"Bearer {key}"}
    return {"X-API-Key": key}


class TestApiKeyAuth:
    def test_health_always_public(self, client, monkeypatch):
        """Health endpoint is always accessible without auth."""
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        monkeypatch.delenv("API_KEYS", raising=False)
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_protected_endpoint_requires_key(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        monkeypatch.delenv("API_KEYS", raising=False)
        resp = client.get("/api/claims/stats")
        assert resp.status_code == 401

    def test_protected_endpoint_accepts_x_api_key(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        monkeypatch.delenv("API_KEYS", raising=False)
        resp = client.get("/api/claims/stats", headers={"X-API-Key": "secret123"})
        assert resp.status_code == 200

    def test_protected_endpoint_accepts_bearer(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        monkeypatch.delenv("API_KEYS", raising=False)
        resp = client.get("/api/claims/stats", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_invalid_key_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "secret123")
        monkeypatch.delenv("API_KEYS", raising=False)
        resp = client.get("/api/claims/stats", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]


# -------------------------------------------------------------------
# RBAC (API_KEYS with roles)
# -------------------------------------------------------------------

class TestRBAC:
    """Test role-based access control with API_KEYS."""

    def _set_api_keys(self, monkeypatch, keys: str):
        monkeypatch.setenv("API_KEYS", keys)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)

    def test_adjuster_can_access_claims(self, client, monkeypatch):
        """Adjuster can access claims endpoints."""
        self._set_api_keys(monkeypatch, "sk-adj:adjuster")
        resp = client.get("/api/claims/stats", headers=_auth_headers("sk-adj"))
        assert resp.status_code == 200

    def test_adjuster_forbidden_metrics(self, client, monkeypatch):
        """Adjuster gets 403 for metrics (supervisor+ only)."""
        self._set_api_keys(monkeypatch, "sk-adj:adjuster")
        resp = client.get("/api/metrics", headers=_auth_headers("sk-adj"))
        assert resp.status_code == 403

    def test_adjuster_forbidden_system_config(self, client, monkeypatch):
        """Adjuster gets 403 for system/config (admin only)."""
        self._set_api_keys(monkeypatch, "sk-adj:adjuster")
        resp = client.get("/api/system/config", headers=_auth_headers("sk-adj"))
        assert resp.status_code == 403

    def test_supervisor_can_access_metrics(self, client, monkeypatch):
        """Supervisor can access metrics."""
        self._set_api_keys(monkeypatch, "sk-sup:supervisor")
        resp = client.get("/api/metrics", headers=_auth_headers("sk-sup"))
        assert resp.status_code == 200

    def test_supervisor_forbidden_system_config(self, client, monkeypatch):
        """Supervisor gets 403 for system/config (admin only)."""
        self._set_api_keys(monkeypatch, "sk-sup:supervisor")
        resp = client.get("/api/system/config", headers=_auth_headers("sk-sup"))
        assert resp.status_code == 403

    def test_admin_can_access_all(self, client, monkeypatch):
        """Admin can access claims, metrics, and system config."""
        self._set_api_keys(monkeypatch, "sk-admin:admin")
        headers = _auth_headers("sk-admin")
        assert client.get("/api/claims/stats", headers=headers).status_code == 200
        assert client.get("/api/metrics", headers=headers).status_code == 200
        assert client.get("/api/system/config", headers=headers).status_code == 200

    def test_adjuster_forbidden_reprocess(self, client, monkeypatch):
        """Adjuster gets 403 for reprocess (supervisor+ only)."""
        self._set_api_keys(monkeypatch, "sk-adj:adjuster")
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: {"claim_id": "CLM-TEST001"})
        resp = client.post(
            "/api/claims/CLM-TEST001/reprocess",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 403

    def test_supervisor_can_reprocess(self, client, monkeypatch):
        """Supervisor can call reprocess endpoint."""
        self._set_api_keys(monkeypatch, "sk-sup:supervisor")
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: {"claim_id": "CLM-TEST001"})
        resp = client.post(
            "/api/claims/CLM-TEST001/reprocess",
            headers=_auth_headers("sk-sup"),
        )
        assert resp.status_code == 200

    def test_reprocess_not_found_returns_404(self, client, monkeypatch):
        """Reprocess of non-existent claim returns 404."""
        self._set_api_keys(monkeypatch, "sk-sup:supervisor")
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: {"claim_id": "x"})
        resp = client.post(
            "/api/claims/CLM-NOTEXIST/reprocess",
            headers=_auth_headers("sk-sup"),
        )
        assert resp.status_code == 404


# -------------------------------------------------------------------
# JWT authentication (when JWT_SECRET is set)
# -------------------------------------------------------------------

class TestJWTAuth:
    """Test JWT Bearer token authentication."""

    def test_valid_jwt_with_role(self, client, monkeypatch):
        """Valid JWT with known secret and role is accepted."""
        jwt = pytest.importorskip("jwt")
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "user-123", "role": "admin"},
            "test-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/claims/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_expired_jwt_returns_401(self, client, monkeypatch):
        """Expired JWT returns 401."""
        jwt = pytest.importorskip("jwt")
        import time
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "user-123", "role": "admin", "exp": int(time.time()) - 3600},
            "test-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/claims/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_invalid_signature_returns_401(self, client, monkeypatch):
        """JWT with invalid signature returns 401."""
        jwt = pytest.importorskip("jwt")
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "user-123", "role": "admin"},
            "wrong-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/claims/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_jwt_missing_sub_returns_401(self, client, monkeypatch):
        """JWT without sub claim returns 401."""
        jwt = pytest.importorskip("jwt")
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        token = jwt.encode(
            {"role": "admin"},
            "test-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/claims/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_jwt_unknown_role_returns_401(self, client, monkeypatch):
        """JWT with role not in (adjuster, supervisor, admin) returns 401."""
        jwt = pytest.importorskip("jwt")
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        token = jwt.encode(
            {"sub": "user-123", "role": "superadmin"},
            "test-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/claims/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


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

    @pytest.fixture(autouse=True)
    def _mock_workflow_for_class(self, monkeypatch):
        """Ensure workflow is mocked for all tests in this class to avoid LLM calls."""
        mock_result = {
            "claim_id": "CLM-TEST-MOCK",
            "claim_type": "new",
            "status": "open",
            "summary": "Claim processed successfully.",
        }
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
        yield

    def _mock_workflow(self, monkeypatch):
        """Patch run_claim_workflow to avoid real LLM calls."""
        mock_result = {
            "claim_id": "CLM-TEST-MOCK",
            "claim_type": "new",
            "status": "open",
            "summary": "Claim processed successfully.",
        }
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
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

    def test_valid_claim_with_files_creates_single_claim(self, client, monkeypatch, tmp_path):
        """Process claim with file upload creates exactly one claim and stores attachment."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        self._mock_workflow(monkeypatch)
        import json

        with get_connection() as conn:
            count_before = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"]

        resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            files=[("files", ("damage.jpg", b"fake image data", "image/jpeg"))],
        )
        assert resp.status_code == 200

        with get_connection() as conn:
            count_after = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"]
            # Exactly one new claim (no duplicate creation)
            assert count_after == count_before + 1

    def test_audit_log_records_actor_id_when_authenticated(self, client, monkeypatch, tmp_path):
        """When processing with API key, claim_audit_log records authenticated identity."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        monkeypatch.setenv("API_KEYS", "sk-audit-test:adjuster")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        import json

        resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            headers={"X-API-Key": "sk-audit-test"},
        )
        assert resp.status_code == 200
        # Find the claim created by create_claim (first audit entry, before workflow runs)
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT claim_id, actor_id FROM claim_audit_log WHERE action = 'created' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert rows
        # actor_id for 'created' comes from process_claim's create_claim; should be key identity
        assert rows["actor_id"].startswith("key-"), f"Expected key identity, got {rows['actor_id']}"

    def test_attachment_download_returns_file(self, client, monkeypatch, tmp_path):
        """GET /claims/{claim_id}/attachments/{key} serves the file for local storage."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)

        storage = factory_mod.get_storage_adapter()
        stored_key = storage.save(
            claim_id="CLM-TEST001",
            filename="test_photo.jpg",
            content=b"fake image content",
        )
        resp = client.get(f"/api/claims/CLM-TEST001/attachments/{stored_key}")
        assert resp.status_code == 200
        assert resp.content == b"fake image content"

    def test_attachment_download_claim_not_found(self, client, monkeypatch, tmp_path):
        """Attachment download returns 404 for non-existent claim."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        resp = client.get("/api/claims/CLM-NONEXISTENT/attachments/abc123_photo.jpg")
        assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/process/async and GET /claims/{id}/stream
# -------------------------------------------------------------------


class TestProcessClaimAsyncEndpoint:
    """Tests for POST /claims/process/async and GET /claims/{id}/stream."""

    @pytest.fixture(autouse=True)
    def _mock_workflow_for_class(self, monkeypatch):
        mock_result = {
            "claim_id": "CLM-ASYNC-MOCK",
            "claim_type": "new",
            "status": "open",
            "summary": "Claim processed.",
        }
        import claim_agent.api.routes.claims as claims_mod
        monkeypatch.setattr(claims_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
        yield

    def test_async_returns_claim_id_immediately(self, client, monkeypatch, tmp_path):
        """Async process returns claim_id immediately without waiting for workflow."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import json

        resp = client.post(
            "/api/claims/process/async",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "claim_id" in data
        assert data["claim_id"].startswith("CLM-")

    def test_stream_returns_sse_events(self, client, monkeypatch, tmp_path):
        """Stream endpoint returns SSE-formatted events for existing claim."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        import claim_agent.api.routes.claims as claims_mod
        import json

        # Mock workflow to return the actual claim_id (from existing_claim_id) and
        # update the DB to a terminal status so the SSE stream terminates promptly.
        def mock_wf(claim_data, llm=None, existing_claim_id=None, *, actor_id=None):
            if existing_claim_id:
                from claim_agent.db.database import get_db_path
                from claim_agent.db.repository import ClaimRepository
                ClaimRepository(db_path=get_db_path()).update_claim_status(
                    existing_claim_id, "open"
                )
            return {
                "claim_id": existing_claim_id or "CLM-MOCK",
                "claim_type": "new",
                "status": "open",
                "summary": "Claim processed.",
            }

        monkeypatch.setattr(claims_mod, "run_claim_workflow", mock_wf)

        process_resp = client.post(
            "/api/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert process_resp.status_code == 200
        claim_id = process_resp.json()["claim_id"]

        stream_resp = client.get(f"/api/claims/{claim_id}/stream")
        assert stream_resp.status_code == 200
        assert stream_resp.headers.get("content-type", "").startswith("text/event-stream")
        content = stream_resp.text
        assert "data:" in content
        assert claim_id in content or "done" in content

    def test_async_then_stream_returns_done(self, client, monkeypatch, tmp_path):
        """Async process + stream: POST async, then GET stream until done."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        import claim_agent.api.routes.claims as claims_mod
        import json

        def mock_wf(claim_data, llm=None, existing_claim_id=None, *, actor_id=None):
            if existing_claim_id:
                from claim_agent.db.database import get_db_path
                from claim_agent.db.repository import ClaimRepository
                ClaimRepository(db_path=get_db_path()).update_claim_status(
                    existing_claim_id, "open"
                )
            return {
                "claim_id": existing_claim_id or "CLM-MOCK",
                "claim_type": "new",
                "status": "open",
                "summary": "Claim processed.",
            }

        monkeypatch.setattr(claims_mod, "run_claim_workflow", mock_wf)

        async_resp = client.post(
            "/api/claims/process/async",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert async_resp.status_code == 200
        claim_id = async_resp.json()["claim_id"]

        stream_resp = client.get(f"/api/claims/{claim_id}/stream")
        assert stream_resp.status_code == 200
        assert stream_resp.headers.get("content-type", "").startswith("text/event-stream")
        content = stream_resp.text
        assert "data:" in content
        assert claim_id in content
        assert '"done":true' in content or '"done": true' in content
