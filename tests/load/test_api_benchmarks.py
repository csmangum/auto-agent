"""API latency benchmarks: individual endpoint response-time baselines.

These tests measure single-request latency for key endpoints and assert that
measured p50/p99 values stay within documented SLA baselines.  They complement
the concurrent throughput test in test_concurrent_claims.py.

Baselines (SLA environment variable overrides)
---------------------------------------------
Health check     p50 < BENCH_HEALTH_P50_SEC   (default 1.0 s)
                 p99 < BENCH_HEALTH_P99_SEC   (default 2.0 s)
Claims list      p50 < BENCH_LIST_P50_SEC     (default 1.0 s)
                 p99 < BENCH_LIST_P99_SEC     (default 2.0 s)
Single submit    p50 < BENCH_SUBMIT_P50_SEC   (default 2.0 s)
                 p99 < BENCH_SUBMIT_P99_SEC   (default 5.0 s)

Run via:
    MOCK_DB_PATH=data/mock_db.json pytest tests/load/test_api_benchmarks.py -v -m load -s
"""

import json
import math
import os
import time

import pytest

# ---------------------------------------------------------------------------
# Per-endpoint SLA baselines (override via environment variables).
# ---------------------------------------------------------------------------
BENCH_HEALTH_P50_SEC: float = float(os.environ.get("BENCH_HEALTH_P50_SEC", "1.0"))
BENCH_HEALTH_P99_SEC: float = float(os.environ.get("BENCH_HEALTH_P99_SEC", "2.0"))

BENCH_LIST_P50_SEC: float = float(os.environ.get("BENCH_LIST_P50_SEC", "1.0"))
BENCH_LIST_P99_SEC: float = float(os.environ.get("BENCH_LIST_P99_SEC", "2.0"))

BENCH_SUBMIT_P50_SEC: float = float(os.environ.get("BENCH_SUBMIT_P50_SEC", "2.0"))
BENCH_SUBMIT_P99_SEC: float = float(os.environ.get("BENCH_SUBMIT_P99_SEC", "5.0"))

# Number of warmup + measured repetitions per benchmark.
BENCH_WARMUP: int = int(os.environ.get("BENCH_WARMUP", "2"))
BENCH_REPS: int = int(os.environ.get("BENCH_REPS", "20"))

if BENCH_WARMUP < 0:
    raise ValueError(f"BENCH_WARMUP must be non-negative, got {BENCH_WARMUP!r}")
if BENCH_REPS <= 0:
    raise ValueError(f"BENCH_REPS must be positive, got {BENCH_REPS!r}")

VALID_CLAIM_PAYLOAD = {
    "policy_number": "POL-BENCH-001",
    "vin": "1HGBH41JXMN109186",
    "vehicle_year": 2021,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2025-01-15",
    "incident_description": "Rear-ended at stoplight",
    "damage_description": "Rear bumper damage",
    "estimated_damage": 2500.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], pct: float) -> float:
    """Return the pct-th percentile from a pre-sorted list."""
    if not sorted_values:
        return 0.0
    idx = math.ceil(len(sorted_values) * pct) - 1
    return sorted_values[max(0, idx)]


def _assert_2xx(response, path: str, method: str, phase: str) -> None:
    code = getattr(response, "status_code", None)
    if code is None or not (200 <= code < 300):
        raise AssertionError(
            f"{phase.capitalize()} request to {path} via {method.upper()} failed: "
            f"status {code!r} (expected 2xx)"
        )


def _run_benchmark(client, method: str, path: str, **kwargs) -> list[float]:
    """Warmup + measure *BENCH_REPS* requests.  Returns measured latencies."""
    fn = getattr(client, method)

    # Warmup passes — not included in measurements.
    for _ in range(BENCH_WARMUP):
        response = fn(path, **kwargs)
        _assert_2xx(response, path, method, "warmup")

    latencies: list[float] = []
    for _ in range(BENCH_REPS):
        t0 = time.perf_counter()
        response = fn(path, **kwargs)
        elapsed = time.perf_counter() - t0
        _assert_2xx(response, path, method, "benchmark")
        latencies.append(elapsed)
    return latencies


def _print_report(label: str, latencies: list[float], sla_p50: float, sla_p99: float) -> None:
    sorted_lats = sorted(latencies)
    p50 = _percentile(sorted_lats, 0.50)
    p99 = _percentile(sorted_lats, 0.99)
    p_min = sorted_lats[0] if sorted_lats else 0.0
    p_max = sorted_lats[-1] if sorted_lats else 0.0
    avg = sum(sorted_lats) / len(sorted_lats) if sorted_lats else 0.0
    print(f"\n{'=' * 55}")
    print(f"Benchmark: {label}")
    print(f"{'=' * 55}")
    print(f"  Reps:   {len(latencies)}  (+ {BENCH_WARMUP} warmup)")
    print(f"  Min:    {p_min * 1000:.1f} ms")
    print(f"  Avg:    {avg * 1000:.1f} ms")
    print(f"  p50:    {p50 * 1000:.1f} ms  (SLA < {sla_p50 * 1000:.0f} ms)")
    print(f"  p99:    {p99 * 1000:.1f} ms  (SLA < {sla_p99 * 1000:.0f} ms)")
    print(f"  Max:    {p_max * 1000:.1f} ms")
    print(f"{'=' * 55}")


def _maybe_write_report(label: str, latencies: list[float], sla_p50: float, sla_p99: float) -> None:
    """Append benchmark result to LOAD_TEST_OUTPUT file when set."""
    output_path = os.environ.get("LOAD_TEST_OUTPUT")
    if not output_path:
        return
    sorted_lats = sorted(latencies)
    result = {
        "benchmark": label,
        "reps": len(latencies),
        "warmup": BENCH_WARMUP,
        "min_sec": round(sorted_lats[0], 6) if sorted_lats else 0,
        "avg_sec": round(sum(sorted_lats) / len(sorted_lats), 6) if sorted_lats else 0,
        "p50_sec": round(_percentile(sorted_lats, 0.50), 6),
        "p99_sec": round(_percentile(sorted_lats, 0.99), 6),
        "max_sec": round(sorted_lats[-1], 6) if sorted_lats else 0,
        "sla_p50_sec": sla_p50,
        "sla_p99_sec": sla_p99,
    }
    # Append as a JSON line so multiple benchmarks can be written to the same file.
    with open(output_path, "a") as fh:
        fh.write(json.dumps(result) + "\n")


# ---------------------------------------------------------------------------
# Benchmark tests
# ---------------------------------------------------------------------------

@pytest.mark.load
@pytest.mark.slow
def test_health_endpoint_latency(load_client):
    """GET /api/v1/health latency baseline.

    The health endpoint should be lightweight (no LLM, minimal DB work) and
    serve as the lower-bound API overhead reference.
    """
    latencies = _run_benchmark(load_client, "get", "/api/v1/health")
    sorted_lats = sorted(latencies)
    p50 = _percentile(sorted_lats, 0.50)
    p99 = _percentile(sorted_lats, 0.99)

    _print_report("GET /api/v1/health", latencies, BENCH_HEALTH_P50_SEC, BENCH_HEALTH_P99_SEC)
    _maybe_write_report("GET /api/v1/health", latencies, BENCH_HEALTH_P50_SEC, BENCH_HEALTH_P99_SEC)

    assert p50 < BENCH_HEALTH_P50_SEC, (
        f"Health p50 {p50:.4f}s exceeds baseline {BENCH_HEALTH_P50_SEC}s"
    )
    assert p99 < BENCH_HEALTH_P99_SEC, (
        f"Health p99 {p99:.4f}s exceeds baseline {BENCH_HEALTH_P99_SEC}s"
    )


@pytest.mark.load
@pytest.mark.slow
def test_claims_list_latency(load_client):
    """GET /api/v1/claims latency baseline.

    Measures read-path overhead including SQLite query and serialization.
    """
    latencies = _run_benchmark(load_client, "get", "/api/v1/claims")
    sorted_lats = sorted(latencies)
    p50 = _percentile(sorted_lats, 0.50)
    p99 = _percentile(sorted_lats, 0.99)

    _print_report("GET /api/v1/claims", latencies, BENCH_LIST_P50_SEC, BENCH_LIST_P99_SEC)
    _maybe_write_report("GET /api/v1/claims", latencies, BENCH_LIST_P50_SEC, BENCH_LIST_P99_SEC)

    assert p50 < BENCH_LIST_P50_SEC, (
        f"Claims list p50 {p50:.4f}s exceeds baseline {BENCH_LIST_P50_SEC}s"
    )
    assert p99 < BENCH_LIST_P99_SEC, (
        f"Claims list p99 {p99:.4f}s exceeds baseline {BENCH_LIST_P99_SEC}s"
    )


@pytest.mark.load
@pytest.mark.slow
def test_single_claim_submission_latency(load_client, mock_workflow_for_load):
    """POST /api/v1/claims latency baseline with mocked workflow.

    Measures API write-path overhead (validation, DB insert, mocked workflow
    dispatch) without LLM round-trips.  This is the baseline for claim
    ingestion throughput planning.
    """
    latencies: list[float] = []
    for _ in range(BENCH_WARMUP):
        w = load_client.post("/api/v1/claims", json=VALID_CLAIM_PAYLOAD)
        _assert_2xx(w, "/api/v1/claims", "post", "warmup")

    for i in range(BENCH_REPS):
        payload = {**VALID_CLAIM_PAYLOAD, "policy_number": f"POL-BENCH-{i:05d}"}
        t0 = time.perf_counter()
        response = load_client.post("/api/v1/claims", json=payload)
        elapsed = time.perf_counter() - t0
        _assert_2xx(response, "/api/v1/claims", "post", "benchmark")
        latencies.append(elapsed)

    sorted_lats = sorted(latencies)
    p50 = _percentile(sorted_lats, 0.50)
    p99 = _percentile(sorted_lats, 0.99)

    _print_report(
        "POST /api/v1/claims (mocked workflow)",
        latencies,
        BENCH_SUBMIT_P50_SEC,
        BENCH_SUBMIT_P99_SEC,
    )
    _maybe_write_report(
        "POST /api/v1/claims (mocked workflow)",
        latencies,
        BENCH_SUBMIT_P50_SEC,
        BENCH_SUBMIT_P99_SEC,
    )

    assert p50 < BENCH_SUBMIT_P50_SEC, (
        f"Claim submission p50 {p50:.4f}s exceeds baseline {BENCH_SUBMIT_P50_SEC}s"
    )
    assert p99 < BENCH_SUBMIT_P99_SEC, (
        f"Claim submission p99 {p99:.4f}s exceeds baseline {BENCH_SUBMIT_P99_SEC}s"
    )
