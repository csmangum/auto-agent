"""Load tests: concurrent claim submissions with throughput and latency metrics."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

VALID_CLAIM_PAYLOAD = {
    "policy_number": "POL-001",
    "vin": "1HGBH41JXMN109186",
    "vehicle_year": 2021,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2025-01-15",
    "incident_description": "Rear-ended at stoplight",
    "damage_description": "Rear bumper damage",
    "estimated_damage": 2500.0,
}


def _submit_one(client, index: int) -> tuple[float, bool, int]:
    """Submit a single claim. Returns (latency_sec, success, status_code)."""
    payload = {**VALID_CLAIM_PAYLOAD, "policy_number": f"POL-{index:05d}"}
    start = time.perf_counter()
    try:
        resp = client.post("/api/claims", json=payload)
        elapsed = time.perf_counter() - start
        return elapsed, resp.status_code == 200, resp.status_code
    except Exception:
        elapsed = time.perf_counter() - start
        return elapsed, False, 0


@pytest.mark.load
@pytest.mark.slow
def test_concurrent_claim_submissions(load_client, mock_workflow_for_load):
    """Run concurrent POST /api/claims and report throughput, latency, error rate.

    Concurrency is configurable via LOAD_TEST_CONCURRENCY (default 10).
    """
    concurrency = int(os.environ.get("LOAD_TEST_CONCURRENCY", "10"))
    total_requests = concurrency * 2  # 2 rounds per worker

    latencies: list[float] = []
    errors = 0
    status_codes: list[int] = []

    def run_batch():
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_submit_one, load_client, i): i
                for i in range(total_requests)
            }
            for future in as_completed(futures):
                lat, ok, code = future.result()
                results.append((lat, ok, code))
        return results

    start = time.perf_counter()
    results = run_batch()
    wall_duration = time.perf_counter() - start

    for lat, ok, code in results:
        latencies.append(lat)
        status_codes.append(code)
        if not ok:
            errors += 1

    total = len(results)
    throughput = total / wall_duration if wall_duration > 0 else 0
    error_rate = errors / total if total > 0 else 0

    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0
    p99_idx = int(len(latencies_sorted) * 0.99) - 1
    p99 = latencies_sorted[p99_idx] if p99_idx >= 0 and latencies_sorted else 0

    report = {
        "concurrency": concurrency,
        "total_requests": total,
        "throughput_claims_per_sec": round(throughput, 2),
        "latency_p50_sec": round(p50, 4),
        "latency_p99_sec": round(p99, 4),
        "error_rate": round(error_rate, 4),
        "errors": errors,
    }

    print("\n" + "=" * 50)
    print("Load Test Report")
    print("=" * 50)
    print(f"  Concurrency:        {report['concurrency']}")
    print(f"  Total requests:     {report['total_requests']}")
    print(f"  Throughput:         {report['throughput_claims_per_sec']} claims/sec")
    print(f"  Latency p50:        {report['latency_p50_sec']}s")
    print(f"  Latency p99:        {report['latency_p99_sec']}s")
    print(f"  Error rate:         {report['error_rate']:.2%}")
    print(f"  Errors:             {report['errors']}")
    print("=" * 50)

    output_path = os.environ.get("LOAD_TEST_OUTPUT")
    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {output_path}")

    assert error_rate < 0.01, f"Error rate {error_rate:.2%} exceeds 1% threshold"
