# PII Handling and Data Retention

This document describes how the claim agent handles personally identifiable information (PII) in logs and enforces data retention policies for compliance.

## PII Masking

### Overview

Logs may contain policy numbers, VINs, and other PII. To comply with data protection requirements, the agent can mask these values in log output. Masking is **enabled by default** (`CLAIM_AGENT_MASK_PII=true`) for production safety.

### Masked Fields

| Field | Format | Example |
|-------|--------|---------|
| `policy_number` | First 3 + last 3 visible | `POL-12345-001` → `POL***001` |
| `vin` | First 3 + last 4 visible | `1HGCM82633A123456` → `1HG***3456` |

In structured `extra_data` (dicts), keys containing "claimant" or "name" are also masked (e.g. `claimant_name` → first letter per word).

### Configuration

| Variable | Default | Description |
|----------|--------|-------------|
| `CLAIM_AGENT_MASK_PII` | `true` | When `true`, mask policy_number and vin in StructuredFormatter, HumanReadableFormatter, and log extra dicts. Set to `false` for local development/debugging. |

### Where Masking Applies

- **StructuredFormatter** (JSON logs): `policy_number`, `vin`, and `data` (extra_data) are masked
- **HumanReadableFormatter**: Claim context prefix and extra_data
- **claim_context**: Values passed to `policy_number` and `vin` are masked when written to log output
- **Metrics export**: Claim IDs are not PII; policy_number/vin are not stored in metrics

### Disabling for Development

For local debugging where you need to see full values:

```bash
CLAIM_AGENT_MASK_PII=false claim-agent process claim.json
```

Or in `.env`:

```
CLAIM_AGENT_MASK_PII=false
```

## Data Retention

### Overview

California compliance (CCR 2695.3, ECR-003) requires claims records to be retained for at least 5 years. After the retention period, claims should be archived or deleted. The agent enforces retention via a CLI command.

### Retention Period

| Source | Default |
|--------|---------|
| `RETENTION_PERIOD_YEARS` env | Override (e.g. `7`) |
| `california_auto_compliance.json` → `electronic_claims_requirements.provisions` (id: ECR-003) | 5 years |
| Fallback | 5 years |

### State-Specific Retention

When `data/state_retention_periods.json` exists, claims use `loss_state` to pick per-state retention. Unlisted states or missing `loss_state` fall back to the default period.

| File | Path (config) |
|------|---------------|
| `data/state_retention_periods.json` | `STATE_RETENTION_PATH` |

Example:

```json
{
  "retention_by_state": {
    "California": 5,
    "Texas": 7,
    "Florida": 5,
    "New York": 6,
    "Georgia": 7
  },
  "purge_after_archive_by_state": {
    "California": 3,
    "Texas": 4,
    "New York": 3
  }
}
```

Optional `purge_after_archive_by_state` sets how many **calendar years** after `archived_at` before a claim may be purged, per `loss_state`. Values must be integers **≥ 0** (`0` means eligible as of the archive timestamp’s calendar day). Unlisted states and claims whose `loss_state` cannot be normalized (typos, unsupported states) use the global `RETENTION_PURGE_AFTER_ARCHIVE_YEARS` instead. **`retention-purge` / `retention-report` with `--years` / `--purge-years` forces the global value and ignores this map** (operational override).

**Important:** JSON keys must match canonical state names from `rag.constants.normalize_state` (e.g. `"California"`, not `"CA"`). Supported states are defined in `SUPPORTED_STATES`. Adding a new state (e.g. Nevada) to the JSON alone will not take effect—claims with unsupported `loss_state` values fall back to the default retention period. To support a new state, update both `state_retention_periods.json` and `rag.constants` (SUPPORTED_STATES, _STATE_ABBREV_TO_CANONICAL).

### Litigation Hold

Claims with `litigation_hold=1` are excluded from retention enforcement by default (retention suspended for claims in litigation). They are also skipped during DSAR deletion when `LITIGATION_HOLD_BLOCKS_DELETION=true`.

- **Set/clear hold**: `PATCH /api/claims/{claim_id}/litigation-hold` with `{"litigation_hold": true|false}`
- **CLI**: `claim-agent litigation-hold --claim-id X --on` or `--off`
- **Override**: `claim-agent retention-enforce --include-litigation-hold` archives claims with hold (use with caution)

### Retention Enforcement

Run the retention enforcement command to archive claims older than the retention period:

```bash
# Preview what would be archived (dry run)
claim-agent retention-enforce --dry-run

# Archive claims older than retention period (skips litigation hold)
claim-agent retention-enforce

# Override retention period (e.g. 7 years)
claim-agent retention-enforce --years 7

# Include claims with litigation hold (default: exclude)
claim-agent retention-enforce --include-litigation-hold
```

### Retention purge (after archive)

After claims have been archived for `RETENTION_PURGE_AFTER_ARCHIVE_YEARS` (default 2), purge anonymizes PII and sets `status=purged`. Per-state delays may be set in `state_retention_periods.json` under `purge_after_archive_by_state` (see State-Specific Retention example above).

```bash
claim-agent retention-purge --dry-run
claim-agent retention-purge
claim-agent retention-purge --years 3
claim-agent retention-purge --include-litigation-hold
# Export to cold storage before anonymising (requires RETENTION_EXPORT_ENABLED=true):
claim-agent retention-purge --export-before-purge
```

Dry-run and post-purge JSON output may include `purge_by_state` when the per-state map is loaded from config (omitted when you pass `--years`, which disables the map). When `--export-before-purge` is used, the output also includes `exported_count`, `exported_claim_ids`, `export_failed_count`, and `export_failed_claim_ids`.

### Cold-storage export pipeline (S3 / Glacier)

Before or instead of in-place anonymisation, the `retention-export` command writes a **JSON manifest** (full claim data + audit log summary) to S3, allowing the bucket lifecycle policy to transition objects to Glacier or Glacier Instant Retrieval automatically.  Records are idempotent (`cold_storage_exported_at` column) — re-running the command skips already-exported claims.

| Variable | Default | Description |
|----------|---------|-------------|
| `RETENTION_EXPORT_ENABLED` | `false` | Must be `true` to allow exports. |
| `RETENTION_EXPORT_S3_BUCKET` | (required) | Destination bucket. |
| `RETENTION_EXPORT_S3_PREFIX` | `retention-exports` | Key prefix inside the bucket. |
| `RETENTION_EXPORT_S3_ENDPOINT` | (unset) | Optional S3-compatible endpoint (MinIO, etc.). |
| `RETENTION_EXPORT_S3_STORAGE_CLASS` | `GLACIER_IR` | Storage class (e.g. `GLACIER_IR`, `GLACIER`, `STANDARD_IA`). |
| `RETENTION_EXPORT_ENCRYPTION` | `AES256` | Server-side encryption: `AES256` or `aws:kms`. |
| `RETENTION_EXPORT_KMS_KEY_ID` | (unset) | KMS key ARN/alias when `encryption=aws:kms`. |

The exported key is stored in `cold_storage_export_key` on the claim row and a `cold_storage_exported` audit event is appended.

**Recommended operational flow:**

```bash
# 1. Preview what would be exported
claim-agent retention-export --dry-run

# 2. Export to cold storage (requires RETENTION_EXPORT_ENABLED + bucket configured)
RETENTION_EXPORT_ENABLED=true RETENTION_EXPORT_S3_BUCKET=my-archive-bucket \
  claim-agent retention-export

# 3. Then purge (anonymise) separately
claim-agent retention-purge

# Or combine steps 2 & 3 in one call
RETENTION_EXPORT_ENABLED=true RETENTION_EXPORT_S3_BUCKET=my-archive-bucket \
  claim-agent retention-purge --export-before-purge
```

### Retention Audit Report

Produce a retention audit report with counts by tier, litigation hold, and pending archive:

```bash
claim-agent retention-report
claim-agent retention-report --years 7
claim-agent retention-report --purge-years 3
```

Output includes: `retention_period_years`, `purge_after_archive_years`, `retention_by_state`, `purge_by_state`, `claims_by_status`, `claims_by_retention_tier`, `active_count`, `closed_count`, `archived_count`, `purged_count`, `litigation_hold_count`, `closed_with_litigation_hold`, `pending_archive_count`, `pending_purge_count`, `audit_log_rows`, `audit_log_rows_for_purged_claims`, `audit_log_rows_for_non_purged_claims`, `audit_log_retention_years_after_purge`, `audit_log_rows_eligible_for_retention` (eligibility counts require `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE` or `retention-report --audit-purge-years`).

### Audit log retention (issue #350)

[GitHub #350](https://github.com/csmangum/auto-agent/issues/350) tracks policy and tooling for **unbounded** `claim_audit_log` growth. Claim-level retention (`retention-purge`) does **not** remove audit rows; triggers historically blocked `DELETE` until migration `039_allow_claim_audit_log_delete_for_retention`.

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE` | (unset) | Calendar years after `purged_at` before audit rows are eligible for export/purge reporting. Unset = no eligibility window; counts in reports are `null`. |
| `AUDIT_LOG_PURGE_ENABLED` | `false` | Must be `true` for `claim-agent audit-log-purge` to delete rows (in addition to `--ack-exported`). |

**Recommended operational flow:** configure a retention period → run `claim-agent retention-report` for breakdowns → `claim-agent audit-log-export --output ...` (cold storage) → `claim-agent audit-log-purge --ack-exported` only after legal/compliance approval.

```bash
claim-agent retention-report
claim-agent retention-report --audit-purge-years 7
claim-agent audit-log-export --output /secure/audit_export.ndjson --dry-run
# Dry-run JSON omits claim ID lists by default (use --print-eligible-claim-ids to include).
# Write IDs to a file: --eligible-claim-ids-file /secure/eligible_claim_ids.txt
claim-agent audit-log-export --output /secure/audit_export.ndjson
# After compliance sign-off and export verified:
AUDIT_LOG_PURGE_ENABLED=true claim-agent audit-log-purge --ack-exported --dry-run
AUDIT_LOG_PURGE_ENABLED=true claim-agent audit-log-purge --ack-exported
```

### Audit log PII redaction (in-place, before_state / after_state)

`claim_audit_log` stores `before_state` and `after_state` as JSON snapshots
that can contain PII (policy number, VIN, narrative descriptions, party
details).  Migration `039` removed the DELETE block; migration `049` relaxes
the UPDATE block so that **only the two JSON state columns** can be updated —
all other columns (`claim_id`, `action`, `old_status`, `new_status`, `details`,
`actor_id`, `created_at`) remain immutable, preserving tamper-evidence for
audit event metadata.

#### Threat model: tamper-evidence vs erasure

| Property | Impact after enabling redaction |
|----------|---------------------------------|
| **Who did what and when** | Unchanged — `action`, `actor_id`, `created_at`, status transitions remain immutable |
| **Before/after PII values** | Replaced with `[REDACTED]` — pre-redaction PII is erased from the audit trail |
| **Compliance record** | Audit row is retained; only the PII payload is scrubbed |

This satisfies GDPR/CCPA right-to-erasure while keeping audit-event metadata
(the *what happened* record) intact.  If your threat model requires full
immutability of all audit columns (e.g. regulatory frameworks that treat audit
logs as evidence that must never be altered), **leave this feature disabled**
and rely on export-then-purge instead.

#### Settings gate

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_STATE_REDACTION_ENABLED` | `false` | When `true`, before_state / after_state JSON is redacted in place during DSAR deletion and retention purge.  Requires migration 049. |

The default is `false`; existing deployments are unaffected until you opt in.

#### What gets redacted

The following keys are replaced with `[REDACTED]` wherever they appear in the
JSON (at the top level or inside nested objects):

| Key | Reason |
|-----|--------|
| `policy_number` | Direct PII |
| `vin` | Direct PII |
| `incident_description` | Narrative – may contain names/locations |
| `damage_description` | Narrative – may contain names/locations |
| `name` | Party PII |
| `email` | Party PII |
| `phone` | Party PII |
| `address` | Party PII |
| `attachments` | Replaced with `[]` (may reference external PII) |

Status, claim type, amounts, timestamps, and other non-PII fields are kept.

#### Enabling redaction

```bash
# .env or environment
AUDIT_LOG_STATE_REDACTION_ENABLED=true
```

Once set, every subsequent DSAR deletion or retention purge will also sanitize
the audit log rows for the affected claim(s).  Rows created *before* enabling
the setting are not retroactively redacted; to backfill older rows call the
`redact_audit_log_pii()` helper directly (see `src/claim_agent/db/pii_redaction.py`).

### Tiered retention (cold → archived → purged)

Claims carry a `retention_tier` (`active`, `cold`, `archived`, `purged`). On closure, tier moves to **cold** (closed claims within the legal retention window). `retention-enforce` still archives by age using `created_at` and per-state rules. After archive, **`RETENTION_PURGE_AFTER_ARCHIVE_YEARS`** (default 2) defines how long the row stays in `status=archived` before **`claim-agent retention-purge`** may run. The purge horizon uses **calendar years** from `archived_at` (same month/day anniversary, with day clamped for short months). Purge **anonymizes** the claim row (`policy_number`, `vin`, `incident_description`, `damage_description`, `attachments`), **claim_parties**, and **claim_notes** (same pattern as DSAR deletion), sets `status=purged`, `retention_tier=purged`, and `purged_at`; **claim_audit_log** rows are not deleted (when `AUDIT_LOG_STATE_REDACTION_ENABLED=true`, before_state / after_state JSON is also redacted in place).

### Archive Behavior

- **Soft delete**: Claims are marked with `status=archived` and `archived_at=datetime('now')`
- **Audit log**: Each archived claim gets an audit entry: `action=retention_archived`, `actor_id=retention`
- **Audit trail preserved**: The audit log is append-only for non-PII columns; archived claims remain in the database for audit history

### Retention Actions Logged

Every retention action is logged to `claim_audit_log` with:

- `action`: `retention_archived`
- `old_status`: Previous claim status
- `new_status`: `archived`
- `actor_id`: `retention`
- `details`: "Archived for retention (claim older than retention period)"

### Scheduling

Run `claim-agent retention-enforce` periodically (e.g. daily via cron):

```bash
# cron: daily at 2 AM
0 2 * * * cd /path/to/project && claim-agent retention-enforce
```

## LLM Data Minimization

When `LLM_DATA_MINIMIZATION=true` (default), claim data sent to LLM prompts is minimized:

- **Per-crew allowlists**: Only fields necessary for each crew's task are included
- **PII masking**: policy_number and VIN are masked (e.g. POL***001, 1HG***3456)
- **Attachment stripping**: Descriptions removed; url and type kept
- **Party PII**: For bodily_injury, party name/email/phone/address stripped; role kept. Parties with `consent_status=revoked` are excluded from LLM prompts

Set `LLM_DATA_MINIMIZATION=false` for debugging.

## DSAR (Data Subject Access Request)

### Access Requests (Right-to-Know)

- **Submit**: `POST /api/dsar/access` with claimant_identifier and verification (claim_id or policy_number+vin)
- **Status**: `GET /api/dsar/requests/{request_id}`
- **List**: `GET /api/dsar/requests` – paginated (limit, offset); returns `requests`, `total`, `limit`, `offset`
- **Fulfill**: `POST /api/dsar/requests/{request_id}/fulfill` – returns export with claims, parties, audit entries, notes
- **CLI**: `claim-agent dsar-access --claimant-email X --claim-id Y [--fulfill]`

### Deletion Requests (Right-to-Delete)

- **Submit**: `POST /api/dsar/deletion` with claimant_identifier and verification (claim_id or policy_number+vin)
- **Fulfill**: `POST /api/dsar/deletion/fulfill/{request_id}` – anonymizes claims (`policy_number`, `vin`, `incident_description`, `damage_description`, `attachments`), parties, and claim_notes (PII placeholders); claim_audit_log behavior is controlled by `DSAR_AUDIT_LOG_POLICY` (see below)
- **CLI**: `claim-agent dsar-deletion --claimant-email X --claim-id Y [--fulfill]`
- **Litigation hold**: When `LITIGATION_HOLD_BLOCKS_DELETION=true` (default), claims with `litigation_hold=1` are skipped. Set to `false` to anonymize regardless.

### Audit log policy during DSAR deletion

The `DSAR_AUDIT_LOG_POLICY` setting controls how `claim_audit_log` rows are handled when a DSAR deletion is fulfilled:

| Value | Behavior |
|-------|----------|
| `preserve` (default) | Audit rows are kept unchanged. Recommended for most jurisdictions where audit trail must be retained for legal/regulatory purposes. |
| `redact` | PII values under known keys (`policy_number`, `vin`, `incident_description`, `damage_description`, `name`, `email`, `phone`, `address`, `claimant_name`) are replaced with `[REDACTED]` in the `details`, `before_state`, and `after_state` JSON fields. Action type, actor, and timestamps are preserved. |
| `delete` | All `claim_audit_log` rows for the claim are permanently removed. Irreversible. Use only in jurisdictions that require full audit row removal for DSAR, and only after compliance sign-off. |

**Default is `preserve`** — no silent change to existing behavior without explicit configuration.

The `audit_log_policy` and `audit_rows_affected` fields are included in the deletion fulfillment response and in the `dsar_audit_log` for traceability.

### Consent Tracking

- **Update consent**: `PATCH /api/claims/{claim_id}/parties/{party_id}/consent` with `{"consent_status": "granted"|"revoked"|"pending"}`
- **Revoke by email**: `POST /api/dsar/consent-revoke` with `{"email": "..."}` – revokes consent for all parties with that email
- When `consent_status=revoked`, party PII is excluded from LLM prompts (e.g. bodily_injury crew)

### DSAR Configuration

- **DSAR_VERIFICATION_REQUIRED** (default: true): When true, require claim_id or policy_number+vin for verification. When false, allow claimant_identifier (email) lookup in claim_parties.
- **LITIGATION_HOLD_BLOCKS_DELETION** (default: true): When true, skip claims with litigation_hold during deletion. When false, anonymize regardless.
- **DSAR_AUDIT_LOG_POLICY** (default: `preserve`): Controls claim_audit_log handling during DSAR deletion. Options: `preserve`, `redact`, `delete`. See "Audit log policy during DSAR deletion" above.

## Related

- [Configuration](configuration.md) – CLAIM_AGENT_MASK_PII, RETENTION_PERIOD_YEARS, STATE_RETENTION_PATH, AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE, AUDIT_LOG_PURGE_ENABLED, AUDIT_LOG_STATE_REDACTION_ENABLED, LLM_DATA_MINIMIZATION, DSAR_VERIFICATION_REQUIRED, LITIGATION_HOLD_BLOCKS_DELETION
- [Configuration](configuration.md) – CLAIM_AGENT_MASK_PII, RETENTION_PERIOD_YEARS, STATE_RETENTION_PATH, AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE, AUDIT_LOG_PURGE_ENABLED, LLM_DATA_MINIMIZATION, DSAR_VERIFICATION_REQUIRED, LITIGATION_HOLD_BLOCKS_DELETION, DSAR_AUDIT_LOG_POLICY
- [Observability](observability.md) – Structured logging, claim context
- [Database](database.md) – Schema, audit log
