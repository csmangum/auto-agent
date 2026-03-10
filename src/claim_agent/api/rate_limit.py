"""Simple in-memory rate limiting middleware for API routes."""

import time
from collections import OrderedDict
from typing import cast

# (ip -> [timestamps]); OrderedDict for LRU eviction
_buckets: OrderedDict[str, list[float]] = OrderedDict()
_WINDOW = 60  # seconds
_MAX_REQUESTS = 100  # per window per IP
_MAX_BUCKETS = 10_000


def _cleanup(bucket: list[float], now: float) -> list[float]:
    """Remove timestamps outside the window."""
    cutoff = now - _WINDOW
    return [t for t in bucket if t > cutoff]


def is_rate_limited(ip: str) -> bool:
    """Return True if the IP has exceeded the rate limit."""
    now = time.monotonic()
    if ip in _buckets:
        _buckets.move_to_end(ip)
    else:
        if len(_buckets) >= _MAX_BUCKETS:
            _buckets.popitem(last=False)
        _buckets[ip] = []
    bucket = _buckets[ip]
    bucket = _cleanup(bucket, now)
    if len(bucket) >= _MAX_REQUESTS:
        return True
    bucket.append(now)
    _buckets[ip] = bucket
    return False


def clear_rate_limit_buckets() -> None:
    """Clear all rate limit buckets. For testing only."""
    _buckets.clear()


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
