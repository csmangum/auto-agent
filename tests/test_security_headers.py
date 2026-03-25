"""Tests for security-headers and HTTPS-redirect middleware."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all security-headers tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each test to avoid 429 interference."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """TestClient with ENFORCE_HTTPS disabled (default)."""
    from claim_agent.api.server import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def https_client():
    """TestClient with ENFORCE_HTTPS=true and a minimal HSTS_MAX_AGE for assertions."""
    from claim_agent.config import reload_settings

    old_enforce = os.environ.get("ENFORCE_HTTPS")
    old_max_age = os.environ.get("HSTS_MAX_AGE")
    old_subdomains = os.environ.get("HSTS_INCLUDE_SUBDOMAINS")

    os.environ["ENFORCE_HTTPS"] = "true"
    os.environ["HSTS_MAX_AGE"] = "63072000"
    os.environ["HSTS_INCLUDE_SUBDOMAINS"] = "true"
    reload_settings()

    from claim_agent.api.server import app

    yield TestClient(app, raise_server_exceptions=True)

    # Restore original env
    if old_enforce is None:
        os.environ.pop("ENFORCE_HTTPS", None)
    else:
        os.environ["ENFORCE_HTTPS"] = old_enforce
    if old_max_age is None:
        os.environ.pop("HSTS_MAX_AGE", None)
    else:
        os.environ["HSTS_MAX_AGE"] = old_max_age
    if old_subdomains is None:
        os.environ.pop("HSTS_INCLUDE_SUBDOMAINS", None)
    else:
        os.environ["HSTS_INCLUDE_SUBDOMAINS"] = old_subdomains
    reload_settings()


class TestUnconditionalSecurityHeaders:
    """Security headers that must be present on every response regardless of HTTPS setting."""

    def test_x_content_type_options(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/api/health")
        value = resp.headers.get("permissions-policy", "")
        assert "geolocation=()" in value
        assert "microphone=()" in value
        assert "camera=()" in value
        assert "payment=()" in value

    def test_no_hsts_without_enforce_https(self, client):
        """HSTS must NOT be set when ENFORCE_HTTPS is false (avoid breaking HTTP-only dev)."""
        resp = client.get("/api/health")
        assert "strict-transport-security" not in resp.headers

    def test_headers_present_on_non_health_endpoints(self, client):
        resp = client.get("/api/claims/stats")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


class TestHSTSWithEnforceHttps:
    """HSTS header is present when ENFORCE_HTTPS=true."""

    def test_hsts_header_present(self, https_client):
        resp = https_client.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=63072000" in hsts

    def test_hsts_includes_subdomains(self, https_client):
        resp = https_client.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "includeSubDomains" in hsts

    def test_hsts_includes_preload(self, https_client):
        resp = https_client.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "preload" in hsts

    def test_unconditional_headers_still_present(self, https_client):
        resp = https_client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


class TestHttpsRedirectMiddleware:
    """HTTP→HTTPS redirect when ENFORCE_HTTPS=true and X-Forwarded-Proto: http."""

    def test_redirects_http_to_https(self, https_client):
        resp = https_client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        location = resp.headers.get("location", "")
        assert location.startswith("https://")

    def test_redirect_preserves_path_and_query(self, https_client):
        resp = https_client.get(
            "/api/health?check=1",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        location = resp.headers.get("location", "")
        assert "https://" in location
        assert "/api/health" in location
        assert "check=1" in location

    def test_no_redirect_when_https(self, https_client):
        resp = https_client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_no_redirect_without_forwarded_proto(self, https_client):
        """Requests without X-Forwarded-Proto (direct uvicorn) are never redirected."""
        resp = https_client.get("/api/health", follow_redirects=False)
        assert resp.status_code == 200

    def test_no_redirect_when_enforce_https_false(self, client):
        """HTTP requests are never redirected when ENFORCE_HTTPS is false."""
        resp = client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "http"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
