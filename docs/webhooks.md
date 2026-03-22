# Webhooks

Outbound webhooks notify external systems when claim status changes or when repairs are authorized. Configure one or more URLs to receive POST requests with JSON payloads and optional HMAC signatures.

## Configuration

| Variable | Description |
|----------|-------------|
| `WEBHOOK_URL` | Single webhook URL (used if WEBHOOK_URLS is unset) |
| `WEBHOOK_URLS` | Comma-separated list of webhook URLs |
| `WEBHOOK_SECRET` | Secret for HMAC-SHA256 signature (optional) |
| `WEBHOOK_MAX_RETRIES` | Max delivery retries (default: 5) |
| `WEBHOOK_ENABLED` | Enable/disable webhooks (default: true) |
| `WEBHOOK_SHOP_URL` | Optional shop-specific URL for repair.authorized |
| `WEBHOOK_DEAD_LETTER_PATH` | Optional file path for failed deliveries |

## Events

| Event | When |
|-------|------|
| `claim.submitted` | Claim created (status: pending) |
| `claim.processing` | Workflow started |
| `claim.needs_review` | Escalated to human review |
| `claim.failed` | Workflow failed |
| `claim.opened` | Claim opened for claimant (status: open) |
| `claim.closed` | Claim resolved (closed, duplicate, fraud_suspected, settled) |
| `claim.denied` | Rejected by adjuster |
| `claim.pending_info` | More info requested |
| `claim.under_investigation` | Escalated to SIU |
| `claim.archived` | Archived for retention (older than retention period) |
| `repair.authorized` | Repair authorization generated for partial loss |
| `ucspa.deadline_approaching` | UCSPA compliance deadline is within the configured lookahead window (from `ucspa-deadlines` CLI or the in-process scheduler) |

### UCSPA deadline approaching (no server-side deduplication)

The server may send **`ucspa.deadline_approaching`** more than once for the same claim: while a deadline remains in the lookahead window (see `SCHEDULER_UCSPA_DAYS_AHEAD` or `ucspa-deadlines --days`), each daily (or manual) run can dispatch again. This matches a **daily reminder** model. Integrators that need at-most-once alerts should dedupe on a stable key such as `(claim_id, deadline_type, due_date)` (or track the last handled delivery in their system).

## Payload Schema

### Claim events

```json
{
  "event": "claim.processing",
  "claim_id": "CLM-ABC12345",
  "status": "processing",
  "timestamp": "2026-03-07T12:00:00.000000+00:00",
  "summary": "Workflow started",
  "claim_type": "partial_loss",
  "payout_amount": 2500.00
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Event name |
| `claim_id` | string | Claim ID |
| `status` | string | Current claim status |
| `timestamp` | string | ISO 8601 UTC |
| `summary` | string | Optional human-readable summary |
| `claim_type` | string | Optional (new, duplicate, partial_loss, etc.) |
| `payout_amount` | number | Optional settlement amount |

### Repair authorized

```json
{
  "event": "repair.authorized",
  "claim_id": "CLM-ABC12345",
  "shop_id": "SHOP-001",
  "shop_name": "Premier Auto Body",
  "shop_phone": "310-555-0101",
  "authorized_amount": 3500.00,
  "authorization_id": "RA-ABCD1234",
  "timestamp": "2026-03-07T12:00:00.000000+00:00"
}
```

### UCSPA deadline approaching

```json
{
  "event": "ucspa.deadline_approaching",
  "claim_id": "CLM-ABC12345",
  "deadline_type": "acknowledgment",
  "due_date": "2026-03-25",
  "loss_state": "California",
  "timestamp": "2026-03-07T12:00:00.000000+00:00"
}
```

`loss_state` is omitted when unknown.

## HMAC Signature Verification

When `WEBHOOK_SECRET` is set, each request includes an `X-Webhook-Signature` header:

```
X-Webhook-Signature: sha256=<hex_digest>
```

Verify in your endpoint:

```python
import hmac
import hashlib

def verify_webhook(body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    # Header format: "sha256=<hex>"
    if not signature_header.startswith("sha256="):
        return False
    received = signature_header[7:]
    return hmac.compare_digest(expected, received)
```

## Retry Behavior

- Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at 60s)
- Retries on connection errors, timeouts, 408 (Request Timeout), 429 (Too Many Requests), and 5xx responses
- Non-retriable 4xx (e.g. 400, 401) are not retried
- After max retries: log error; optionally append to `WEBHOOK_DEAD_LETTER_PATH`
- Delivery runs in a thread pool; does not block claim processing

## Dead-Letter File

When `WEBHOOK_DEAD_LETTER_PATH` is set, failed deliveries (after all retries) are appended as JSONL (one JSON object per line). Each line contains `url`, `payload`, and `error`.

**Rotation**: The file grows unbounded. Operators should rotate or archive it periodically (e.g. via logrotate or a scheduled job). Consider moving processed lines to an archive before truncating.

**Concurrency**: Multiple threads may append to the same file. The application does not provide explicit locking or guarantee of line-level atomicity; depending on the OS and filesystem, writes from different deliveries may interleave at sub-line granularity and individual lines may become invalid JSON. Treat this file as best-effort diagnostics, or ensure a single writer (e.g. a single worker process or external log aggregation) if you require strict JSONL integrity.
