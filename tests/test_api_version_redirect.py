"""Tests for the /api/* -> /api/v1/* 308 redirect middleware."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    from claim_agent.api.server import app

    return TestClient(app, follow_redirects=False)


class TestApiVersionRedirect:
    def test_get_redirect_basic(self, client):
        """GET /api/health redirects to /api/v1/health with 308."""
        resp = client.get("/api/health")
        assert resp.status_code == 308
        assert resp.headers["location"].endswith("/api/v1/health")

    def test_redirect_preserves_query_string(self, client):
        """Query parameters survive the redirect."""
        resp = client.get("/api/claims?status=open&limit=5")
        assert resp.status_code == 308
        loc = resp.headers["location"]
        assert "/api/v1/claims" in loc
        assert "status=open" in loc
        assert "limit=5" in loc

    def test_post_redirect_uses_308(self, client):
        """POST /api/claims gets 308 (method-preserving), not 301/302."""
        resp = client.post("/api/claims", json={"claim_type": "new"})
        assert resp.status_code == 308
        assert resp.headers["location"].endswith("/api/v1/claims")

    def test_bare_api_path_redirect(self, client):
        """/api (no trailing slash) redirects to /api/v1."""
        resp = client.get("/api")
        assert resp.status_code == 308
        assert resp.headers["location"].endswith("/api/v1")

    def test_versioned_path_not_redirected(self, client):
        """/api/v1/health is served directly, no redirect."""
        resp = client.get("/api/v1/health")
        assert resp.status_code in (200, 503)

    def test_redirect_includes_security_headers(self, client):
        """308 redirect responses include standard security headers."""
        resp = client.get("/api/health")
        assert resp.status_code == 308
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
