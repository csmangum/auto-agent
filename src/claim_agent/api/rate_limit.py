"""Rate limiting for API routes. In-memory for dev; Redis for production.

Both backends use sliding-window semantics: at most _MAX_REQUESTS in any
_WINDOW-second period. Redis uses a sorted set (ZSET) keyed by timestamp.
"""

import logging
import time
import uuid
from collections import OrderedDict
from typing import Protocol, cast

from claim_agent.config import get_settings

# (ip -> [timestamps]); OrderedDict for LRU eviction
_WINDOW = 60  # seconds
_MAX_REQUESTS = 100  # per window per IP
_MAX_BUCKETS = 10_000

_logger = logging.getLogger(__name__)
_LAST_REDIS_ERROR_LOG: float | None = None
_REDIS_ERROR_LOG_INTERVAL = 60.0


def _log_redis_rate_limit_error(exc: Exception) -> None:
    """Log Redis-related rate limit errors with simple rate limiting to avoid log spam."""
    global _LAST_REDIS_ERROR_LOG
    now = time.monotonic()
    if _LAST_REDIS_ERROR_LOG is None or (now - _LAST_REDIS_ERROR_LOG) >= _REDIS_ERROR_LOG_INTERVAL:
        _LAST_REDIS_ERROR_LOG = now
        _logger.warning(
            "RedisRateLimitBackend error, failing open (skipping rate limit check): %s",
            exc,
        )


class RateLimitBackend(Protocol):
    """Protocol for rate limit backends."""

    def is_rate_limited(self, ip: str) -> bool:
        """Return True if the IP has exceeded the rate limit."""
        ...


def _cleanup(bucket: list[float], now: float) -> list[float]:
    """Remove timestamps outside the window."""
    cutoff = now - _WINDOW
    return [t for t in bucket if t > cutoff]


class InMemoryRateLimitBackend:
    """In-memory rate limiting. Not shared across workers/instances."""

    def __init__(self) -> None:
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()

    def is_rate_limited(self, ip: str) -> bool:
        """Return True if the IP has exceeded the rate limit."""
        now = time.monotonic()
        if ip in self._buckets:
            self._buckets.move_to_end(ip)
        else:
            if len(self._buckets) >= _MAX_BUCKETS:
                self._buckets.popitem(last=False)
            self._buckets[ip] = []
        bucket = self._buckets[ip]
        bucket = _cleanup(bucket, now)
        if len(bucket) >= _MAX_REQUESTS:
            return True
        bucket.append(now)
        self._buckets[ip] = bucket
        return False

    def clear(self) -> None:
        """Clear all buckets. For testing only."""
        self._buckets.clear()


_in_memory_backend: InMemoryRateLimitBackend | None = None


def _get_in_memory_backend() -> InMemoryRateLimitBackend:
    """Return the singleton in-memory backend."""
    global _in_memory_backend
    if _in_memory_backend is None:
        _in_memory_backend = InMemoryRateLimitBackend()
    return _in_memory_backend


class RedisRateLimitBackend:
    """Redis-backed rate limiting for multi-instance deployments.

    Uses sliding-window semantics via ZSET: timestamps as scores, unique
    members per request. Aligns with in-memory backend behavior.
    """

    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError:
            raise ImportError(
                "Redis backend requires redis package. Install with: pip install -e '.[redis]'"
            ) from None
        self._url = url
        self._client = redis.from_url(url, decode_responses=True)

    def is_rate_limited(self, ip: str) -> bool:
        """Return True if the IP has exceeded the rate limit (sliding window)."""
        key = f"rate_limit:{ip}"
        try:
            now = time.time()
            cutoff = now - _WINDOW
            pipe = self._client.pipeline()
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
            pipe.expire(key, _WINDOW)
            pipe.zcard(key)
            results = pipe.execute()
            count = int(results[3])
            return count > _MAX_REQUESTS
        except Exception as exc:
            _log_redis_rate_limit_error(exc)
            return False  # Fail open on Redis errors


_backend: RateLimitBackend | None = None


def reset_rate_limit_backend() -> None:
    """Reset cached backend. For testing; next call to get_rate_limit_backend() will re-init."""
    global _backend
    _backend = None


def get_rate_limit_backend() -> RateLimitBackend:
    """Return the configured rate limit backend (Redis if REDIS_URL set, else in-memory)."""
    global _backend
    if _backend is not None:
        return _backend
    url = get_settings().paths.redis_url
    if url:
        try:
            _backend = RedisRateLimitBackend(url)
        except Exception as exc:
            _log_redis_rate_limit_error(exc)
            _backend = _get_in_memory_backend()
    else:
        _backend = _get_in_memory_backend()
    return _backend


def is_rate_limited(ip: str) -> bool:
    """Return True if the IP has exceeded the rate limit."""
    return get_rate_limit_backend().is_rate_limited(ip)


def clear_rate_limit_buckets() -> None:
    """Clear all rate limit buckets. For testing only. In-memory backend only."""
    backend = get_rate_limit_backend()
    if isinstance(backend, InMemoryRateLimitBackend):
        backend.clear()


def _get_buckets_for_testing() -> OrderedDict[str, list[float]]:
    """For testing only. Returns in-memory backend buckets. Fails if Redis backend active."""
    backend = get_rate_limit_backend()
    if isinstance(backend, InMemoryRateLimitBackend):
        return backend._buckets
    raise RuntimeError("Tests require in-memory backend (REDIS_URL must be unset)")


def get_client_ip(request, *, trust_forwarded_for: bool = False) -> str:
    """Extract client IP from the request.

    Only trusts the ``X-Forwarded-For`` header when *trust_forwarded_for*
    is ``True`` (i.e. the application is deployed behind a known reverse
    proxy).  Without that flag the header is ignored to prevent IP spoofing.
    """
    if trust_forwarded_for:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return cast(str, forwarded.split(",")[0].strip())
    return request.client.host if request.client else "unknown"
