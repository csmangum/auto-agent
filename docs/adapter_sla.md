# Adapter SLA Requirements

This document defines Service Level Agreement (SLA) expectations for real adapter integrations. Use these targets when selecting vendors, designing fallbacks, and configuring timeouts/retries.

## Overview

| Adapter | Purpose | Criticality | Latency Target | Availability Target |
|---------|---------|-------------|----------------|---------------------|
| Policy (PAS) | Coverage, deductible, status lookup | Critical | p95 < 500ms | 99.9% |
| Valuation | Vehicle ACV, comparables | Critical | p95 < 2s | 99.5% |
| Repair Shop (DRP) | Shop network, labor catalog | High | p95 < 1s | 99.5% |
| Parts | Parts catalog, pricing | High | p95 < 1s | 99.5% |
| SIU | Case creation, status updates | High | p95 < 1s | 99.0% |
| Claim Search | NICB/ISO duplicate search | Medium | p95 < 3s | 99.0% |

## Policy Administration System (PAS)

**Integration pattern**: REST API, typically GET /policies/{policy_number}

- **Latency**: p95 < 500ms; p99 < 1s
- **Availability**: 99.9% (policy lookup blocks FNOL and routing)
- **Retry**: Transient 5xx, 408, 429; max 3 attempts with exponential backoff
- **Circuit breaker**: Open after 5 consecutive failures; half-open after 60s
- **Auth**: Bearer token or API key via configurable header

## Valuation (CCC / Mitchell / Audatex)

**Integration pattern**: REST or SOAP; VIN + year/make/model → ACV + comparables

- **Latency**: p95 < 2s (valuation APIs are often slower)
- **Availability**: 99.5%
- **Retry**: Same as PAS
- **Fallback**: Use mock/valuation config when external API is down (configurable)

## Repair Shop Network (DRP)

**Integration pattern**: REST; shops and labor operations catalogs

- **Latency**: p95 < 1s for get_shops, get_shop, get_labor_operations
- **Availability**: 99.5%
- **Caching**: Consider short TTL cache (e.g. 5 min) for get_shops and get_labor_operations

## Parts Pricing

**Integration pattern**: REST; parts catalog and pricing

- **Latency**: p95 < 1s
- **Availability**: 99.5%
- **Caching**: Catalog can be cached with longer TTL (e.g. 1 hour)

## SIU Case Management

**Integration pattern**: REST; create_case, get_case, add_investigation_note, update_case_status

- **Latency**: p95 < 1s for create_case (blocks fraud workflow)
- **Availability**: 99.0%
- **Idempotency**: Prefer idempotent create when supported

## Claim Search (NICB / ISO)

**Integration pattern**: REST or batch; VIN, claimant name, date range → matches

- **Latency**: p95 < 3s (external search can be slow)
- **Availability**: 99.0%
- **Degradation**: Claim processing can proceed without claim search; treat as non-blocking

## Implementation Patterns

All real adapters should:

1. **Use `AdapterHttpClient`** (or equivalent) for auth, retry, and circuit breaker
2. **Implement `health_check() -> tuple[bool, str]`** for `/api/v1/health` inclusion
3. **Return `None` or empty** on circuit open rather than raising (where semantically valid)
4. **Log failures** at WARNING level for circuit open, ERROR for unexpected errors

## Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `POLICY_REST_BASE_URL` | PAS API base URL | `https://pas.example.com/api/v1` |
| `POLICY_REST_AUTH_HEADER` | Auth header name | `Authorization` |
| `POLICY_REST_AUTH_VALUE` | Bearer token or API key | `Bearer sk-...` |
| `POLICY_REST_PATH_TEMPLATE` | Path with `{policy_number}` | `/policies/{policy_number}` |
| `POLICY_REST_RESPONSE_KEY` | JSON key for policy (optional) | `data` |
| `POLICY_REST_TIMEOUT` | Request timeout seconds | `15` |

## Health Endpoint

`GET /api/v1/health` runs adapter probes when the backend supports them:

- For **most adapters**, a probe runs when `*_ADAPTER=rest` (and the adapter is REST-capable).
- For **valuation**, a probe also runs when `VALUATION_ADAPTER` is one of the provider backends: `ccc`, `mitchell`, or `audatex` (in addition to `rest` when supported).

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "llm": "skipped",
    "adapter_policy": "ok",
    "adapter_valuation": "skipped"
  }
}
```

- `ok`: Adapter health probe succeeded
- `degraded:msg`: Probe failed (e.g. timeout, 5xx)
- `skipped`: Adapter uses a backend that does not run a probe (e.g. `mock`), or valuation is not `rest` / `ccc` / `mitchell` / `audatex`
- `error:msg`: Exception during check
