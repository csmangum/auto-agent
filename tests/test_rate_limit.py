"""Tests for rate limiting middleware."""

from unittest.mock import MagicMock

import pytest

from claim_agent.api.rate_limit import (
    _get_buckets_for_testing,
    _MAX_BUCKETS,
    _MAX_REQUESTS,
    clear_rate_limit_buckets,
    get_client_ip,
    is_rate_limited,
)


@pytest.fixture(autouse=True)
def _clear_buckets():
    """Clear rate limit buckets before each test."""
    clear_rate_limit_buckets()
    yield
    clear_rate_limit_buckets()


class TestRateLimitBasic:
    def test_under_limit_returns_false(self):
        assert is_rate_limited("192.168.1.1") is False

    def test_over_limit_returns_true(self):
        for _ in range(_MAX_REQUESTS):
            assert is_rate_limited("10.0.0.1") is False
        assert is_rate_limited("10.0.0.1") is True

    def test_clear_resets_state(self):
        for _ in range(_MAX_REQUESTS):
            is_rate_limited("10.0.0.2")
        assert is_rate_limited("10.0.0.2") is True
        clear_rate_limit_buckets()
        assert is_rate_limited("10.0.0.2") is False


class TestRateLimitLRUEviction:
    def test_buckets_capped_at_max(self):
        """LRU eviction keeps bucket count at _MAX_BUCKETS."""
        for i in range(_MAX_BUCKETS + 1):
            is_rate_limited(f"ip-{i}")
        assert len(_get_buckets_for_testing()) == _MAX_BUCKETS

    def test_evicted_ip_treated_as_new(self):
        """Evicted IP can make requests again (fresh bucket)."""
        for i in range(_MAX_BUCKETS):
            is_rate_limited(f"ip-{i}")
        # Add one more IP to trigger eviction of ip-0 (oldest)
        is_rate_limited(f"ip-{_MAX_BUCKETS}")
        assert "ip-0" not in _get_buckets_for_testing()
        # Evicted IP can make a request again (gets fresh bucket)
        assert is_rate_limited("ip-0") is False


def _fake_request(*, client_host: str = "10.0.0.1", forwarded_for: str | None = None):
    """Build a minimal mock request for get_client_ip tests."""
    request = MagicMock()
    request.client.host = client_host
    headers = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    request.headers.get = lambda key, default=None: headers.get(key, default)
    return request


class TestGetClientIp:
    def test_uses_client_host_by_default(self):
        req = _fake_request(client_host="192.168.1.5", forwarded_for="1.2.3.4")
        assert get_client_ip(req) == "192.168.1.5"

    def test_ignores_forwarded_for_when_untrusted(self):
        req = _fake_request(client_host="10.0.0.1", forwarded_for="5.6.7.8")
        assert get_client_ip(req, trust_forwarded_for=False) == "10.0.0.1"

    def test_uses_forwarded_for_when_trusted(self):
        req = _fake_request(client_host="10.0.0.1", forwarded_for="5.6.7.8")
        assert get_client_ip(req, trust_forwarded_for=True) == "5.6.7.8"

    def test_uses_first_forwarded_ip(self):
        req = _fake_request(client_host="10.0.0.1", forwarded_for="1.1.1.1, 2.2.2.2, 3.3.3.3")
        assert get_client_ip(req, trust_forwarded_for=True) == "1.1.1.1"

    def test_falls_back_to_client_host_when_no_header(self):
        req = _fake_request(client_host="172.16.0.1")
        assert get_client_ip(req, trust_forwarded_for=True) == "172.16.0.1"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock()
        request.client = None
        request.headers.get = lambda key, default=None: None
        assert get_client_ip(request) == "unknown"
