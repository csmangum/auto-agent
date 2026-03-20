# Claim State Machine

The claim lifecycle is enforced by a formal state machine in `src/claim_agent/db/state_machine.py`. Invalid transitions raise `InvalidClaimTransitionError` and are logged for compliance alerting.

## Valid Transitions

| From | Valid To |
|------|----------|
| pending | processing, open, needs_review, fraud_suspected |
| processing | open, duplicate, denied, settled, fraud_suspected, needs_review, failed, under_investigation |
| open | settled, disputed, needs_review, closed, processing, denied |
| needs_review | processing, denied, pending_info, under_investigation, closed |
| denied | needs_review, closed |
| disputed | dispute_resolved, needs_review |
| settled | disputed, closed |
| under_investigation | fraud_suspected, fraud_confirmed, needs_review |
| fraud_suspected | fraud_confirmed, needs_review |
| fraud_confirmed | closed |
| duplicate | closed |
| failed | closed, processing |
| dispute_resolved | closed |
| pending_info | needs_review, processing, closed |
| closed | archived |
| archived | (terminal) |
| partial_loss | closed, settled, needs_review |

## Transition Guards

### Close Guard

Transition to `closed` requires one of:

- `payout_amount` is set (including 0 for administrative closure)
- `from_status` is `denied`, `duplicate`, or `failed` (no payout required)

This ensures closure is documented (settlement or denial).

## Bypass

- `actor_id="system"` or `force=True` skips validation when calling `validate_transition()` or `can_transition()` directly (for migrations, seeding, or tests)
- At the repository layer, use `skip_validation=True` on `update_claim_status()` to bypass the state machine

## REST API

For non-streaming JSON REST endpoints, `InvalidClaimTransitionError` is handled globally in the FastAPI app (`create_app`): responses use **409 Conflict** with JSON fields `detail`, `claim_id`, `from_status`, `to_status`, and `reason`. Route handlers avoid catching it inside broad `except Exception` blocks that would map errors to 400 or 503; Pydantic validation failures use `ValidationError` only so domain transition errors are not misclassified.

For streaming/SSE endpoints (e.g., `/api/chat`), a JSON 409 response cannot be issued mid-stream. Transition errors in those paths are surfaced as SSE error events instead.

## Violation Logging

Invalid transition attempts are logged with `logger.warning` and `event=transition_violation`, including:

- `claim_id`, `from_status`, `to_status`, `actor_id`, `reason`

Use log aggregation to alert on compliance violations.

## Usage

```python
from claim_agent.db.state_machine import can_transition, validate_transition

# Check without raising
if can_transition("open", "closed", claim={"payout_amount": 1000.0}):
    repo.update_claim_status(claim_id, "closed", payout_amount=1000.0)

# Validate (raises InvalidClaimTransitionError if invalid)
validate_transition(claim_id, "open", "closed", claim=claim, payout_amount=1000.0)
```
