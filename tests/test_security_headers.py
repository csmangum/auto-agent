"""Tests for security-headers and HTTPS-redirect middleware."""

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all security-headers tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before and after each test to avoid 429 interference."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    try:
        yield
    finally:
        clear_rate_limit_buckets()


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
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self, client):
        resp = client.get("/api/v1/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/api/v1/health")
        value = resp.headers.get("permissions-policy", "")
        assert "geolocation=()" in value
        assert "microphone=()" in value
        assert "camera=()" in value
        assert "payment=()" in value

    def test_content_security_policy(self, client):
        resp = client.get("/api/v1/health")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        # unsafe-inline removed from script-src; theme script is served as a static file
        assert "script-src 'self'" in csp
        script_src_value = next((p for p in csp.split(";") if "script-src" in p), "")
        assert "unsafe-inline" not in script_src_value
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_no_hsts_without_enforce_https(self, client):
        """HSTS must NOT be set when ENFORCE_HTTPS is false (avoid breaking HTTP-only dev)."""
        resp = client.get("/api/v1/health")
        assert "strict-transport-security" not in resp.headers

    def test_headers_present_on_non_health_endpoints(self, client):
        resp = client.get("/api/v1/claims/stats")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_cache_control_no_store_on_api_except_health(self, client):
        stats = client.get("/api/v1/claims/stats")
        assert stats.headers.get("cache-control") == "no-store"
        health = client.get("/api/v1/health")
        assert "cache-control" not in health.headers


class TestHSTSWithEnforceHttps:
    """HSTS header is present when ENFORCE_HTTPS=true."""

    def test_hsts_header_present(self, https_client):
        resp = https_client.get("/api/v1/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=63072000" in hsts

    def test_hsts_includes_subdomains(self, https_client):
        resp = https_client.get("/api/v1/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "includeSubDomains" in hsts

    def test_hsts_omits_preload_by_default(self, https_client):
        resp = https_client.get("/api/v1/health")
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
            resp = tc.get("/api/v1/health")
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
            resp = tc.get("/api/v1/health")
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
            resp = tc.get("/api/v1/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=0" in hsts

    def test_unconditional_headers_still_present(self, https_client):
        resp = https_client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


class TestHttpsRedirectMiddleware:
    """HTTP→HTTPS redirect when ENFORCE_HTTPS=true, TRUST_FORWARDED_FOR=true, X-Forwarded-Proto: http."""

    def test_redirects_http_to_https(self, https_client):
        resp = https_client.get(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers.get("location", "")
        assert location.startswith("https://")

    def test_redirect_preserves_path_and_query(self, https_client):
        resp = https_client.get(
            "/api/v1/health?check=1",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers.get("location", "")
        assert "https://" in location
        assert "/api/v1/health" in location
        assert "check=1" in location

    def test_redirect_includes_security_headers(self, https_client):
        resp = https_client.get(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp

    def test_post_redirect_is_307(self, https_client):
        """307 preserves method; ensure redirect applies to POST."""
        resp = https_client.post(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert resp.headers.get("location", "").startswith("https://")

    def test_no_redirect_when_https(self, https_client):
        resp = https_client.get(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_no_redirect_without_forwarded_proto(self, https_client):
        """Requests without X-Forwarded-Proto (direct uvicorn) are never redirected."""
        resp = https_client.get("/api/v1/health", follow_redirects=False)
        assert resp.status_code == 200

    def test_no_redirect_without_trust_forwarded_for(self, monkeypatch):
        from claim_agent.config import reload_settings

        monkeypatch.setenv("ENFORCE_HTTPS", "true")
        monkeypatch.setenv("TRUST_FORWARDED_FOR", "false")
        reload_settings()
        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get(
                "/api/v1/health",
                headers={"X-Forwarded-Proto": "http", "Host": "example.com"},
                follow_redirects=False,
            )
        assert resp.status_code == 200

    def test_no_redirect_when_enforce_https_false(self, client):
        """HTTP requests are never redirected when ENFORCE_HTTPS is false."""
        resp = client.get(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "http"},
            follow_redirects=False,
        )
        assert resp.status_code == 200


class TestSecurityHeadersOnShortCircuitResponses:
    """Security headers must be present even when auth or rate-limit middleware short-circuits."""

    def test_headers_on_401_from_auth_middleware(self, monkeypatch):
        """401 from auth_middleware must still carry all security headers."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("API_KEYS", "valid-key:adjuster")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get("/api/v1/claims/stats")  # protected endpoint, no auth header
        assert resp.status_code == 401
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert resp.headers.get("cache-control") == "no-store"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp

    def test_headers_on_429_from_rate_limit_middleware(self, monkeypatch):
        """429 from rate_limit_middleware must still carry all security headers."""
        from claim_agent.api.rate_limit import clear_rate_limit_buckets, is_rate_limited
        from claim_agent.config import reload_settings

        monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        reload_settings()

        # Exhaust rate limit for a known IP: is_rate_limited() both checks AND increments
        # the counter, so calling it _MAX_REQUESTS times brings the IP to the limit.
        test_ip = "10.99.99.99"
        clear_rate_limit_buckets()
        from claim_agent.api.rate_limit import _MAX_REQUESTS

        for _ in range(_MAX_REQUESTS):
            is_rate_limited(test_ip)

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.get(
                "/api/v1/claims/stats",
                headers={"X-Forwarded-For": test_ip},
            )
        assert resp.status_code == 429
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert resp.headers.get("cache-control") == "no-store"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp


class TestRequestBodySizeLimitMiddleware:
    """Middleware rejects oversized request bodies before route handlers read them."""

    def test_json_request_within_limit_passes(self, client):
        """A small JSON payload under the 10 MB limit is accepted."""
        payload = b'{"claim_id": "test"}'
        resp = client.post(
            "/api/v1/claims/process",
            content=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        # May return 422 (validation) or other non-413 status – just not 413
        assert resp.status_code != 413

    def test_json_request_over_limit_returns_413(self, monkeypatch):
        """A Content-Length exceeding MAX_REQUEST_BODY_SIZE_MB returns 413."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("MAX_REQUEST_BODY_SIZE_MB", "1")
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            # The middleware checks the Content-Length header only (does not read the body),
            # so advertising an oversized Content-Length is sufficient to trigger the limit.
            resp = tc.post(
                "/api/v1/claims/process",
                content=b"x",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(2 * 1024 * 1024),
                },
            )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Request body too large"

    def test_multipart_request_over_limit_returns_413(self, monkeypatch):
        """A multipart Content-Length exceeding MAX_UPLOAD_BODY_SIZE_MB returns 413."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("MAX_UPLOAD_BODY_SIZE_MB", "1")
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            # The middleware checks the Content-Length header only (does not read the body).
            resp = tc.post(
                "/api/v1/claims/process",
                content=b"x",
                headers={
                    "Content-Type": "multipart/form-data; boundary=----boundary",
                    "Content-Length": str(2 * 1024 * 1024),
                },
            )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Request body too large"

    def test_multipart_content_type_case_insensitive_uses_upload_limit(self, monkeypatch):
        """Multipart detection is case-insensitive (RFC 7231 media types)."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("MAX_UPLOAD_BODY_SIZE_MB", "1")
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.post(
                "/api/v1/claims/process",
                content=b"x",
                headers={
                    "Content-Type": "Multipart/Form-Data; boundary=----boundary",
                    "Content-Length": str(2 * 1024 * 1024),
                },
            )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Request body too large"

    def test_multipart_request_within_limit_is_not_rejected_by_middleware(self, monkeypatch):
        """Multipart uploads within the upload limit are not rejected by the size middleware."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("MAX_UPLOAD_BODY_SIZE_MB", "100")
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            # The middleware only reads the Content-Length header; the actual body is tiny.
            resp = tc.post(
                "/api/v1/claims/process",
                content=b"x",
                headers={
                    "Content-Type": "multipart/form-data; boundary=----boundary",
                    "Content-Length": "1024",
                },
            )
        # Should not be rejected by the size middleware; may fail validation (422) etc.
        assert resp.status_code != 413

    def test_413_response_includes_security_headers(self, monkeypatch):
        """413 responses from the body size middleware carry all required security headers."""
        from claim_agent.config import reload_settings

        monkeypatch.setenv("MAX_REQUEST_BODY_SIZE_MB", "1")
        reload_settings()

        from claim_agent.api.server import app

        with TestClient(app, raise_server_exceptions=True) as tc:
            # The middleware checks the Content-Length header only (does not read the body).
            resp = tc.post(
                "/api/v1/claims/process",
                content=b"x",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(2 * 1024 * 1024),
                },
            )
        assert resp.status_code == 413
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("cache-control") == "no-store"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp

    def test_invalid_content_length_returns_400(self, client):
        """A non-integer Content-Length header returns 400 Bad Request."""
        resp = client.post(
            "/api/v1/claims/process",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "not-a-number"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid Content-Length header"

    def test_no_content_length_header_passes_through(self, client):
        """GET requests without Content-Length are not rejected by the size middleware."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_post_streaming_body_without_content_length_returns_411(self, client):
        """POST under /api/ with chunked/streaming body (no Content-Length) returns 411."""

        async def _streaming_post():
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:

                async def agen():
                    yield b'{"claim_id": "x"}'

                return await ac.post(
                    "/api/v1/claims/process",
                    headers={"Content-Type": "application/json"},
                    content=agen(),
                )

        resp = anyio.run(_streaming_post)
        assert resp.status_code == 411
        assert resp.json()["detail"] == "Content-Length required"

    def test_negative_content_length_returns_400(self, client):
        """Negative Content-Length is invalid HTTP and must return 400."""
        resp = client.post(
            "/api/v1/claims/process",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "-1"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid Content-Length header"


class TestCorsConfiguration:
    """CORS allow_methods / allow_headers from settings (including defaults)."""

    def test_preflight_allow_methods_includes_head(self, client):
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "HEAD",
            },
        )
        assert resp.status_code == 200
        methods = resp.headers.get("access-control-allow-methods", "")
        assert "HEAD" in methods.replace(" ", "")

    def test_preflight_allow_headers_reflects_defaults(self, client):
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-api-key",
            },
        )
        assert resp.status_code == 200
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allow_headers
        assert "x-api-key" in allow_headers

    def test_cors_methods_env_uppercased_on_preflight(self, monkeypatch, request):
        from claim_agent.api.server import create_app
        from claim_agent.config import reload_settings

        request.addfinalizer(reload_settings)
        monkeypatch.setenv("CORS_METHODS", "get, options")
        reload_settings()
        with TestClient(create_app(), raise_server_exceptions=True) as tc:
            resp = tc.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert resp.status_code == 200
        methods = resp.headers.get("access-control-allow-methods", "").replace(" ", "")
        assert "GET" in methods
        assert "OPTIONS" in methods

    def test_cors_headers_env_replaces_defaults_on_preflight(self, monkeypatch, request):
        from claim_agent.api.server import create_app
        from claim_agent.config import reload_settings

        request.addfinalizer(reload_settings)
        monkeypatch.setenv("CORS_HEADERS", "X-Custom-Alpha, X-Custom-Beta")
        reload_settings()
        with TestClient(create_app(), raise_server_exceptions=True) as tc:
            resp = tc.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "x-custom-alpha",
                },
            )
        assert resp.status_code == 200
        allow_headers = resp.headers.get("access-control-allow-headers", "")
        assert "X-Custom-Alpha" in allow_headers
        assert "X-Custom-Beta" in allow_headers
