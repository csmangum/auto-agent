# Design Considerations

This document describes known limitations, design trade-offs, and future enhancements for the Agentic Claim Representative system.

For architecture and security details, see [Architecture](architecture.md). For configuration options, see [Configuration](configuration.md).

## Router Classification

The router classifies claims into one of five types: `new`, `duplicate`, `total_loss`, `fraud`, or `partial_loss`. Classification is based on LLM analysis of claim data (incident description, damage description, VIN, dates, etc.).

### Confidence Threshold

When the router returns a **confidence score** below `ROUTER_CONFIDENCE_THRESHOLD` (default 0.7), the claim is escalated to `needs_review` for human classification before any workflow runs. This prevents low-confidence automated routing from misdirecting claims.

- **Configurable**: Set `ROUTER_CONFIDENCE_THRESHOLD` in `.env` (e.g., `0.5` for more permissive routing).
- **Inference**: When the router output is plain text (legacy format), confidence is inferred from keywords in the reasoning. Explicit JSON output with `confidence` is preferred.

### Optional Validation Pass

Set `ROUTER_VALIDATION_ENABLED=true` to run a second LLM call when confidence is low. If the validation pass returns high confidence, the workflow proceeds (with optional re-classification if validation disagrees with the initial router). This adds latency and cost but can reduce unnecessary escalations.

### Known Limitations

- **LLM variability**: Classification can vary between runs for borderline claims.
- **No structured output guarantee**: Legacy router output may not include explicit `confidence`; the system infers it from text.
- **Five types only**: The router is trained for five claim types; new types require router skill and main flow updates.

## Known Limitations

### Data and Integrations

- **Mock adapters**: Policy, valuation, repair shop, parts, and SIU adapters default to mock implementations. Production requires real integrations.
- **California compliance only**: RAG compliance data exists only for California; Texas, Florida, and New York have policy language but no compliance JSON. See [Compliance Corpus Requirements](compliance-corpus-requirements.md).
- **SQLite**: Sufficient for POC; production may require PostgreSQL for concurrency and scale.

### Workflow

- **Bodily injury**: Claims with both property damage and injury are routed to property-damage crews; a separate Bodily Injury crew exists but is invoked via API, not the main router.
- **Reopened claims**: Reopened claim handling is a sub-workflow; entry is via API, not router classification.
- **Token budgets**: Processing stops if `CLAIM_AGENT_MAX_TOKENS_PER_CLAIM` or `CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM` is exceeded; long workflows may hit limits.

### Observability

- **Prometheus metrics**: Exposed at `/metrics`; no auth (suitable for scraping). Per-claim metrics require supervisor role at `/api/metrics`.
- **Tracing**: LangSmith and OpenTelemetry are optional; enable via env vars.

## Future Enhancements

- **Additional claim types**: Extend router and crews for new workflows (e.g., glass-only, theft).
- **Multi-state compliance**: Add Texas, Florida, and New York compliance JSON for full RAG coverage.
- **Production adapters**: Replace mock adapters with real policy DB, KBB/valuation API, repair shop networks, parts catalogs, SIU systems.
- **Review queue UI**: Backend API exists; frontend consumption is planned. See [Review Queue](review-queue.md).
- **Structured router output**: Enforce JSON output with `claim_type`, `confidence`, `reasoning` for all router responses.
