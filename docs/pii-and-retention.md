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
  }
}
```

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

### Retention Audit Report

Produce a retention audit report with counts by tier, litigation hold, and pending archive:

```bash
claim-agent retention-report
claim-agent retention-report --years 7
```

Output includes: `retention_period_years`, `retention_by_state`, `claims_by_status`, `active_count`, `closed_count`, `archived_count`, `litigation_hold_count`, `closed_with_litigation_hold`, `pending_archive_count`, `audit_log_rows`.

### Archive Behavior

- **Soft delete**: Claims are marked with `status=archived` and `archived_at=datetime('now')`
- **Audit log**: Each archived claim gets an audit entry: `action=retention_archived`, `actor_id=retention`
- **Audit trail preserved**: The audit log is append-only; archived claims remain in the database for audit history

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
- **Fulfill**: `POST /api/dsar/deletion/fulfill/{request_id}` – anonymizes claims, parties, and claim_notes (sets PII to [REDACTED]); preserves claim_audit_log for legal/regulatory requirements
- **CLI**: `claim-agent dsar-deletion --claimant-email X --claim-id Y [--fulfill]`
- **Litigation hold**: When `LITIGATION_HOLD_BLOCKS_DELETION=true` (default), claims with `litigation_hold=1` are skipped. Set to `false` to anonymize regardless.

### Consent Tracking

- **Update consent**: `PATCH /api/claims/{claim_id}/parties/{party_id}/consent` with `{"consent_status": "granted"|"revoked"|"pending"}`
- **Revoke by email**: `POST /api/dsar/consent-revoke` with `{"email": "..."}` – revokes consent for all parties with that email
- When `consent_status=revoked`, party PII is excluded from LLM prompts (e.g. bodily_injury crew)

### DSAR Configuration

- **DSAR_VERIFICATION_REQUIRED** (default: true): When true, require claim_id or policy_number+vin for verification. When false, allow claimant_identifier (email) lookup in claim_parties.
- **LITIGATION_HOLD_BLOCKS_DELETION** (default: true): When true, skip claims with litigation_hold during deletion. When false, anonymize regardless.

## Related

- [Configuration](configuration.md) – CLAIM_AGENT_MASK_PII, RETENTION_PERIOD_YEARS, STATE_RETENTION_PATH, LLM_DATA_MINIMIZATION, DSAR_VERIFICATION_REQUIRED, LITIGATION_HOLD_BLOCKS_DELETION
- [Observability](observability.md) – Structured logging, claim context
- [Database](database.md) – Schema, audit log
