"""Tests for rate limiting middleware."""

import pytest

from claim_agent.api.rate_limit import (
    _buckets,
    _MAX_BUCKETS,
    _MAX_REQUESTS,
    clear_rate_limit_buckets,
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
            is_rate_limited(f"192.168.0.{i % 256}.{i // 256}")
        assert len(_buckets) == _MAX_BUCKETS

    def test_evicted_ip_treated_as_new(self):
        """Evicted IP can make requests again (fresh bucket)."""
        for i in range(_MAX_BUCKETS):
            is_rate_limited(f"ip-{i}")
        # Add one more IP to trigger eviction of ip-0 (oldest)
        is_rate_limited(f"ip-{_MAX_BUCKETS}")
        assert "ip-0" not in _buckets
        # Evicted IP can make a request again (gets fresh bucket)
        assert is_rate_limited("ip-0") is False
