"""Prometheus metrics for outbound REST adapter HTTP calls.

Labels are low-cardinality: fixed adapter names and HTTP method / status class only.
Never put URLs, tokens, or claim IDs in labels.
"""

from __future__ import annotations

import threading

from prometheus_client import Counter, Histogram, REGISTRY

_adapter_http_requests_total: Counter | None = None
_adapter_http_request_duration_seconds: Histogram | None = None
_metrics_lock = threading.Lock()


def _ensure_adapter_http_metrics() -> None:
    global _adapter_http_requests_total, _adapter_http_request_duration_seconds
    if _adapter_http_requests_total is not None:
        return
    with _metrics_lock:
        if _adapter_http_requests_total is not None:
            return
        _adapter_http_requests_total = Counter(
            "adapter_http_requests_total",
            "Completed outbound HTTP calls from AdapterHttpClient (one sample per logical request, after retries)",
            ["adapter", "method", "status_class"],
        )
        _adapter_http_request_duration_seconds = Histogram(
            "adapter_http_request_duration_seconds",
            "Wall time per logical outbound adapter HTTP request (includes retries)",
            ["adapter", "method", "status_class"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )


def record_adapter_http_request(
    *,
    adapter_name: str,
    method: str,
    duration_seconds: float,
    status_class: str,
) -> None:
    """Record one logical adapter HTTP outcome for Prometheus."""
    _ensure_adapter_http_metrics()
    if _adapter_http_requests_total is None or _adapter_http_request_duration_seconds is None:
        return
    name = (adapter_name or "unknown").strip() or "unknown"
    m = method.upper() if method else "GET"
    sc = (status_class or "error").strip() or "error"
    if duration_seconds < 0:
        duration_seconds = 0.0
    _adapter_http_requests_total.labels(adapter=name, method=m, status_class=sc).inc()
    _adapter_http_request_duration_seconds.labels(adapter=name, method=m, status_class=sc).observe(
        duration_seconds
    )


def unregister_adapter_http_metrics_for_tests() -> None:
    """Remove adapter HTTP metrics from the global registry (unit tests only)."""
    global _adapter_http_requests_total, _adapter_http_request_duration_seconds
    with _metrics_lock:
        for metric in (_adapter_http_requests_total, _adapter_http_request_duration_seconds):
            if metric is not None:
                try:
                    REGISTRY.unregister(metric)
                except KeyError:
                    pass
        _adapter_http_requests_total = None
        _adapter_http_request_duration_seconds = None
