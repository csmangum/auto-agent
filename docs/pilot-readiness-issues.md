# Pilot Readiness Issues

Comprehensive assessment of issues to address before this POC is ready for a real-world pilot. Issues are organized by severity and domain. Each issue includes location, risk, and recommended action.

> **Codebase at time of review:** ~65K lines Python (318 source files), 158 test files, 134 frontend files, 57 Alembic migrations.

## Executive Summary

The architecture is solid — good patterns for state machines, input sanitization, RBAC, audit logging, and human-in-the-loop escalation. However, the system is firmly in POC/development mode. The primary gaps are:

- **All external adapters are mocked** — the system returns synthetic data for every external integration
- **Security is opt-in** — authentication, HTTPS, and rate limiting all disabled or in-memory by default
- **No production deployment infrastructure** — SQLite default, no k8s manifests, in-process scheduler
- **Several compliance features are framework-only** — implemented but not wired to real services

---

## 🔴 CRITICAL — Must fix before any pilot

### C1. All External Adapters Default to Mock

**Location:** `.env.example`, `src/claim_agent/config/settings_model.py`

**Risk:** The system returns synthetic/fake data for every external integration: policy lookup, vehicle valuation, repair shops, parts catalog, SIU, fraud reporting, NMVTIS, gap insurance, CMS, ERP, OCR, claim search, reverse image search.

**Action:**
- Implement the `rest` adapter (or direct integration) connecting to real systems for each adapter used in the pilot scope
- At minimum for a limited pilot: `POLICY_ADAPTER=rest`, `VALUATION_ADAPTER=rest` (or `ccc`/`mitchell`/`audatex`), `REPAIR_SHOP_ADAPTER=rest`
- Verify adapter error handling with real network failures
- Create integration tests against staging instances of each external system

### C2. Authentication Disabled by Default — Anonymous Admin Access

**Location:** `src/claim_agent/api/deps.py` (lines 39–49), `src/claim_agent/api/server.py`

**Risk:** When no `API_KEYS`, `CLAIMS_API_KEY`, or `JWT_SECRET` is configured (the default), every user gets `admin` role. All endpoints are fully accessible without credentials.

**Action:**
- Require at least one auth mechanism in production mode
- Fail startup (or refuse to bind to non-localhost) when no auth is configured and `ENVIRONMENT != dev`
- Configure real API keys with proper role bindings for the pilot
- Set up `JWT_SECRET` for the claimant/repair-shop/third-party portals

### C3. No HTTPS / TLS Enforcement

**Location:** `src/claim_agent/api/server.py`, `Dockerfile`, `docker-compose.yml`

**Risk:** API serves over HTTP. Credentials, PII (policy numbers, VINs, claimant info), and LLM API keys transmitted in plaintext.

**Action:**
- Deploy behind a TLS-terminating reverse proxy (nginx, Traefik, AWS ALB)
- Add HSTS header middleware
- Redirect HTTP → HTTPS
- Configure `Secure` flag on any cookies

### C4. SQLite Not Suitable for Production

**Location:** `src/claim_agent/db/database.py`, `.env`

**Risk:** SQLite does not support concurrent writes (one writer at a time), has no replication/HA, no point-in-time recovery, no connection pooling. A multi-worker API server will hit `database is locked` errors.

**Action:**
- Switch to PostgreSQL for the pilot (`DATABASE_URL=postgresql://...`)
- Set up database backup (pg_dump cron or RDS automated backups)
- Run `alembic upgrade head` as the canonical migration path
- Test all operations under PostgreSQL (integration tests exist but should be expanded)

### C5. LLM API Key Stored as Plain String

**Location:** `src/claim_agent/config/settings_model.py` (line 635)

**Risk:** `OPENAI_API_KEY` is stored as a plain `str` field, not `SecretStr`. It could appear in logs, error tracebacks, settings dumps, or `/api/system/config` responses.

**Action:**
- Change `api_key: str` to `api_key: SecretStr` in `LLMConfig`
- Update all callers to use `.get_secret_value()`
- Audit other sensitive fields: `LANGSMITH_API_KEY`, `WEBHOOK_SECRET`, `OTP_PEPPER`
- Ensure `/api/system/config` endpoint redacts all secrets

### C6. No Claim Processing Timeout

**Location:** `src/claim_agent/workflow/orchestrator.py`

**Risk:** If an LLM call hangs or an adapter is unresponsive, the claim workflow runs indefinitely. No per-claim wall-clock timeout exists. Token/call budgets exist but don't cover hanging calls.

**Action:**
- Add a configurable wall-clock timeout for `run_claim_workflow()` (e.g., 10 minutes)
- Implement per-LLM-call timeout in `get_llm()` / CrewAI configuration
- Mark claim as `failed` with timeout reason on expiry
- Alert on timeouts via webhook

### C7. Medical Records Adapter Missing (Bodily Injury)

**Location:** `src/claim_agent/tools/bodily_injury_logic.py` (line 7)

**Risk:** Explicit `TODO: Add MedicalRecordsAdapter for production`. BI claims use mock medical records. Any pilot involving bodily injury claims will return fabricated medical data.

**Action:**
- Either exclude BI claims from pilot scope, OR
- Implement `MedicalRecordsAdapter` connecting to an HIE/provider portal
- At minimum, add a manual review gate for all BI claims

---

## 🟡 HIGH — Should fix before pilot

### H1. No Database Backup or Recovery Strategy

**Risk:** No documented or automated backup procedure. Data loss on disk failure.

**Action:** Set up automated PostgreSQL backups. Document RTO/RPO. Test restore procedure.

### H2. CORS Too Permissive

**Location:** `src/claim_agent/api/server.py` (line 128)

**Risk:** `allow_methods=["*"]`, `allow_headers=["*"]`. This allows any origin/method combination.

**Action:** Restrict to specific origins (`CORS_ORIGINS`), specific methods (`GET, POST, PUT, PATCH, DELETE`), and specific headers.

### H3. No Request Body Size Limits

**Location:** `src/claim_agent/api/server.py`

**Risk:** No limit on request body size. An attacker could upload multi-GB payloads to exhaust memory/disk.

**Action:** Configure max body size in uvicorn/nginx (e.g., 10 MB). Add explicit limits on file upload endpoints.

### H4. In-Memory Rate Limiting Not Shared Across Workers

**Location:** `src/claim_agent/api/rate_limit.py`

**Risk:** Rate limits are per-process. With multiple uvicorn workers, an attacker can multiply their request budget.

**Action:** Deploy with `REDIS_URL` configured. The Redis backend already exists.

### H5. Background Task State Lost on Restart

**Location:** `src/claim_agent/api/routes/claims.py` (`_background_tasks`)

**Risk:** In-flight async claim processing tasks are tracked in a Python set. On server restart, these tasks are lost with no retry.

**Action:**
- Record in-progress claims in the database
- Add a startup recovery scan for `processing` claims stuck > N minutes
- Consider a proper task queue (Celery, ARQ) for production

### H6. No Concurrent Claim Processing Guard

**Location:** `src/claim_agent/workflow/orchestrator.py`

**Risk:** Two requests could trigger workflow processing for the same claim simultaneously, causing race conditions in status updates and audit logging.

**Action:** Add a database-level advisory lock or `processing` status check before starting workflow. The idempotency key covers claim creation but not reprocessing.

### H7. Dual Migration Path (Alembic + Raw SQL)

**Location:** `src/claim_agent/db/database.py` (`_run_migrations()`)

**Risk:** SQLite uses inline migrations in `_run_migrations()` alongside Alembic. Schema could drift between SQLite and PostgreSQL.

**Action:**
- Use Alembic as the single source of truth for both backends
- Remove or deprecate the inline `_run_migrations()` function
- Verify schema parity (tests exist: `test_schema_sqlite_parity.py`, `test_schema_core_parity.py`)

### H8. Webhook Retry Blocks Thread Pool

**Location:** `src/claim_agent/notifications/webhook.py` (`_deliver_one()`)

**Risk:** Webhook retries use `time.sleep()` inside a 4-thread `ThreadPoolExecutor`. 4 slow webhooks → all workers blocked → notification backlog.

**Action:**
- Use async HTTP client with proper retry (e.g., `httpx.AsyncClient` with `tenacity`)
- Or increase thread pool size and add circuit breaker
- Add delivery metrics (latency, failure rate)

### H9. No Content Security Policy (CSP) Headers

**Location:** `src/claim_agent/api/server.py`, frontend

**Risk:** No CSP headers configured. XSS attacks could execute arbitrary scripts.

**Action:** Add CSP middleware with strict policy. Disable `unsafe-inline` where possible.

### H10. Email/SMS Notifications Disabled by Default

**Location:** `.env.example`, `src/claim_agent/notifications/claimant.py`

**Risk:** Claimant notifications (acknowledgments, denial letters, follow-ups) are configured but disabled. Pilot claimants won't receive required communications.

**Action:**
- Configure SendGrid (email) and/or Twilio (SMS) for the pilot
- Test delivery for all UCSPA-required notifications
- Set up bounce/failure monitoring

### H11. No Graceful Shutdown for In-Flight Claims

**Location:** `src/claim_agent/api/server.py` (lifespan)

**Risk:** On SIGTERM, background claim processing tasks are awaited but no grace period is given. Long-running LLM calls may be interrupted mid-workflow.

**Action:**
- Add signal handler with configurable grace period
- Mark interrupted claims as `failed` with recoverable flag
- Add startup recovery logic (see H5)

### H12. No Secret Management Integration

**Location:** `.env`, `src/claim_agent/config/settings_model.py`

**Risk:** All secrets (API keys, JWT secret, DB password, webhook secret) stored in `.env` file or environment variables. No rotation, no audit trail.

**Action:** Integrate with a secret manager (AWS Secrets Manager, HashiCorp Vault, etc.) for production. At minimum, document secret rotation procedures.

### H13. Scheduler Not Production-Ready

**Location:** `src/claim_agent/scheduler.py`

**Risk:** APScheduler runs in-process. With multiple API workers, jobs run N times. `.env` says "with multiple API workers/replicas, set false".

**Action:**
- For pilot: run scheduler as a separate single-instance process (`claim-agent run-scheduler`)
- Or use external cron / cloud scheduler
- Add distributed locking if needed

### H14. No API Versioning

**Location:** All API routes

**Risk:** No `/api/v1/` prefix. Breaking changes during pilot will break existing integrations.

**Action:** Add version prefix (`/api/v1/`) or API versioning strategy. Document deprecation policy.

---

## 🟠 MEDIUM — Should address for a robust pilot

### M1. Overly Broad Exception Handling

**Risk:** ~100+ `except Exception` catches across the codebase. Critical errors (OOM, assertion errors) can be silently swallowed.

**Action:** Narrow exception types. At minimum, re-raise `SystemExit`, `KeyboardInterrupt`. Add structured error logging for caught exceptions.

### M2. No Circuit Breaker for External Services

**Risk:** REST adapters retry on failure but have no circuit breaker. A down external service causes cascading slow responses.

**Action:** Add circuit breaker pattern (e.g., `pybreaker`) for adapter calls. Open circuit after N failures, close after timeout.

### M3. `FRESH_CLAIMS_DB_ON_STARTUP` Configuration Risk

**Location:** `.env.example`

**Risk:** If accidentally set to `true` in production, ALL claim data is wiped on every server restart.

**Action:** Add startup guard: refuse `FRESH_CLAIMS_DB_ON_STARTUP=true` unless `ENVIRONMENT=dev` or an explicit override flag.

### M4. No Structured Error Responses

**Risk:** Many API endpoints return unstructured error strings. No consistent error schema (error code, message, details).

**Action:** Implement a standard error response model across all endpoints. Map domain exceptions to HTTP status codes consistently.

### M5. Coverage Threshold Too Low (70%)

**Location:** `.github/workflows/ci.yml`

**Risk:** 70% coverage threshold may leave critical business logic untested for insurance domain.

**Action:** Raise to 80–85%. Add coverage requirements for critical modules (state machine, fraud detection, settlement calculation, compliance).

### M6. No Load Test SLAs Defined

**Risk:** Load tests exist but no baseline or threshold defined. No way to catch performance regressions.

**Action:** Define SLAs: p50 < Xs, p99 < Ys, error rate < Z%. Add to CI as gate.

### M7. No Monitoring/Alerting Stack

**Risk:** Prometheus metrics endpoint exists but no Grafana/alerting configured. No dashboard for claim processing latency, error rates, LLM costs.

**Action:** Set up Prometheus + Grafana (or Datadog/New Relic). Configure alerts for: error rate spike, high latency, LLM cost anomaly, DB connection failures.

### M8. No Frontend Error Tracking

**Risk:** Frontend has ErrorBoundary but no error reporting service. Production JS errors invisible.

**Action:** Add Sentry or similar error tracking to the frontend.

### M9. Missing PostgreSQL Foreign Key Enforcement Verification

**Location:** `src/claim_agent/db/database.py` (`get_connection()`)

**Risk:** `PRAGMA foreign_keys = ON` is SQLite-only. PostgreSQL enforces FKs by default in schema, but Alembic migrations should be verified.

**Action:** Verify all Alembic migrations create proper FK constraints for PostgreSQL. Add integration test.

### M10. No Session Timeout for Portals

**Risk:** Claimant, repair shop, and third-party portal tokens have expiry but no inactivity timeout. A stolen session could be used indefinitely until token expiry.

**Action:** Add short-lived access tokens with refresh. Add inactivity timeout.

### M11. UCSPA Compliance Limited to 5 States

**Location:** `src/claim_agent/compliance/state_rules.py`

**Risk:** State-specific rules only cover CA, TX, FL, NY, GA. Pilot in other states may miss regulatory deadlines.

**Action:** Verify pilot states are covered. Add state rules for any additional pilot states.

### M12. Cross-Border Transfer Mechanism Not Validated

**Location:** `src/claim_agent/privacy/cross_border.py`

**Risk:** `LLM_TRANSFER_MECHANISM=scc` is set but no actual Standard Contractual Clauses are documented. Framework is there but legal/compliance review needed.

**Action:** Confirm with legal that appropriate DPAs/SCCs are in place with LLM providers. Document in DPA registry.

### M13. No Kubernetes / Production Deployment Manifests

**Risk:** Only Dockerfile + docker-compose (SQLite). No k8s manifests, Helm charts, or Terraform for real deployment.

**Action:** Create production deployment configuration for target infrastructure (ECS, EKS, GKE, etc.).

### M14. No Disaster Recovery Plan

**Risk:** No documented DR plan. No RTO/RPO defined.

**Action:** Document DR plan including: database recovery, service failover, data export/import procedures, communication plan.

### M15. Repository.py God Object (4,693 lines)

**Location:** `src/claim_agent/db/repository.py`

**Risk:** Single file handling all claim CRUD, audit logging, search, reserve management, party management, notes, tasks, documents, etc. High coupling, hard to maintain and test.

**Action:** Split into focused repositories (already partially done with `PaymentRepository`, `IncidentRepository`, etc.). Extract remaining concerns.

### M16. docker-compose.yml Uses SQLite, No PostgreSQL Service

**Location:** `docker-compose.yml`

**Risk:** Docker deployment uses SQLite. Anyone deploying via docker-compose gets a non-production database.

**Action:** Add PostgreSQL service to docker-compose.yml. Create separate `docker-compose.prod.yml`.

---

## 🔵 LOW — Nice to have for pilot, required for production

### L1. No Accessibility (a11y) Testing

**Risk:** Frontend may not be accessible to users with disabilities. Potential ADA compliance issue.

**Action:** Run axe or Lighthouse a11y audit. Fix critical issues.

### L2. No API Documentation for Integrators

**Risk:** OpenAPI spec auto-generated but no integration guide for external systems.

**Action:** Create API integration guide with examples for common flows.

### L3. No Runbook / Incident Response Documentation

**Risk:** No documented procedures for common operational issues.

**Action:** Create runbooks for: claim stuck in processing, database recovery, adapter failure, LLM outage.

### L4. No Performance Benchmarks Documented

**Risk:** No documented baseline for claim processing time, API latency, throughput.

**Action:** Run benchmarks, document results, set baseline.

### L5. LangSmith API Key Not SecretStr

**Location:** `src/claim_agent/config/settings_model.py` (line 501)

**Risk:** `langsmith_api_key: str` — same concern as C5 but lower risk (optional observability).

**Action:** Change to `SecretStr`.

### L6. No Log Aggregation Setup

**Risk:** Structured logging exists but no centralized log collection configured.

**Action:** Set up ELK/Loki/CloudWatch for log aggregation. Configure log retention.

### L7. No Blue/Green or Canary Deployment

**Risk:** No safe rollback mechanism during deployment.

**Action:** Implement deployment strategy appropriate to infrastructure.

### L8. claims.py Route File Too Large (2,768 lines)

**Location:** `src/claim_agent/api/routes/claims.py`

**Risk:** Single route file handles claim CRUD, workflow, attachments, parties, incidents, supplemental, disputes, SIU, reprocessing, etc.

**Action:** Split into focused route modules by domain.

### L9. No Data Seeding for Pilot

**Risk:** Pilot starts with empty database. No representative historical data for duplicate detection or reporting.

**Action:** Create pilot data seeding script with realistic (but anonymized) historical claims.

### L10. No Claimant Communication Templates Review

**Risk:** Email/SMS notification templates are hardcoded strings. May not meet regulatory or brand requirements.

**Action:** Review with legal/compliance. Make templates configurable.

---

## Summary

| Severity | Count | Key Theme |
|----------|-------|-----------|
| 🔴 Critical | 7 | Mock adapters, auth, HTTPS, DB, secrets, timeouts, BI adapter |
| 🟡 High | 14 | Backup, CORS, rate limits, concurrency, migrations, shutdown, secrets, scheduler, API versioning |
| 🟠 Medium | 16 | Error handling, circuit breakers, monitoring, compliance, deployment, code quality |
| 🔵 Low | 10 | Accessibility, documentation, performance, deployment strategy |
| **Total** | **47** | |

## Recommended Pilot Gating Order

1. **Week 1:** C1 (adapters), C2 (auth), C3 (HTTPS), C4 (PostgreSQL), C5 (secrets), C6 (timeouts)
2. **Week 2:** C7 (BI scope), H1–H5 (backup, CORS, limits, tasks, concurrency)
3. **Week 3:** H6–H14 (remaining high), M1–M5 (error handling, monitoring basics)
4. **Week 4:** M6–M16 (remaining medium), L-items as capacity allows
