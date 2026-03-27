# Performance Benchmarks

This document defines baseline performance targets for the Agentic Claim Representative system, describes the benchmark methodology, and explains how to run the tests and interpret results.

## Overview

Three dimensions are measured:

| Dimension | What is measured | Relevant test |
|-----------|-----------------|---------------|
| **API latency** | Single-request response time per endpoint | `tests/load/test_api_benchmarks.py` |
| **Claim processing time** | End-to-end wall time to process one claim (mocked workflow) | `tests/load/test_api_benchmarks.py` |
| **Throughput** | Claims submitted per second under concurrent load | `tests/load/test_concurrent_claims.py` |

All load tests require a running FastAPI app instance (served by FastAPI `TestClient` in-process) with the workflow engine mocked out so that LLM round-trips do not inflate API latency numbers.

---

## Baseline SLA Targets

The values below are the default gate thresholds built into the load test suite.  They represent conservative, achievable targets for a single-node SQLite deployment running on a developer laptop or a small CI runner.  Production targets on a PostgreSQL-backed deployment with dedicated compute will be tighter.

### Per-endpoint latency (single request, no LLM)

| Endpoint | p50 target | p99 target | Notes |
|----------|-----------|-----------|-------|
| `GET /api/v1/health` | < 1 000 ms | < 2 000 ms | Framework + DB ping only |
| `GET /api/v1/claims` | < 1 000 ms | < 2 000 ms | List query + serialization |
| `POST /api/v1/claims` | < 2 000 ms | < 5 000 ms | Validation + DB write + mocked workflow dispatch |

### Throughput (concurrent load, 10 workers, mocked workflow)

| Metric | Target |
|--------|--------|
| Throughput | ≥ 1 claim/sec sustained |
| p50 latency | < 2 000 ms |
| p99 latency | < 5 000 ms |
| Error rate | ≤ 1 % |

### Adapter SLA targets

External adapter latencies are tracked separately.  See [Adapter SLA](adapter_sla.md) for per-integration targets (Policy/PAS, Valuation, Repair Shop, Parts, SIU, Claim Search).

---

## How to Run the Benchmarks

### Prerequisites

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # OPENAI_API_KEY is NOT required for load tests
export MOCK_DB_PATH=data/mock_db.json
```

### Single-endpoint latency benchmarks

```bash
MOCK_DB_PATH=data/mock_db.json \
  .venv/bin/pytest tests/load/test_api_benchmarks.py -v -m load -s
```

To capture machine-readable results:

```bash
MOCK_DB_PATH=data/mock_db.json \
LOAD_TEST_OUTPUT=/tmp/benchmark_results.jsonl \
  .venv/bin/pytest tests/load/test_api_benchmarks.py -v -m load -s
```

Each test appends a JSON line to `LOAD_TEST_OUTPUT`.  Fields include `benchmark`, `reps`, `warmup`, `min_sec`, `avg_sec`, `p50_sec`, `p99_sec`, `max_sec`, `sla_p50_sec`, `sla_p99_sec`.

### Concurrent throughput test

```bash
MOCK_DB_PATH=data/mock_db.json \
LOAD_TEST_CONCURRENCY=10 \
  .venv/bin/pytest tests/load/test_concurrent_claims.py -v -m load -s
```

### Running all load tests together

```bash
MOCK_DB_PATH=data/mock_db.json \
LOAD_TEST_CONCURRENCY=10 \
LOAD_TEST_OUTPUT=/tmp/load_results.jsonl \
  .venv/bin/pytest tests/load/ -v -m load -s
```

---

## Tuning Thresholds

All SLA gates are controlled by environment variables so they can be tightened per environment without code changes:

### Single-endpoint benchmarks (`test_api_benchmarks.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCH_HEALTH_P50_SEC` | `1.0` | Health endpoint p50 gate (seconds) |
| `BENCH_HEALTH_P99_SEC` | `2.0` | Health endpoint p99 gate (seconds) |
| `BENCH_LIST_P50_SEC` | `1.0` | Claims list p50 gate (seconds) |
| `BENCH_LIST_P99_SEC` | `2.0` | Claims list p99 gate (seconds) |
| `BENCH_SUBMIT_P50_SEC` | `2.0` | Claim submission p50 gate (seconds) |
| `BENCH_SUBMIT_P99_SEC` | `5.0` | Claim submission p99 gate (seconds) |
| `BENCH_WARMUP` | `2` | Warmup requests excluded from measurements |
| `BENCH_REPS` | `20` | Measured repetitions per benchmark |

### Concurrent throughput test (`test_concurrent_claims.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOAD_TEST_CONCURRENCY` | `10` | Worker thread count |
| `LOAD_TEST_SLA_P50_SEC` | `2.0` | p50 latency gate |
| `LOAD_TEST_SLA_P99_SEC` | `5.0` | p99 latency gate |
| `LOAD_TEST_SLA_ERROR_RATE` | `0.01` | Maximum acceptable error rate (fraction) |
| `LOAD_TEST_OUTPUT` | _(unset)_ | Path to write JSON report |

---

## Benchmark Methodology

### What is mocked

The load tests mock `run_claim_workflow()` to return immediately with a synthetic result.  This isolates **API framework overhead** (request parsing, middleware, authentication, DB read/write, response serialization) from **LLM latency**, which varies by model, network, and provider load.

To measure actual end-to-end claim processing time including LLM calls, use the evaluation scripts instead:

```bash
python scripts/evaluate_claim_processing.py --quick
```

### Measurement approach

1. **Warmup phase** — a configurable number of requests (default 2) are issued before recording begins. This ensures Python module caches and SQLite page caches are warm.
2. **Measurement phase** — `BENCH_REPS` sequential requests are timed with `time.perf_counter()` (wall-clock, sub-microsecond resolution).
3. **Percentile calculation** — p50 and p99 are computed from the sorted latency array.
4. **SLA assertion** — the test fails if any percentile exceeds the configured gate.

### Interpreting results

| Observation | Likely cause |
|-------------|-------------|
| p99 >> p50 | Occasional GIL contention, SQLite lock wait, or OS scheduler jitter |
| All latencies high | SQLite write-ahead log flush, model/corpus loading at import time |
| Health p50 ≈ Claims list p50 | DB query is not the bottleneck; look at middleware/serialization |
| Submission p50 >> List p50 | Expected: write path is heavier than read path |

---

## CI Integration

Load tests run in the `load` CI job (see `.github/workflows/`).  The job uses reduced concurrency (`LOAD_TEST_CONCURRENCY=2`) to fit in the free-tier runner time budget, and the results are not uploaded as artifacts by default.  To capture results in CI, set `LOAD_TEST_OUTPUT` to a path and upload it with the `actions/upload-artifact` step.

Example CI step:

```yaml
- name: Run load tests
  env:
    MOCK_DB_PATH: data/mock_db.json
    LOAD_TEST_CONCURRENCY: 2
    LOAD_TEST_OUTPUT: /tmp/load_results.jsonl
  run: .venv/bin/pytest tests/load/ -v -m load -s

- name: Upload benchmark results
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: load-test-results
    path: /tmp/load_results.jsonl
```

---

## Updating Baselines

When you deploy hardware or infrastructure changes that meaningfully improve performance, update the default gate values in the test files and this document together:

1. Run benchmarks on the new infrastructure and record p50/p99 values.
2. Set the new baseline to **measured p99 × 1.5** (50 % headroom) to allow for measurement noise.
3. Update the environment variable defaults at the top of `tests/load/test_api_benchmarks.py` and `tests/load/test_concurrent_claims.py`.
4. Update the [Baseline SLA Targets](#baseline-sla-targets) table in this document.
5. Commit both the test and doc changes together so the baseline is always self-documenting.

---

## Related Documentation

- [Adapter SLA](adapter_sla.md) — latency and availability targets for external integrations
- [Observability](observability.md) — Prometheus metrics, per-claim latency histograms, LLM cost tracking
- [Alerting](alerting.md) — production alert rules based on `claim_processing_duration_seconds`
- [Eval Suite Gaps](eval-suite-gaps.md) — evaluation coverage status
