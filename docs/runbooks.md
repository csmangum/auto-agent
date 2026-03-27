# Runbooks — Incident Response Procedures

This document provides step-by-step operational runbooks for the four most common incident types in the Agentic Claim Representative system. Each runbook includes symptoms, diagnosis commands, resolution steps, and escalation criteria.

> **Related documents:** [Alerting](alerting.md) · [Disaster Recovery](disaster-recovery.md) · [Observability](observability.md) · [Adapters](adapters.md) · [Configuration](configuration.md)

---

## Table of Contents

1. [Claim Stuck in Processing](#1-claim-stuck-in-processing)
2. [Database Recovery](#2-database-recovery)
3. [Adapter Failure](#3-adapter-failure)
4. [LLM Outage](#4-llm-outage)

---

## 1. Claim Stuck in Processing

### Symptoms

- `claims_in_progress` Prometheus gauge is elevated and not decreasing.
- `ClaimAgentHighLatency` alert fires (P99 > 120 s).
- A claim's `status` remains `processing` for longer than the expected duration (typically 60–300 s depending on claim type and LLM latency).
- No progress events appear in the structured log for a given `claim_id`.

### Diagnosis

**1. Identify stuck claims via the API:**

```bash
# List claims currently in 'processing' status
curl -H "X-API-Key: $API_KEY" \
  "https://<your-domain>/api/v1/claims?status=processing" | jq '.claims[] | {id, created_at, claim_type}'
```

**2. Check the audit trail for a specific claim:**

```bash
claim-agent history <claim_id>
# or via API
curl -H "X-API-Key: $API_KEY" \
  "https://<your-domain>/api/v1/claims/<claim_id>/history" | jq .
```

Look for the last recorded event timestamp; a gap of more than 5 minutes without a new event indicates the claim is stuck.

**3. Inspect structured logs for the claim:**

```bash
# JSON log format — filter by claim_id
kubectl -n claim-agent logs -l app=claim-agent --since=1h \
  | grep '"claim_id": "<claim_id>"' | tail -40

# Or in human log format
kubectl -n claim-agent logs -l app=claim-agent --since=1h \
  | grep "\[claim=<claim_id>" | tail -40
```

**4. Check the `claims_in_progress` gauge in Grafana or Prometheus:**

```promql
claims_in_progress
```

A non-zero value that persists across multiple scrape intervals confirms active stuck claims.

**5. Check for LLM or adapter errors in the logs:**

```bash
kubectl -n claim-agent logs -l app=claim-agent --since=1h \
  | grep -E '"level": "ERROR"|"level": "WARNING"' | tail -50
```

### Resolution

#### Option A — Reprocess the claim (preferred)

If the claim reached a known stage before getting stuck, resume from that stage:

```bash
# Resume from the last known good stage (e.g. 'router', 'workflow', 'escalation_check')
claim-agent reprocess <claim_id> --from-stage <stage>

# Full reprocess from the beginning
claim-agent reprocess <claim_id>
```

Valid `--from-stage` values: `coverage_verification`, `economic_analysis`, `fraud_prescreening`, `duplicate_detection`, `router`, `escalation_check`, `workflow`, `task_creation`, `rental`, `liability_determination`, `settlement`, `subrogation`, `salvage`, `after_action`.

#### Option B — Escalate to SIU

If reprocessing fails or fraud / investigation is warranted, route the claim to Special Investigations (SIU):

```bash
# Via CLI (uses workflow actor id; ensure CLI context can access the claim DB)
claim-agent escalate-siu <claim_id>

# Or via API (adjuster-or-higher API key or JWT; no request body)
curl -X POST -H "X-API-Key: $API_KEY" \
  "https://<your-domain>/api/v1/claims/<claim_id>/review/escalate-to-siu"
```

For claims already in `needs_review`, use the review queue (`GET /api/v1/claims/review-queue`) and approve / reject / request-info endpoints instead ([Adjuster workflow](adjuster-workflow.md)).

#### Option C — Restart application pods

If multiple claims are stuck simultaneously (systemic issue), restart all pods:

```bash
kubectl -n claim-agent rollout restart deployment/claim-agent
kubectl -n claim-agent rollout status deployment/claim-agent
```

After the restart, re-queue any stuck claims with `claim-agent reprocess`.

### Escalation criteria

| Condition | Action |
|-----------|--------|
| Single claim stuck > 10 min | Reprocess (Option A) |
| Reprocess fails twice | Escalate to SIU (Option B) or use review queue if status is `needs_review` |
| > 3 claims stuck simultaneously | Restart pods (Option C); page engineering lead |
| All new claims stuck | Treat as LLM or database outage; follow runbooks §3 / §4 |

---

## 2. Database Recovery

> For comprehensive PITR, backup, and multi-region failover procedures, see [Disaster Recovery](disaster-recovery.md#3-database-recovery). This runbook covers quick operational responses.

### Symptoms

- `ClaimAgentDBConnectionFailure` alert fires.
- `/health` endpoint returns 503 with `"database": "error"`.
- All API requests return 5xx errors.
- Structured logs contain `OperationalError`, `connection refused`, or `FATAL: remaining connection slots are reserved` messages.

### Diagnosis

**1. Verify the health endpoint:**

```bash
curl -s https://<your-domain>/health | jq .checks.database
```

**2. Check pod logs for database errors:**

```bash
kubectl -n claim-agent logs -l app=claim-agent --since=5m \
  | grep -E "OperationalError|connection refused|FATAL|database" | tail -30
```

**3. Verify the database host is reachable from within the cluster:**

```bash
kubectl -n claim-agent run db-check --rm -it --image=postgres:15 --restart=Never -- \
  psql "$DATABASE_URL" -c "SELECT 1;"
```

**4. Check connection pool exhaustion:**

```bash
# On the PostgreSQL server
psql -h "$PGHOST" -U "$PGUSER" -c \
  "SELECT count(*), state FROM pg_stat_activity WHERE datname='claims' GROUP BY state;"
```

### Resolution

#### Scenario A — Transient network blip or connection pool exhaustion

```bash
# Restart pods to reset connection pools
kubectl -n claim-agent rollout restart deployment/claim-agent
kubectl -n claim-agent rollout status deployment/claim-agent

# Verify recovery
curl https://<your-domain>/health
```

#### Scenario B — Database primary is down (managed PostgreSQL, Multi-AZ)

For managed databases (RDS Multi-AZ, Cloud SQL HA, Azure Flexible Server):

1. Check the cloud console for automatic failover status (typically completes in 1–2 min).
2. Once the DNS endpoint resolves to the new primary, restart pods to reconnect:
   ```bash
   kubectl -n claim-agent rollout restart deployment/claim-agent
   ```
3. Confirm health:
   ```bash
   curl https://<your-domain>/health
   ```

#### Scenario C — Self-managed PostgreSQL primary down

See [Disaster Recovery §3.2](disaster-recovery.md#32-self-managed-postgresql) for full WAL-based restore steps.

Quick manual failover to a warm standby:

```bash
# On the standby server
pg_ctl promote -D /var/lib/postgresql/data

# Update DATABASE_URL secret in Kubernetes
kubectl -n claim-agent patch secret claim-agent-secret \
  -p '{"stringData": {"DATABASE_URL": "postgresql://<standby-host>:5432/claims"}}'

# Restart pods
kubectl -n claim-agent rollout restart deployment/claim-agent
```

#### Scenario D — Alembic migration mismatch after restore

```bash
# Check current migration state
DATABASE_URL="postgresql://..." uv run alembic current

# Apply any pending migrations
DATABASE_URL="postgresql://..." uv run alembic upgrade head
```

#### Scenario E — Connection pool exhaustion (too many connections)

```bash
# Identify long-running idle connections on the server
psql -h "$PGHOST" -U "$PGUSER" -c \
  "SELECT pid, state, query_start, query \
   FROM pg_stat_activity \
   WHERE datname='claims' AND state != 'active' \
   ORDER BY query_start;"

# Terminate idle connections older than 10 min
psql -h "$PGHOST" -U "$PGUSER" -c \
  "SELECT pg_terminate_backend(pid) \
   FROM pg_stat_activity \
   WHERE datname='claims' AND state='idle' \
     AND query_start < NOW() - INTERVAL '10 minutes';"
```

After clearing idle connections, restart pods:

```bash
kubectl -n claim-agent rollout restart deployment/claim-agent
```

### Post-recovery verification

```bash
# 1. Health endpoint returns 200
curl -s https://<your-domain>/health | jq .status

# 2. Submit a test claim (use mock if available)
MOCK_CREW_ENABLED=true claim-agent process tests/sample_claims/new_claim.json

# 3. Confirm Prometheus alert ClaimAgentDBConnectionFailure has cleared
```

### Escalation criteria

| Condition | Action |
|-----------|--------|
| Health endpoint recovers within 5 min of pod restart | No escalation needed; monitor |
| Managed DB failover takes > 10 min | Contact cloud provider support |
| Self-managed primary unrecoverable | Execute PITR restore ([DR §3.2](disaster-recovery.md#32-self-managed-postgresql)); page DBA and engineering lead |
| Data loss suspected | Page engineering lead + DBA + Legal/Compliance immediately |

---

## 3. Adapter Failure

### Symptoms

- Health endpoint returns `"adapter_<name>": "error"` or `"adapter_<name>": "degraded"`.
- Claims for a specific type (e.g. `partial_loss`, `total_loss`) are failing or producing incomplete results.
- Logs contain `AdapterError`, `circuit open`, `HTTP 5xx`, or connection timeout messages for a specific adapter.
- `ClaimAgentHighErrorRate` alert fires for claims that rely on the affected adapter.

### Adapters and their dependencies

| Adapter | Env var | Purpose | Claim types affected |
|---------|---------|---------|----------------------|
| `PolicyAdapter` | `POLICY_ADAPTER` | Coverage and deductible lookup | All |
| `ValuationAdapter` | `VALUATION_ADAPTER` | Vehicle market value | `total_loss`, `partial_loss` |
| `RepairShopAdapter` | `REPAIR_SHOP_ADAPTER` | Shop network and labor catalog | `partial_loss` |
| `PartsAdapter` | `PARTS_ADAPTER` | Parts catalog | `partial_loss` |
| `SIUAdapter` | `SIU_ADAPTER` | Fraud case creation | `fraud` |
| `NMVTISAdapter` | `NMVTIS_ADAPTER` | Federal total-loss reporting | `total_loss` |
| `GapInsuranceAdapter` | `GAP_INSURANCE_ADAPTER` | Gap carrier coordination | `total_loss` |
| `MedicalRecordsAdapter` | `MEDICAL_RECORDS_ADAPTER` | Medical records fetch | `bodily_injury` |

### Diagnosis

**1. Check health endpoint adapter probes:**

```bash
curl -s https://<your-domain>/health | jq .checks
```

**2. Check circuit breaker state in logs:**

```bash
kubectl -n claim-agent logs -l app=claim-agent --since=15m \
  | grep -E "circuit|AdapterError|adapter" -i | tail -40
```

**3. Test the external endpoint directly:**

```bash
# Example: check if the policy REST API is reachable
curl -v "$POLICY_REST_BASE_URL/health"

# Check valuation service
curl -v "$VALUATION_REST_BASE_URL/health"
```

**4. Check circuit breaker configuration:**

Each REST adapter supports a circuit breaker controlled by environment variables:

```bash
# Default: opens after 5 consecutive failures, recovers after 60 s
<PREFIX>_CIRCUIT_FAILURE_THRESHOLD=5   # e.g. POLICY_CIRCUIT_FAILURE_THRESHOLD
<PREFIX>_CIRCUIT_RECOVERY_TIMEOUT=60   # e.g. POLICY_CIRCUIT_RECOVERY_TIMEOUT
```

A `circuit open` log entry means the adapter has exceeded its failure threshold and is rejecting calls until the recovery timeout expires.

### Resolution

#### Option A — Wait for circuit breaker recovery

If the external service has recovered (check its status page or health endpoint), the circuit breaker will reset automatically after `<PREFIX>_CIRCUIT_RECOVERY_TIMEOUT` seconds (default 60 s). No action required beyond monitoring.

```bash
# Monitor logs for circuit breaker closing
kubectl -n claim-agent logs -l app=claim-agent -f \
  | grep -E "circuit|adapter" -i
```

#### Option B — Fall back to stub adapter

Switch the affected adapter to its `stub` or `mock` implementation to unblock claim processing while the upstream service is restored. **Use only in a controlled maintenance window — stub adapters return synthetic data.**

```bash
# Example: fall back policy adapter to stub
kubectl -n claim-agent set env deployment/claim-agent POLICY_ADAPTER=stub

# Or for mock (rich fake data — test/demo only)
kubectl -n claim-agent set env deployment/claim-agent POLICY_ADAPTER=mock

kubectl -n claim-agent rollout status deployment/claim-agent
```

**Restore the real adapter once the upstream service recovers:**

```bash
kubectl -n claim-agent set env deployment/claim-agent POLICY_ADAPTER=rest
kubectl -n claim-agent rollout status deployment/claim-agent
```

#### Option C — Increase circuit breaker thresholds (temporary)

If the upstream service is experiencing elevated latency (not complete failure), increase the failure threshold to tolerate transient errors:

```bash
kubectl -n claim-agent set env deployment/claim-agent \
  POLICY_CIRCUIT_FAILURE_THRESHOLD=20 \
  POLICY_CIRCUIT_RECOVERY_TIMEOUT=120
kubectl -n claim-agent rollout restart deployment/claim-agent
```

**Reset to defaults once the upstream service is stable:**

```bash
kubectl -n claim-agent set env deployment/claim-agent \
  POLICY_CIRCUIT_FAILURE_THRESHOLD=5 \
  POLICY_CIRCUIT_RECOVERY_TIMEOUT=60
kubectl -n claim-agent rollout restart deployment/claim-agent
```

#### Option D — Reprocess affected claims

After the adapter is restored, reprocess any claims that failed during the outage:

```bash
# Identify failed claims within a time window via API
curl -H "X-API-Key: $API_KEY" \
  "https://<your-domain>/api/v1/claims?status=failed" | jq '.claims[] | .id' \
  | xargs -I{} claim-agent reprocess {}
```

### Post-recovery verification

```bash
# 1. Health endpoint shows adapter healthy
curl -s https://<your-domain>/health | jq '.checks | to_entries | map(select(.key | startswith("adapter_")))'

# 2. Process a claim that exercises the recovered adapter
MOCK_CREW_ENABLED=false claim-agent process tests/sample_claims/partial_loss_parking.json

# 3. Confirm ClaimAgentHighErrorRate alert has cleared
```

### Escalation criteria

| Condition | Action |
|-----------|--------|
| Single adapter down < 15 min | Fall back to stub (Option B); notify adapter owner |
| Single adapter down > 15 min | Page engineering lead; contact upstream vendor |
| Multiple adapters down simultaneously | Treat as systemic outage; page engineering lead; consider maintenance mode |
| Claims with bad data written due to stub fallback | Manual data review required; notify claims operations team |

---

## 4. LLM Outage

### Symptoms

- Claims fail with errors containing `openai`, `litellm`, `rate limit`, `502`, `503`, or `LLMCallFailed`.
- `ClaimAgentHighErrorRate` alert fires.
- `llm_tokens_total` metric stops incrementing while `claims_failed_total` rises.
- `/health` shows `"llm": "degraded"` (when `HEALTH_CHECK_LLM=true`).
- LangSmith traces show errors or no new traces appear.

### Diagnosis

**1. Check health endpoint LLM status:**

```bash
# Requires HEALTH_CHECK_LLM=true
curl -s https://<your-domain>/health | jq .checks.llm
```

**2. Check pod logs for LLM errors:**

```bash
kubectl -n claim-agent logs -l app=claim-agent --since=15m \
  | grep -E "openai|litellm|rate.limit|LLMCall|RateLimitError|APIError" -i | tail -40
```

**3. Verify the LLM provider status page:**

| Provider | Status page |
|----------|------------|
| OpenAI | https://status.openai.com |
| OpenRouter | https://status.openrouter.ai |

**4. Check rate limit and quota metrics:**

```promql
# LLM cost anomaly — approaching quota
rate(llm_tokens_total[5m])

# LLM cost alert
ClaimAgentLLMCostAnomaly
```

**5. Verify API key is valid and not expired:**

```bash
# Test the OpenAI endpoint directly (replace with the configured base URL if using OpenRouter)
curl -s https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq '.error // "OK"'
```

### Resolution

#### Option A — Wait for provider recovery

If the outage is confirmed on the provider's status page, claim processing will resume automatically once service is restored. In the meantime:

1. Halt new submissions if possible (coordinate with claims operations).
2. Monitor the provider status page.
3. Monitor `ClaimAgentHighErrorRate` alert for clearing.

No code or configuration change is needed; the retry logic in the workflow will automatically retry transient LLM failures.

#### Option B — Switch LLM model or provider

If you have an alternative provider or model configured (e.g. OpenRouter as a fallback):

```bash
# Switch to OpenRouter (OPENROUTER_API_KEY must be set)
kubectl -n claim-agent set env deployment/claim-agent \
  LLM_PROVIDER=openrouter \
  MODEL_NAME=openai/gpt-4o-mini  # or another OpenRouter-supported model

kubectl -n claim-agent rollout restart deployment/claim-agent
kubectl -n claim-agent rollout status deployment/claim-agent
```

If switching to a lower-capability model (e.g. `gpt-4o-mini` → `gpt-3.5-turbo`), expect lower accuracy. Review escalation rates after switching.

**Restore the primary model once the provider recovers:**

```bash
kubectl -n claim-agent set env deployment/claim-agent \
  LLM_PROVIDER=openai \
  MODEL_NAME=gpt-4o-mini
kubectl -n claim-agent rollout restart deployment/claim-agent
```

#### Option C — Enable mock crew for non-LLM processing

If you need to keep some workflows running without LLM (e.g. status checks, human review actions), the mock crew can be used for test/demo scenarios. **Do not use in production for real claims.**

```bash
kubectl -n claim-agent set env deployment/claim-agent MOCK_CREW_ENABLED=true
kubectl -n claim-agent rollout restart deployment/claim-agent
```

**Restore after the outage:**

```bash
kubectl -n claim-agent set env deployment/claim-agent MOCK_CREW_ENABLED=false
kubectl -n claim-agent rollout restart deployment/claim-agent
```

#### Option D — Rate limit mitigation

If the outage is caused by hitting rate limits (not a provider outage):

1. **Check current spend** in the provider dashboard (OpenAI Platform or OpenRouter).
2. **Review the `ClaimAgentLLMCostAnomaly` alert** — this fires when spend exceeds $10 in 1 hour.
3. **Reduce concurrency** by scaling down replicas:
   ```bash
   kubectl -n claim-agent scale deployment/claim-agent --replicas=1
   ```
4. **Request a quota increase** from the provider if the current limit is insufficient for production load.
5. **Restore replicas** after rate limits clear:
   ```bash
   kubectl -n claim-agent scale deployment/claim-agent --replicas=3
   ```

#### Option E — Reprocess failed claims after recovery

```bash
# Reprocess all claims that failed during the LLM outage
curl -H "X-API-Key: $API_KEY" \
  "https://<your-domain>/api/v1/claims?status=failed" | jq -r '.[].id' \
  | xargs -I{} claim-agent reprocess {}
```

### Post-recovery verification

```bash
# 1. Health endpoint LLM check passes
curl -s https://<your-domain>/health | jq .checks.llm

# 2. Process a test claim end-to-end
claim-agent process tests/sample_claims/new_claim.json

# 3. Confirm llm_tokens_total is incrementing again
# (check in Grafana or Prometheus)

# 4. Confirm ClaimAgentHighErrorRate alert has cleared
```

### Escalation criteria

| Condition | Action |
|-----------|--------|
| Provider outage confirmed on status page, ETA < 30 min | Wait (Option A); notify claims operations to pause new submissions |
| Provider outage > 30 min | Switch provider/model (Option B); page engineering lead |
| Rate limit — transient | Reduce replicas (Option D); request quota increase |
| Rate limit — persistent | Page engineering lead; review cost anomalies; consider model downgrade |
| API key expired or revoked | Rotate key immediately via the provider dashboard and update Kubernetes secret |

---

## Common Across All Runbooks

### Health check

```bash
curl -s https://<your-domain>/health | jq .
```

A healthy system returns `"status": "ok"` with `200`. A degraded system returns `"status": "degraded"` or `"status": "error"` with `503`.

### Key Prometheus queries

```promql
# Claims currently being processed
claims_in_progress

# Error rate over the last 5 min
rate(claims_failed_total[5m]) / (rate(claims_processed_total[5m]) + rate(claims_failed_total[5m]))

# P99 processing latency
histogram_quantile(0.99, rate(claim_processing_duration_seconds_bucket[5m]))

# LLM token usage rate
rate(llm_tokens_total[5m])
```

### Emergency contacts

Populate before going to production — see [Disaster Recovery §6.5](disaster-recovery.md#65-external-contacts) for the full contacts table.

### Post-incident

After resolving any incident:

1. Confirm all Prometheus alerts have cleared.
2. Reprocess any claims that failed during the incident.
3. Capture a timeline and root cause in the incident log.
4. Schedule a post-incident review within 24 hours.

See [Disaster Recovery §6.4](disaster-recovery.md#64-incident-response-checklist) for the full incident response checklist.
