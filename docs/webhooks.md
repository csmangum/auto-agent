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
| `claim.closed` | Claim closed (open, closed, duplicate, fraud_suspected, settled) |
| `claim.denied` | Rejected by adjuster |
| `claim.pending_info` | More info requested |
| `claim.under_investigation` | Escalated to SIU |
| `claim.archived` | Archived for retention (older than retention period) |
| `repair.authorized` | Repair authorization generated for partial loss |

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
- Retries on connection errors, timeouts, and 5xx responses
- After max retries: log error; optionally append to `WEBHOOK_DEAD_LETTER_PATH`
- Delivery runs in a thread pool; does not block claim processing

## Dead-Letter File

When `WEBHOOK_DEAD_LETTER_PATH` is set, failed deliveries (after all retries) are appended as JSONL (one JSON object per line). Each line contains `url`, `payload`, and `error`.

**Rotation**: The file grows unbounded. Operators should rotate or archive it periodically (e.g. via logrotate or a scheduled job). Consider moving processed lines to an archive before truncating.

**Concurrency**: Multiple threads may append to the same file. Writes are atomic per line (each `write` is a single JSON object + newline). Under heavy load, lines from different deliveries may interleave; each line remains valid JSON and can be parsed independently.
