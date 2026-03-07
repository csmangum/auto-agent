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
| `claimant_name` | First letter per word | `John Smith` → `J*** S***` |

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

### Retention Enforcement

Run the retention enforcement command to archive claims older than the retention period:

```bash
# Preview what would be archived (dry run)
claim-agent retention-enforce --dry-run

# Archive claims older than retention period
claim-agent retention-enforce

# Override retention period (e.g. 7 years)
claim-agent retention-enforce --years 7
```

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

## Related

- [Configuration](configuration.md) – CLAIM_AGENT_MASK_PII, RETENTION_PERIOD_YEARS
- [Observability](observability.md) – Structured logging, claim context
- [Database](database.md) – Schema, audit log
