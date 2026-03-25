"""Tests for security-headers and HTTPS-redirect middleware."""

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
def https_client(monkeypatch):
    """TestClient with ENFORCE_HTTPS=true, TRUST_FORWARDED_FOR=true, and custom HSTS_MAX_AGE."""
    from claim_agent.config import reload_settings

    monkeypatch.setenv("ENFORCE_HTTPS", "true")
    monkeypatch.setenv("HSTS_MAX_AGE", "63072000")
    monkeypatch.setenv("HSTS_INCLUDE_SUBDOMAINS", "true")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    reload_settings()

    from claim_agent.api.server import app

    return TestClient(app, raise_server_exceptions=True)


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

    def test_content_security_policy(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("content-security-policy") == "default-src 'self'"

    def test_no_hsts_without_enforce_https(self, client):
        """HSTS must NOT be set when ENFORCE_HTTPS is false (avoid breaking HTTP-only dev)."""
        resp = client.get("/api/health")
        assert "strict-transport-security" not in resp.headers

    def test_headers_present_on_non_health_endpoints(self, client):
        resp = client.get("/api/claims/stats")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_cache_control_no_store_on_api_except_health(self, client):
        stats = client.get("/api/claims/stats")
        assert stats.headers.get("cache-control") == "no-store"
        health = client.get("/api/health")
        assert "cache-control" not in health.headers


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

    def test_hsts_omits_preload_by_default(self, https_client):
        resp = https_client.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "preload" not in hsts

    def test_hsts_includes_preload_when_enabled(self, monkeypatch):
        from claim_agent.config import reload_settings

        monkeypatch.setenv("ENFORCE_HTTPS", "true")
        monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
        monkeypatch.setenv("HSTS_PRELOAD", "true")
        reload_settings()
        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "preload" in hsts

    def test_hsts_excludes_subdomains_when_disabled(self, monkeypatch):
        from claim_agent.config import reload_settings

        monkeypatch.setenv("ENFORCE_HTTPS", "true")
        monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
        monkeypatch.setenv("HSTS_INCLUDE_SUBDOMAINS", "false")
        reload_settings()
        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "includeSubDomains" not in hsts

    def test_hsts_max_age_zero(self, monkeypatch):
        from claim_agent.config import reload_settings

        monkeypatch.setenv("ENFORCE_HTTPS", "true")
        monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
        monkeypatch.setenv("HSTS_MAX_AGE", "0")
        reload_settings()
        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=0" in hsts

    def test_unconditional_headers_still_present(self, https_client):
        resp = https_client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


class TestHttpsRedirectMiddleware:
    """HTTP→HTTPS redirect when ENFORCE_HTTPS=true, TRUST_FORWARDED_FOR=true, X-Forwarded-Proto: http."""

    def test_redirects_http_to_https(self, https_client):
        resp = https_client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers.get("location", "")
        assert location.startswith("https://")

    def test_redirect_preserves_path_and_query(self, https_client):
        resp = https_client.get(
            "/api/health?check=1",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers.get("location", "")
        assert "https://" in location
        assert "/api/health" in location
        assert "check=1" in location

    def test_redirect_includes_security_headers(self, https_client):
        resp = https_client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("content-security-policy") == "default-src 'self'"

    def test_post_redirect_is_307(self, https_client):
        """307 preserves method; ensure redirect applies to POST."""
        resp = https_client.post(
            "/api/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert resp.headers.get("location", "").startswith("https://")

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

    def test_no_redirect_without_trust_forwarded_for(self, monkeypatch):
        from claim_agent.config import reload_settings

        monkeypatch.setenv("ENFORCE_HTTPS", "true")
        monkeypatch.setenv("TRUST_FORWARDED_FOR", "false")
        reload_settings()
        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get(
                "/api/health",
                headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
                follow_redirects=False,
            )
        assert resp.status_code == 200

    def test_no_redirect_when_enforce_https_false(self, client):
        """HTTP requests are never redirected when ENFORCE_HTTPS is false."""
        resp = client.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "http"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
