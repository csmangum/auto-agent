# Configuration

This document describes all configuration options for the Agentic Claim Representative system.

For database configuration, see [Database](database.md). For getting started, see [Getting Started](getting-started.md).

## Environment Variables

All configuration is done through environment variables. Copy `.env.example` to `.env` and customize. **[.env.example](../.env.example)** is the canonical list of variables and defaults; the sections below document the most important groups and behavior.

```bash
cp .env.example .env
```

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key for LLM provider (OpenRouter/OpenAI) | `sk-or-v1-...` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_BASE` | (none) | Custom API base URL (for OpenRouter) |
| `OPENAI_MODEL_NAME` | `gpt-4o-mini` | Model to use for agents |
| `CLAIMS_DB_PATH` | `data/claims.db` | Path to SQLite database (ignored when `DATABASE_URL` is set) |
| `DATABASE_URL` | (unset) | PostgreSQL URL for production; see [Database](database.md) |
| `DB_POOL_SIZE` | `5` | PostgreSQL pool size (see [Database](database.md)) |
| `DB_MAX_OVERFLOW` | `10` | PostgreSQL pool overflow (see [Database](database.md)) |
| `MOCK_DB_PATH` | `data/mock_db.json` | Path to mock policy/vehicle data |
| `READ_REPLICA_DATABASE_URL` | (unset) | PostgreSQL read-replica URL; when set with `DATABASE_URL`, read-heavy queries use the replica (writes stay on the primary). |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | When using PostgreSQL, run `alembic upgrade head` on API startup. Set `false` if migrations are a separate deploy step. |
| `FRESH_CLAIMS_DB_ON_STARTUP` | `false` | **Dev only:** if `true`, deletes and recreates the claims database on every server start. |
| `ALEMBIC_SCRIPT_LOCATION` | (unset) | Path to the `alembic` revision directory. Required for SQLite when the app is not run from the repo root and the package is not installed editable; see [Database](database.md). |
| `HEALTH_CHECK_NOTIFICATIONS` | `false` | When `true`, `/api/health` includes claimant notification readiness and returns **503** if no email/SMS channel is ready. See [Observability](observability.md#health-endpoint). |
| `CA_COMPLIANCE_PATH` | `data/california_auto_compliance.json` | Path to CA compliance data |
| `CREWAI_VERBOSE` | `true` | CrewAI verbose mode (`true`/`false`) |
| `CLAIM_AGENT_MAX_TOKENS_PER_CLAIM` | `150000` | Max tokens per claim before stopping |
| `CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM` | `50` | Max LLM API calls per claim |
| `CLAIM_WORKFLOW_TIMEOUT_SECONDS` | `600` | Workflow wall-clock limit (seconds). Enforced **between** stages only; pair with `LLM_CALL_TIMEOUT_SECONDS` for per-call caps. |
| `LLM_CALL_TIMEOUT_SECONDS` | `120` | Per-LLM-call timeout passed to the LLM client (seconds). |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | Time-to-live (seconds) for API idempotency keys (default 24h). Expired rows are purged periodically while the API server runs. |
| `REDIS_URL` | (unset) | Redis URL for **shared API rate limiting** across multiple app instances or workers (e.g. `redis://localhost:6379/0`). Requires `pip install -e '.[redis]'`. When unset, rate limits use an in-process store (not shared). |
| `SCHEDULER_ENABLED` | `false` | Enable optional in-process scheduler for recurring operational jobs |
| `SCHEDULER_TIMEZONE` | `UTC` | Timezone for scheduler cron expressions |
| `SCHEDULER_UCSPA_DEADLINE_CHECK_CRON` | `0 9 * * *` | Daily UCSPA deadline alert sweep schedule (cron) |
| `SCHEDULER_DIARY_ESCALATE_CRON` | `0 * * * *` | Diary overdue/escalation sweep schedule (cron) |
| `SCHEDULER_UCSPA_DAYS_AHEAD` | `3` | Lookahead window (days) for UCSPA approaching-deadline alerts |

### Authentication and RBAC

When `API_KEYS`, `CLAIMS_API_KEY`, or `JWT_SECRET` is set, all `/api/*` endpoints (except `/api/health`, `/api/auth/login`, and `/api/auth/refresh`) require authentication.

| Variable | Description |
|---------|-------------|
| `CLAIM_AGENT_ENVIRONMENT` | Default `development`. If set to anything other than `dev`/`development`/`test`/`testing` and no API keys or `JWT_SECRET` are configured, the API **refuses to start** (prevents anonymous admin access in production). Legacy alias: `ENVIRONMENT`. |
| `API_KEYS` | Comma-separated entries. Each entry is `key:role` or `key:role:user_id`. The optional third segment sets API identity (`sub`) for RBAC and adjuster-scoped claims (`claims.assignee` must match `user_id`). Example: `sk-adj:adjuster:uuid-of-adjuster` |
| `CLAIMS_API_KEY` | Single API key (backward compat). When set and `API_KEYS` unset, treated as admin role |
| `JWT_SECRET` | Secret for signing/verifying access JWTs from `POST /api/auth/login` and `Authorization: Bearer`. Access token payload: `sub`, `role`, `token_use`=`access`. Refresh tokens issued by login are opaque DB-backed strings, not JWTs. |
| `JWT_ACCESS_TTL_SECONDS` | Access JWT lifetime in seconds (default 900). |
| `JWT_REFRESH_TTL_SECONDS` | Opaque refresh token lifetime in seconds (default 604800). |
| `TRUST_FORWARDED_FOR` | Default `false`. If `true`, trust `X-Forwarded-For` for client IP (rate limiting) and `X-Forwarded-Proto` for HTTP→HTTPS redirects when `ENFORCE_HTTPS=true`. Enable only behind a trusted reverse proxy. |
| `ENFORCE_HTTPS` | Default `false`. If `true`, send HSTS and redirect clients when `X-Forwarded-Proto` is `http` (only when `TRUST_FORWARDED_FOR=true`). |
| `HSTS_MAX_AGE` | HSTS `max-age` in seconds (default one year). |
| `HSTS_INCLUDE_SUBDOMAINS` | Default `true`; append `includeSubDomains` to HSTS. |
| `HSTS_PRELOAD` | Default `false`; append `preload` to HSTS only when you intend to join the browser preload list. |
| `CORS_ORIGINS` | Comma-separated browser origins allowed by CORS (production; default allows local dev). |
| `CORS_METHODS` | Comma-separated HTTP methods for CORS (default `GET,HEAD,POST,PUT,PATCH,DELETE`). |
| `CORS_HEADERS` | Comma-separated request headers for CORS. If set, **replaces** the built-in default list (not merged). See `.env.example` for the default header names. |

**Roles**: `adjuster` (submit/view claims, docs; when using JWT or `key:role:user_id`, list/get/stats/review-queue are scoped to assigned claims), `supervisor` (all adjuster + reprocess, metrics, assign claims), `executive` (supervisor-level API access; reserve cap is `RESERVE_EXECUTIVE_LIMIT`, default 0 = no cap), `admin` (all + config, system, `/api/users`; may set `skip_authority_check` on reserve updates).

Pass credentials via `X-API-Key` header or `Authorization: Bearer <key>`.

**Email/password login**: `POST /api/auth/login` with JSON `email` and `password` returns `access_token` and `refresh_token`. `POST /api/auth/refresh` with `refresh_token` rotates credentials. Requires `JWT_SECRET` and users in the `users` table (manage via `POST /api/users` as admin).

### Content Security Policy (dashboard)

The API attaches a `Content-Security-Policy` to responses (see `claim_agent.api.server`). **Browser CSP applies to the document that loaded the page**, so JSON API responses alone do not define policy for the SPA. For local development, **`frontend/vite.config.ts` sends the same CSP** on the Vite dev and preview servers; keep that string in sync with the server module when you change either. For production, set an equivalent header (or meta policy) where the built `index.html` is served—typically the static host or reverse proxy in front of the dashboard.

### API idempotency (`Idempotency-Key`)

Mutating claim endpoints support an optional **`Idempotency-Key`** request header so safe retries (e.g. after a timeout) do not create duplicate resources or run duplicate work.

| Behavior | Details |
|----------|---------|
| **Header** | `Idempotency-Key`: 1–256 characters; only `a-z`, `A-Z`, `0-9`, `_`, `-`. Invalid values → **400**. |
| **Scoped key** | The server combines the header with HTTP method, request path, and a fingerprint of auth (`Authorization` if present) and client host so the same key is not shared across users or routes. |
| **Success cache** | Only **HTTP 200** responses are stored and replayed. **4xx/5xx** are not cached; the in-progress row is released so the client can retry. |
| **In flight** | If a second request uses the same key while the first is still processing → **409** with `Retry-After: 5`. |
| **TTL** | Controlled by `IDEMPOTENCY_TTL_SECONDS`. After expiry, a new request with the same key is treated as a new operation. |

**Endpoints that honor `Idempotency-Key`:** `POST /api/claims`, `POST /api/claims/process`, `POST /api/claims/process/async`, `POST /api/incidents`, `POST /api/claim-links`, `POST /api/claims/{claim_id}/portal-token`, and `POST /api/claims/generate` when the body requests submission (`submit: true`).

### API rate limiting

The HTTP API applies a **per-client-IP sliding window** (100 requests per 60 seconds by default; see [`src/claim_agent/api/rate_limit.py`](../src/claim_agent/api/rate_limit.py) for constants). With **`REDIS_URL`** set and the **`redis`** optional dependency installed, counters live in Redis so limits are **consistent across replicas**. If Redis is unavailable at runtime, checks **fail open** (request allowed) after a warning. Client IP uses `X-Forwarded-For` only when **`TRUST_FORWARDED_FOR=true`** (see table above).

### Scheduler vs. external cron

You can run recurring compliance/operations jobs either with the built-in in-process scheduler **or** external cron.

- **Built-in scheduler (optional):** set `SCHEDULER_ENABLED=true` and run the API (`claim-agent serve`) or foreground scheduler (`claim-agent run-scheduler`).
  - `SCHEDULER_UCSPA_DEADLINE_CHECK_CRON` controls automatic `ucspa-deadlines` behavior (with webhook dispatch).
  - `SCHEDULER_DIARY_ESCALATE_CRON` controls automatic `diary-escalate` behavior.
  - `SCHEDULER_ERP_POLL_CRON` controls inbound ERP event polling when ERP integration is enabled (default every 15 minutes in `.env.example`).
- **External cron (fallback / preferred in some deployments):** leave `SCHEDULER_ENABLED=false` and schedule CLI commands externally.

**Multi-worker and multi-replica deployments:** The scheduler is **in-process**. Each API process (each Uvicorn/Gunicorn **worker**, or each replica pod) that starts with `SCHEDULER_ENABLED=true` runs its **own** copy of the same cron jobs. That duplicates diary escalations, UCSPA sweeps, and webhook volume. Recommended patterns:

- Run the HTTP API with **`SCHEDULER_ENABLED=false`** and use **external cron** or a **single dedicated** `claim-agent run-scheduler` process (with `SCHEDULER_ENABLED=true`) for scheduled work; or
- Use **a single API worker** only if you enable the scheduler on the API process.

Example external cron:

```cron
# Daily UCSPA approaching-deadline alerts at 09:00
0 9 * * * /path/to/claim-agent ucspa-deadlines --days 3

# Hourly diary escalation sweep
0 * * * * /path/to/claim-agent diary-escalate
```

### Adapter Backends

Each external-system adapter can be configured independently. See [Adapters](adapters.md) for full documentation.

| Variable | Default | Values | Description |
|----------|---------|--------|-------------|
| `POLICY_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Policy database backend |
| `VALUATION_ADAPTER` | `mock` | `mock`, `stub`, `rest`, `ccc`, `mitchell`, `audatex` | Vehicle valuation backend (see `.env.example` for `VALUATION_REST_*`) |
| `REPAIR_SHOP_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Repair shop network backend |
| `PARTS_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Parts catalog backend |
| `SIU_ADAPTER` | `mock` | `mock`, `stub`, `rest` | SIU case management backend |
| `STATE_BUREAU_ADAPTER` | `mock` | `mock`, `stub`, `rest` | State DOI fraud bureau filing |
| `FRAUD_REPORTING_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Aggregated fraud filing (state bureau / NICB / NISS paths when `rest`) |
| `CLAIM_SEARCH_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Cross-carrier ClaimSearch-style backend |
| `NMVTIS_ADAPTER` | `mock` | `mock`, `stub`, `rest` | NMVTIS total-loss / salvage reporting |
| `GAP_INSURANCE_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Gap (loan/lease) carrier after total loss |
| `CMS_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Medicare Section 111 / CMS reporting |
| `ERP_ADAPTER` | `mock` | `mock`, `rest` | Shop management / ERP integration (bidirectional repair sync) |
| `REVERSE_IMAGE_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Reverse-image / stock-photo fraud signals |
| `MEDICAL_RECORDS_ADAPTER` | `mock` | `mock`, `stub`, `rest` | Medical records / HIE (bodily injury); `mock` returns fabricated PHI — not for production BI |
| `SIU_DEFAULT_STATE` | `California` | Any state name | Fallback state for SIU fraud bureau reporting when claim/policy state is missing |
| `VISION_ADAPTER` | `real` | `real`, `mock` | Vision analysis: `real` (litellm) or `mock` (claim-context derived) |
| `OCR_ADAPTER` | `mock` | `mock`, `stub`, `rest` | OCR for document extraction (estimates, photos) |

REST backends use `*_REST_*` environment variables (URLs, auth headers, timeouts). **Authoritative list:** [.env.example](../.env.example) and [Adapters](adapters.md).

### Mock Crew (Testing)

The Mock Crew simulates external interactions for E2E testing without real people or services. See [Mock Crew Design](mock-crew-design.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_CREW_ENABLED` | `false` | Enable Mock Crew (claimant, vision, etc.) |
| `MOCK_CREW_SEED` | (none) | Optional seed for reproducible mock outputs |
| `MOCK_IMAGE_GENERATOR_ENABLED` | `false` | Generate damage images via OpenRouter |
| `MOCK_IMAGE_MODEL` | `google/gemini-2.0-flash-exp` | OpenRouter model for image generation |
| `MOCK_IMAGE_VISION_ANALYSIS_SOURCE` | `claim_context` | Vision analysis: `claim_context` (mock) or `openrouter` (real API) |

Additional Mock Crew toggles (`MOCK_DOCUMENT_GENERATOR_*`, `MOCK_CLAIMANT_*`, `MOCK_NOTIFIER_*`, `MOCK_REPAIR_SHOP_*`, `MOCK_THIRD_PARTY_*`, webhook/ERP capture flags) are listed in [.env.example](../.env.example).

### Portals and chat

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAIMANT_PORTAL_ENABLED` | `true` | Enable claimant self-service routes (`/api/portal/*`). |
| `CLAIMANT_VERIFICATION_MODE` | `policy_vin` | Claimant verification: `token`, `policy_vin`, or `email`. |
| `CLAIM_ACCESS_TOKEN_EXPIRY_DAYS` | `90` | Magic-link / access token lifetime when using token mode. |
| `REPAIR_SHOP_PORTAL_ENABLED` | `false` | Repair shop portal (`/api/repair-portal`). |
| `REPAIR_SHOP_PORTAL_TOKEN_EXPIRY_DAYS` | `90` | Repair shop per-claim token lifetime. |
| `THIRD_PARTY_PORTAL_ENABLED` | `false` | Third-party / lienholder portal (`/api/third-party-portal`). |
| `THIRD_PARTY_PORTAL_TOKEN_EXPIRY_DAYS` | `90` | Third-party portal token lifetime. |
| `CHAT_MAX_TOOL_ROUNDS` | `5` | Max tool-call rounds per chat agent turn. |
| `CHAT_MAX_MESSAGE_HISTORY` | `50` | Max messages retained per turn for the chat agent. |
| `CHAT_SYSTEM_PROMPT_OVERRIDE` | (empty) | Optional override for the chat system prompt. |

### Async workflow processing

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAIM_AGENT_MAX_CONCURRENT_BACKGROUND_TASKS` | `10` | Cap concurrent background workflow tasks; `POST` with `?async=true` returns **503** when saturated (`0` = unlimited). |
| `CLAIM_AGENT_TASK_RECOVERY_ENABLED` | `true` | On startup, recover claims stuck in `processing`. |
| `CLAIM_AGENT_TASK_RECOVERY_STUCK_MINUTES` | `30` | Minimum minutes in `processing` before recovery treats a claim as stuck. |

### Request body and upload limits

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_REQUEST_BODY_SIZE_MB` | `10` | Max JSON/non-upload body size. |
| `MAX_UPLOAD_BODY_SIZE_MB` | `100` | Max `multipart/form-data` body size. |
| `MAX_UPLOAD_FILE_SIZE_MB` | `50` | Max size per uploaded file (claims API and portals). |

### Diary system

| Variable | Default | Description |
|----------|---------|-------------|
| `DIARY_AUTO_CREATE_ON_STATUS_CHANGE` | `true` | Auto-create diary entries on key status transitions. |
| `DIARY_ESCALATION_HOURS_BEFORE_SUPERVISOR` | `24` | Hours after an overdue diary notification before escalating to supervisor. |

### Database backups (operational)

Backups use `scripts/backup_postgres.py` (PostgreSQL only). Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_ENABLED` | `false` | Convention flag that backups are expected (does not run `pg_dump` by itself). |
| `BACKUP_DIR` | `data/backups` | Local directory for dump files. |
| `BACKUP_RETENTION_DAYS` | `14` | Local retention before rotation. |
| `BACKUP_S3_BUCKET` | (unset) | Optional S3 upload target. |

See [.env.example](../.env.example) for `BACKUP_COMPRESS`, `BACKUP_S3_*`, paths/timeouts for `pg_dump` / `pg_restore` / `psql`.

### Observability

Logging, tracing, and metrics are configurable via: `CLAIM_AGENT_LOG_FORMAT`, `CLAIM_AGENT_LOG_LEVEL`, `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `CLAIM_AGENT_TRACE_LLM`, `CLAIM_AGENT_TRACE_TOOLS`, `CLAIM_AGENT_LOG_PROMPTS`, `CLAIM_AGENT_LOG_RESPONSES`. See [Observability](observability.md) for full details.

### PII and Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAIM_AGENT_MASK_PII` | `true` | Mask policy_number and vin in logs. Set `false` for dev. |
| `RETENTION_PERIOD_YEARS` | 5 (from compliance) | Override retention period. Run `claim-agent retention-enforce` to archive. |
| `RETENTION_PURGE_AFTER_ARCHIVE_YEARS` | `2` | Years after `archived_at` before `claim-agent retention-purge` may anonymize. |
| `STATE_RETENTION_PATH` | `data/state_retention_periods.json` | Path to state-specific retention periods (per-state years). |
| `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE` | (unset) | Calendar years after claim `purged_at` before audit rows are eligible for `audit-log-export` / `audit-log-purge` tooling. |
| `AUDIT_LOG_PURGE_ENABLED` | `false` | Must be `true` for `claim-agent audit-log-purge` to delete `claim_audit_log` rows. |
| `RETENTION_EXPORT_ENABLED` | `false` | Enable S3/Glacier export pipeline for `claim-agent retention-export` and `--export-before-purge`. |
| `RETENTION_EXPORT_S3_BUCKET` | (unset) | Required when export is enabled. Other `RETENTION_EXPORT_*` variables (prefix, endpoint, storage class, encryption) are in [.env.example](../.env.example). |

See [PII and Retention](pii-and-retention.md) for full documentation.

### Privacy, DSAR, and cross-border transfers

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_DATA_MINIMIZATION` | `true` | When true, minimize claim fields sent in LLM prompts (allowlists / masking). |
| `DSAR_VERIFICATION_REQUIRED` | `true` | DSAR access/deletion: require `claim_id` or `policy_number`+`vin` for verification. |
| `LITIGATION_HOLD_BLOCKS_DELETION` | `true` | When true, DSAR deletion skips claims on litigation hold. |
| `DATA_REGION` | `us` | Deployment data region: `us`, `eu`, or `other` (source jurisdiction when `loss_state` absent). |
| `CROSS_BORDER_POLICY` | `audit` | Cross-border handling: `allow`, `audit`, or `restrict` when transfer mechanisms are missing. |
| `LLM_TRANSFER_MECHANISM` | `scc` | Legal basis for LLM API transfers (e.g. `scc`, `adequacy_decision`, `explicit_consent`, `bcr`, `legitimate_interests`, `none`). |

OTP self-service verification (`OTP_ENABLED`, `OTP_PEPPER`, `OTP_*` limits) and audit redaction (`AUDIT_LOG_STATE_REDACTION_ENABLED`, `DSAR_AUDIT_LOG_POLICY`) are documented in [.env.example](../.env.example).

### Reserve management

Carrier case reserves (estimated ultimate cost) are stored on `claims.reserve_amount` with an append-only `reserve_history` table. Adjusters set reserves via `PATCH /api/claims/{claim_id}/reserve` (subject to limits); supervisors/admins use higher ceilings; executives use `RESERVE_EXECUTIVE_LIMIT` when set to a positive value (0 = no cap). Admin-only `skip_authority_check` on that endpoint is recorded in `reserve_history` and `claim_audit_log` with `[authority check bypassed]`. `GET /api/claims/{claim_id}/reserve/adequacy` compares the current reserve to the greater of positive `estimated_damage` and positive `payout_amount` (zeros are ignored) and returns `warnings` plus stable `warning_codes` (`RESERVE_NOT_SET`, `RESERVE_BELOW_ESTIMATE`, `RESERVE_BELOW_PAYOUT`, `RESERVE_BELOW_BENCHMARK`). Transitions to `closed` or `settled` can enforce the same benchmark via `RESERVE_CLOSE_SETTLE_ADEQUACY_GATE` ([State machine](state-machine.md#reserve-adequacy-gate-closed--settled)). The append-only `reserve_history` table also supports aggregate reporting over reserve movements. See [Database](database.md#reserve_history).

| Variable | Default | Description |
|----------|---------|-------------|
| `RESERVE_ADJUSTER_LIMIT` | `10000` | Maximum reserve amount an adjuster may set |
| `RESERVE_SUPERVISOR_LIMIT` | `50000` | Maximum reserve for `supervisor` / `admin` roles |
| `RESERVE_EXECUTIVE_LIMIT` | `0` | Maximum reserve for `executive`; `0` or negative means no cap |
| `RESERVE_INITIAL_RESERVE_FROM_ESTIMATED_DAMAGE` | `true` | When true, FNOL creates an initial reserve from `estimated_damage` when present |
| `RESERVE_CLOSE_SETTLE_ADEQUACY_GATE` | `warn` | `off` \| `block` \| `warn` — adequacy gate on move to `closed` / `settled` |

### Disbursements / payment authority

Individual payments are stored in `claim_payments` (see [Database](database.md#claim_payments)). Adjusters create and transition rows via `POST /api/claims/{claim_id}/payments` and related issue/clear/void endpoints, subject to per-role ceilings. Settlement agents may call the `record_claim_payment` tool (workflow actor, authority bypass for automation). When `PAYMENT_AUTO_RECORD_FROM_SETTLEMENT` is true, a successful main workflow with a positive `extracted_payout` also inserts one authorized row keyed by `workflow_settlement:{workflow_run_id}` (idempotent per run).

**Avoid double-counting:** Do not enable `PAYMENT_AUTO_RECORD_FROM_SETTLEMENT` while settlement agents are also calling `record_claim_payment` for the same total settlement amount (you would get one aggregate auto row plus one or more tool rows). Choose one approach: either rely on the tool for itemized payees, or turn on auto-record for a single summary row per workflow run and keep agents from recording that same payout again.

| Variable | Default | Description |
|----------|---------|-------------|
| `PAYMENT_ADJUSTER_LIMIT` | `5000` | Max disbursement amount an adjuster may authorize in one row |
| `PAYMENT_SUPERVISOR_LIMIT` | `25000` | Ceiling for `supervisor` role |
| `PAYMENT_EXECUTIVE_LIMIT` | `100000` | Ceiling for `executive` / `admin` |
| `PAYMENT_AUTO_RECORD_FROM_SETTLEMENT` | `false` | When true, auto-create one `claim_payments` row from settlement payout at workflow end (see note above on tool overlap) |

Escalation, fraud detection, valuation, and partial-loss thresholds are also configurable via environment variables. See [Centralized Settings](#centralized-settings) and `.env.example` for the full list.

## LLM Configuration

### Using OpenRouter

[OpenRouter](https://openrouter.ai/) provides access to multiple LLMs through a single API.

```bash
# .env
OPENAI_API_KEY=sk-or-v1-your-key-here
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet
```

Available models on OpenRouter:
- `anthropic/claude-3-opus`
- `anthropic/claude-3-sonnet`
- `openai/gpt-4-turbo`
- `openai/gpt-4o-mini`
- `meta-llama/llama-3-70b-instruct`

### Using OpenAI Directly

```bash
# .env
OPENAI_API_KEY=sk-your-openai-key
# Leave OPENAI_API_BASE empty for default OpenAI endpoint
OPENAI_MODEL_NAME=gpt-4o-mini
```

### Using Other OpenAI-Compatible APIs

Any OpenAI-compatible API can be used:

```bash
# .env
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://your-provider.com/v1
OPENAI_MODEL_NAME=your-model-name
```

### Prompt Caching

The system supports two complementary prompt-caching mechanisms controlled by `LLMConfig` fields (via environment variables). Both are **disabled by default** and should be evaluated against your latency, cost, and privacy requirements before enabling.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CACHE_ENABLED` | `false` | Enable LiteLLM in-process prompt cache. Serves repeated identical prompts from memory without a provider round-trip. |
| `LLM_CACHE_SEED` | (unset) | Optional integer seed for deterministic LiteLLM cache keys. Leave blank for provider-assigned keys. |
| `LLM_ANTHROPIC_PROMPT_CACHE` | `false` | Send the Anthropic prompt-caching beta header (`anthropic-beta: prompt-caching-2024-07-31`). Effective only with Anthropic models (direct or via OpenRouter). |

#### LiteLLM in-process cache (`LLM_CACHE_ENABLED`)

LiteLLM's cache stores LLM responses in memory so identical prompts bypass a provider round-trip entirely. Enable when:

- The same system prompt is reused across many agent calls in a single worker process (e.g. bulk claim processing batches).
- Large identical RAG snippets are prepended to multiple consecutive LLM calls.

**Caveats:**

- The cache is **per-process** and is not shared across workers or replicas. In multi-worker or multi-replica deployments the cache provides no cross-instance benefit.
- Cached responses can become **stale** if model weights, temperature, or tool definitions change between calls. Restart the process to clear the in-process cache.
- **Do not enable** when prompts contain claimant-specific PII (e.g. names, policy numbers, VINs injected per-claim); caching those calls risks serving a previous claimant's data in a later response.

```bash
# .env – enable LiteLLM in-process cache with a fixed seed
LLM_CACHE_ENABLED=true
LLM_CACHE_SEED=42
```

#### Anthropic server-side prompt caching (`LLM_ANTHROPIC_PROMPT_CACHE`)

When enabled, `get_llm()` adds the `anthropic-beta: prompt-caching-2024-07-31` request header. Anthropic caches the longest matching prompt *prefix* server-side for approximately five minutes and bills cached input tokens at a significantly reduced rate (≈ 10 % of normal input-token cost).

Enable when:

- You use an Anthropic model directly (`OPENAI_API_KEY` pointing to Anthropic) or via **OpenRouter** with an `anthropic/*` model.
- Your system prompt or prepended RAG context exceeds **1 024 tokens** and is identical across several consecutive calls.

**Caveats:**

- Has **no effect** with non-Anthropic models (OpenAI, Llama, etc.) — the header is silently ignored or may cause a `400` error on some providers.
- Cache TTL is ~5 minutes on the Anthropic side; the cache is automatically invalidated when the prefix changes.
- **Do not include claimant-specific PII** in the portions of the prompt you intend to be cached (e.g., the system prompt or prepended policy text). Rotate or vary the prompt for per-claimant content.
- Cached token counts still appear in the response `usage` field; monitor billing dashboards to confirm cache hits.

```bash
# .env – enable Anthropic prompt-caching beta
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet
LLM_ANTHROPIC_PROMPT_CACHE=true
```

Both options can be combined: `LLM_CACHE_ENABLED=true` + `LLM_ANTHROPIC_PROMPT_CACHE=true` provides in-process de-duplication (saves the network call entirely) as the primary layer, and Anthropic server-side caching as a secondary layer for cache misses.

## Centralized Settings

Configuration is loaded via a Pydantic Settings model at startup. All environment variables are validated and typed. Use `get_settings()` for direct access:

```python
from claim_agent.config import get_settings

settings = get_settings()
# Typed access: settings.router.confidence_threshold, settings.paths.claims_db_path, etc.
```

The module `src/claim_agent/config/settings.py` provides backward-compatible functions that delegate to `get_settings()`:

| Function / Constant | Purpose |
|---------------------|---------|
| `get_router_config()` | Router confidence threshold, validation enabled |
| `get_coverage_config()` | FNOL coverage verification (enabled, deny when deductible exceeds damage) |
| `get_escalation_config()` | Escalation thresholds (confidence, high value, similarity range, etc.) |
| `get_fraud_config()` | Fraud detection scores and thresholds |
| `get_crew_verbose()` | Whether CrewAI runs in verbose mode |
| `get_mask_pii()` | Whether to mask PII in logs (from `CLAIM_AGENT_MASK_PII`) |
| `get_retention_period_years()` | Retention period from compliance or `RETENTION_PERIOD_YEARS` |
| `get_retention_by_state()` | State-specific retention periods (years) from `STATE_RETENTION_PATH` |
| `get_api_keys_config()` | API keys mapping (key -> role) from `API_KEYS` or `CLAIMS_API_KEY` |
| `get_api_key_entries()` | API keys as `ApiKeyEntry` (role + optional identity) for `key:role:user_id` |
| `get_jwt_secret()` | JWT secret for Bearer token verification, or None |
| `get_jwt_access_ttl_seconds()` / `get_jwt_refresh_ttl_seconds()` | JWT and refresh token TTLs |
| `MAX_TOKENS_PER_CLAIM`, `MAX_LLM_CALLS_PER_CLAIM` | Token and call budgets per claim |
| `DEFAULT_BASE_VALUE`, `DEPRECIATION_PER_YEAR`, etc. | Valuation and partial-loss defaults |
| `get_adapter_backend(name)` | Configured adapter backend for a given adapter name |

Router variables: `ROUTER_CONFIDENCE_THRESHOLD` (default 0.7), `ROUTER_VALIDATION_ENABLED` (default false). When `ROUTER_VALIDATION_ENABLED=true`, the optional second-pass validation LLM call uses `OPENAI_MODEL_NAME` (the same variable that controls all other LLM calls; default `gpt-4o-mini`).

Coverage verification: `COVERAGE_ENABLED` (default true) enables FNOL coverage verification before routing. When enabled, claims are checked for:
- Active policy status
- Physical damage coverage (collision/comprehensive)
- Policy territory restrictions (`incident_location` or `loss_state` vs. policy `territory` / `excluded_territories`; see [adapters.md](adapters.md) for US insular areas and Canadian province matching)
- Named insured or authorized driver verification (when policy data available)
- Optionally `COVERAGE_DENY_WHEN_DEDUCTIBLE_EXCEEDS_DAMAGE` (default false) to deny when deductible exceeds estimated damage

Set `COVERAGE_REQUIRE_INCIDENT_LOCATION=true` to route to `under_investigation` when location is missing and the policy defines territory restrictions.

When a claimant is provided but does not match the named insured or authorized drivers on the policy, the claim is routed to `under_investigation` for manual review.

**`under_investigation` status (overload):** The same claim status is used for several manual-review situations: SIU / fraud escalation, policy lookup or parsing failures during coverage verification, deductible comparison errors, and claimant vs. named-insured/driver mismatches. It is **not** exclusively a fraud flag. Use audit metadata, `workflow_output`, and task checkpoints (e.g. `coverage_verification`) to distinguish the reason. Compliance and dashboard views that group `under_investigation` with fraud should treat the status as “needs human review” unless other signals indicate SIU.

Duplicate detection: `DUPLICATE_SIMILARITY_THRESHOLD` (default 40), `DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE` (default 60), `DUPLICATE_DAYS_WINDOW` (default 3). These control when claims with the same VIN are considered duplicates for routing.

High-value thresholds: `HIGH_VALUE_DAMAGE_THRESHOLD` (default 25000), `HIGH_VALUE_VEHICLE_THRESHOLD` (default 50000). Claims exceeding these use stricter duplicate similarity thresholds.

Pre-routing fraud: `PRE_ROUTING_FRAUD_DAMAGE_RATIO` (default 0.9). When damage-to-value ratio exceeds this and damage is not catastrophic, pre-routing fraud indicators are evaluated.

Escalation variables: `ESCALATION_CONFIDENCE_THRESHOLD`, `ESCALATION_HIGH_VALUE_THRESHOLD`, `ESCALATION_SIMILARITY_AMBIGUOUS_RANGE`, `ESCALATION_FRAUD_DAMAGE_VS_VALUE_RATIO`, `ESCALATION_VIN_CLAIMS_DAYS`, `ESCALATION_CONFIDENCE_DECREMENT_PER_PATTERN`, `ESCALATION_DESCRIPTION_OVERLAP_THRESHOLD`. Mid-workflow escalation SLA hours: `ESCALATION_SLA_HOURS_CRITICAL` (24), `ESCALATION_SLA_HOURS_HIGH` (24), `ESCALATION_SLA_HOURS_MEDIUM` (48), `ESCALATION_SLA_HOURS_LOW` (72). Low-confidence router escalations (always medium priority) use `ESCALATION_SLA_HOURS_MEDIUM`. `ROUTER_ESCALATION_SLA_HOURS` is deprecated in favor of the unified `ESCALATION_SLA_HOURS_*` constants. Set `ESCALATION_USE_AGENT=false` to use rule-based `evaluate_escalation` instead of the escalation agent.

Fraud variables: `FRAUD_MULTIPLE_CLAIMS_DAYS`, `FRAUD_MULTIPLE_CLAIMS_THRESHOLD`, `FRAUD_*_SCORE`, `FRAUD_*_THRESHOLD`, `FRAUD_CRITICAL_INDICATOR_COUNT`.

Valuation/partial loss: `VALUATION_*`, `PARTIAL_LOSS_*`. See `.env.example` for all variable names and defaults.

## Secret Management

### Overview

By default, all secrets (API keys, JWT secret, database passwords, webhook
secrets, etc.) are read from environment variables / the `.env` file.  For
pilot and production deployments, **integrate with a centralized secret store**
to enable rotation, audit trails, and access control without redeploying the
application.

The backend is selected by the `SECRET_PROVIDER` environment variable
(default: `env`).  Secrets fetched from the external store are injected into
the process environment **before** Pydantic Settings initialises, so the rest
of the application is unaware of the source.  An existing environment variable
always takes precedence over the value from the store (hard-wired overrides
win).

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_PROVIDER` | `env` | Secret backend: `env`, `aws_secrets_manager`, or `hashicorp_vault` |

### Secrets managed by the provider

The following application variables are expected as keys in the external secret
store's JSON object.  Variables that are absent from the fetched secret fall
back to the environment (or their Pydantic default):

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | LLM provider API key |
| `JWT_SECRET` | JWT signing secret (≥ 32 chars) |
| `API_KEYS` | Comma-separated `key:role[:user_id]` entries |
| `CLAIMS_API_KEY` | Single legacy API key |
| `WEBHOOK_SECRET` | HMAC-SHA256 signing secret for outbound webhooks |
| `SENDGRID_API_KEY` | SendGrid email API key |
| `TWILIO_AUTH_TOKEN` | Twilio SMS auth token |
| `LANGSMITH_API_KEY` | LangSmith tracing key |
| `OTP_PEPPER` | Server-side HMAC pepper for OTP codes |
| `DATABASE_URL` | PostgreSQL primary connection URL |
| `READ_REPLICA_DATABASE_URL` | PostgreSQL read-replica URL |

### AWS Secrets Manager

Store all secrets as a single JSON-valued secret:

```json
{
  "OPENAI_API_KEY": "sk-or-v1-...",
  "JWT_SECRET": "change-me-to-a-long-random-string-in-production",
  "WEBHOOK_SECRET": "...",
  "DATABASE_URL": "postgresql://user:pass@rds.example.com:5432/claims"
}
```

Required configuration:

```bash
SECRET_PROVIDER=aws_secrets_manager
AWS_SECRET_NAME=claim-agent/production   # ARN or friendly name
AWS_REGION=us-east-1                    # Falls back to SDK region chain
```

Optional:

```bash
AWS_SECRET_VERSION_ID=        # Pin to a specific version UUID
AWS_SECRET_VERSION_STAGE=     # Pin to a staging label (default: AWSCURRENT)
```

The AWS SDK authenticates via the standard credential chain (instance role,
`~/.aws/credentials`, `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars).
Install `boto3` with `pip install -e '.[s3]'`.

#### IAM policy (least privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:claim-agent/*"
    }
  ]
}
```

### HashiCorp Vault

Store secrets as a KV v2 (or v1) secret whose keys match the variable names above.

```bash
SECRET_PROVIDER=hashicorp_vault
VAULT_ADDR=https://vault.example.com:8200
VAULT_PATH=claim-agent/production        # KV path (no kv/data prefix)
VAULT_KV_VERSION=2                       # default: 2
```

**Token auth (dev / CI):**

```bash
VAULT_TOKEN=s.XXXXXXXXXXXX
```

**AppRole auth (production — recommended):**

```bash
VAULT_ROLE_ID=<role-id>
VAULT_SECRET_ID=<secret-id>
```

**TLS options:**

```bash
VAULT_CA_CERT=/etc/ssl/certs/vault-ca.pem   # Custom CA bundle
VAULT_NAMESPACE=admin/                        # Vault Enterprise namespace
VAULT_SKIP_VERIFY=false                       # Never true in production
```

Install the `hvac` client with `pip install hvac`.

### Secret rotation procedures

**Principle:** rotate secrets regularly and avoid downtime by staging a new
secret value alongside the old one until all consumers have picked it up.

#### API keys (`API_KEYS` / `CLAIMS_API_KEY`)

1. Add the new key to `API_KEYS` alongside the old one (comma-separated).
2. Distribute the new key to all consumers.
3. After confirming consumers use the new key, remove the old entry from
   `API_KEYS`.
4. For AWS Secrets Manager: update the secret value and let the next pod
   restart (or a SIGHUP / rolling deploy) pick it up.  For zero-downtime,
   keep both keys in `API_KEYS` during the transition.

#### JWT secret (`JWT_SECRET`)

Changing `JWT_SECRET` immediately invalidates **all** existing access tokens
(users must re-authenticate).  Rotate during a maintenance window, or
implement a two-key verification window (verify with old key if new fails)
outside of this codebase.

1. Generate a new secret: `python -c "import secrets; print(secrets.token_hex(32))"`.
2. Update the secret store with the new value.
3. Trigger a rolling restart (Kubernetes: `kubectl rollout restart deployment/claim-agent`).

#### Database password (`DATABASE_URL`)

1. Create a new database user / rotate the existing password in your RDS /
   Cloud SQL console or Vault database secrets engine.
2. Update the secret in the store.
3. Restart the application (rolling deploy); the new pool will use the new URL.
4. Revoke or drop the old credentials after the rollout completes.

#### Webhook secret (`WEBHOOK_SECRET`)

1. Update the secret in the store.
2. Coordinate with the receiving endpoint to accept the new signature (if
   possible, keep the old secret active briefly for in-flight requests).
3. Restart the application.

#### SendGrid / Twilio keys

1. Generate a new key in the provider's dashboard.
2. Update the secret in the store.
3. Restart the application.
4. Revoke the old key in the provider's dashboard.

#### Rotation schedule recommendations

| Secret | Recommended cadence |
|--------|---------------------|
| API keys | 90 days or on personnel change |
| JWT secret | 180 days |
| Database password | 90 days |
| Webhook secret | 180 days |
| LLM provider key | On compromise or annually |

#### Audit trail

AWS Secrets Manager emits CloudTrail events for every `GetSecretValue` call.
HashiCorp Vault's audit device logs every request.  Enable these in production
to maintain a full access audit trail.

## LLM Configuration Code

The module uses `load_dotenv()` and sets up observability (e.g. LangSmith) on first LLM use:

```python
# src/claim_agent/config/llm.py (simplified)

def get_llm():
    """Return the configured LLM for agents. Requires OPENAI_API_KEY."""
    setup_observability()  # LangSmith etc., called once on first LLM use

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")

    base = os.environ.get("OPENAI_API_BASE", "").strip()
    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()

    if base and "openrouter" in base.lower():
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)
```

## Data Files

### mock_db.json

Contains mock data for:
- **Policies**: Policy validation, coverage types, deductibles
- **Vehicle values**: Mock KBB-style valuations
- **claims**: Optional; reference/seed data only (often empty `[]`)

```json
{
  "policies": [
    {
      "policy_number": "POL-001",
      "status": "active",
      "coverage": "comprehensive",
      "deductible": 500
    }
  ],
  "vehicle_values": [
    {
      "vin": "1HGBH41JXMN109186",
      "value": 25000,
      "condition": "good"
    }
  ],
  "claims": []
}
```

### california_auto_compliance.json

California-specific compliance rules, deadlines, and disclosures:

```json
{
  "rules": [
    {
      "id": "CA-001",
      "category": "disclosure",
      "title": "Settlement Disclosure",
      "description": "Must disclose basis for settlement offer",
      "deadline_days": 30
    }
  ]
}
```

### State Policy Language Files

Reference policy language for different states:
- `california_auto_policy_language.json`
- `florida_auto_policy_language.json`
- `new_york_auto_policy_language.json`
- `texas_auto_policy_language.json`

## Agent Configuration

Agent roles, goals, and backstories are defined in **skill files** - markdown documents in the `skills/` folder. This allows easy customization of agent behavior without modifying code.

See [Skills](skills.md) for complete documentation.

### Skills Directory

```
src/claim_agent/skills/
├── router.md           # Claim Router Supervisor
├── intake.md           # Intake Specialist
├── policy_checker.md   # Policy Verification Specialist
└── ...                 # dozens of skill files (see `skills/` directory)
```

### Skill File Format

```markdown
# Router Agent Skill

## Role
Claim Router Supervisor

## Goal
Classify claims and delegate to appropriate workflow

## Backstory
Senior claims manager with expertise in routing
```

### Reference YAML Files

The `config/` folder also contains reference YAML files for agent and task definitions:

#### agents.yaml

```yaml
router:
  role: Claim Router Supervisor
  goal: Classify claims and delegate to appropriate workflow
  backstory: Senior claims manager with expertise in routing
```

#### tasks.yaml

```yaml
classify:
  description: Classify the claim as new, duplicate, total_loss, fraud, or partial_loss
  expected_output: One classification with brief reasoning
```

Note: Agents now load their configuration from skill files, which provide more detailed prompts and context than the YAML reference files.

## Directory Structure

```
project/
├── .env                    # Your configuration (not in git)
├── .env.example            # Template for .env (all env vars documented)
├── data/
│   ├── claims.db           # SQLite database (created automatically)
│   ├── mock_db.json        # Policy and vehicle data
│   ├── california_auto_compliance.json
│   └── *_auto_policy_language.json
└── src/claim_agent/
    ├── config/
    │   ├── llm.py          # LLM configuration
    │   ├── settings.py     # Centralized settings (escalation, fraud, valuation, token budgets)
    │   ├── agents.yaml     # Agent reference
    │   └── tasks.yaml      # Task reference
    └── skills/
        ├── __init__.py     # Skill loading utilities
        └── *.md            # Agent skill definitions
```

## Logging and Verbose Mode

CrewAI verbose mode is controlled by `CREWAI_VERBOSE` (default: `true`). Set to `false` to reduce crew output. For general Python logging:

```python
import logging
logging.getLogger("crewai").setLevel(logging.WARNING)
```

## Testing Configuration

For testing without an API key:

```bash
# Run unit tests (no API key needed)
MOCK_DB_PATH=data/mock_db.json pytest tests/test_tools.py -v

# Run integration tests (API key required)
OPENAI_API_KEY=your-key pytest tests/test_crews.py -v
```

## Production Considerations

### Database

For production, consider:
1. Moving to PostgreSQL for better concurrency
2. Setting up regular backups
3. Implementing connection pooling

### API Keys

1. Use a secrets manager (AWS Secrets Manager, HashiCorp Vault)
2. Rotate keys regularly
3. Set up usage limits and monitoring

### Logging

1. Configure structured logging (JSON format)
2. Send logs to centralized logging service
3. Set up alerting for errors

### Performance

1. Consider caching for frequently accessed data
2. Use async processing for high-volume scenarios
3. Monitor LLM API usage and costs

## Configuration Validation

The system validates configuration at startup:

```python
# Fails fast if OPENAI_API_KEY is not set
from claim_agent.config.llm import get_llm
llm = get_llm()  # Raises ValueError if key missing
```

## Example .env File

See `.env.example` in the project root for the full list of variables. Minimal example:

```bash
# LLM Configuration (Required)
OPENAI_API_KEY=sk-or-v1-your-openrouter-key

# OpenRouter Configuration (Optional - for using OpenRouter)
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet

# Data Paths (Optional - defaults shown)
CLAIMS_DB_PATH=data/claims.db
MOCK_DB_PATH=data/mock_db.json
CA_COMPLIANCE_PATH=data/california_auto_compliance.json

# Optional: Escalation, fraud, valuation, token budgets, CREWAI_VERBOSE
# See .env.example for all options.
```
