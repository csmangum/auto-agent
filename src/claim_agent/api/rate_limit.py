"""Simple in-memory rate limiting middleware for API routes."""

import time
from collections import defaultdict

# (ip -> [(timestamp, ...)])
_buckets: dict[str, list[float]] = defaultdict(list)
_WINDOW = 60  # seconds
_MAX_REQUESTS = 100  # per window per IP


def _cleanup(bucket: list[float], now: float) -> list[float]:
    """Remove timestamps outside the window."""
    cutoff = now - _WINDOW
    return [t for t in bucket if t > cutoff]


def is_rate_limited(ip: str) -> bool:
    """Return True if the IP has exceeded the rate limit."""
    now = time.monotonic()
    bucket = _buckets[ip]
    bucket = _cleanup(bucket, now)
    if len(bucket) >= _MAX_REQUESTS:
        return True
    bucket.append(now)
    _buckets[ip] = bucket
    return False


def get_client_ip(request) -> str:
    """Extract client IP, respecting X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
