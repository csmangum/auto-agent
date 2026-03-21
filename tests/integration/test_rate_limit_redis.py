"""Redis-backed API rate limit integration tests.

Runs when REDIS_URL is set (e.g. CI with redis service). Verifies sliding-window
behavior matches in-memory semantics using RedisRateLimitBackend.
"""

import os

import pytest

from claim_agent.api.rate_limit import _MAX_REQUESTS, is_rate_limited, reset_rate_limit_backend

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_url():
    """REDIS_URL from environment. Skip tests if not set."""
    url = os.environ.get("REDIS_URL")
    if not url or not url.startswith("redis://"):
        pytest.skip("REDIS_URL (redis://...) not set")
    return url


@pytest.fixture(autouse=True)
def redis_rate_limit_env(redis_url):
    """Point settings at Redis, reset backend singleton, flush test DB."""
    import redis
    from claim_agent.config import reload_settings

    prev = os.environ.get("REDIS_URL")
    os.environ["REDIS_URL"] = redis_url
    reload_settings()
    reset_rate_limit_backend()
    client = redis.from_url(redis_url)
    client.flushdb()
    yield
    client.flushdb()
    if prev is not None:
        os.environ["REDIS_URL"] = prev
    elif "REDIS_URL" in os.environ:
        del os.environ["REDIS_URL"]
    reload_settings()
    reset_rate_limit_backend()


def test_redis_rate_limit_sliding_window(redis_rate_limit_env):
    """After _MAX_REQUESTS allowed calls, the next is rate-limited."""
    ip = "203.0.113.206"
    for _ in range(_MAX_REQUESTS):
        assert is_rate_limited(ip) is False
    assert is_rate_limited(ip) is True


def test_redis_rate_limit_isolation_per_ip(redis_rate_limit_env):
    """Distinct IPs have independent counters."""
    saturated = "203.0.113.207"
    other = "203.0.113.208"
    for _ in range(_MAX_REQUESTS):
        assert is_rate_limited(saturated) is False
    assert is_rate_limited(saturated) is True
    assert is_rate_limited(other) is False
