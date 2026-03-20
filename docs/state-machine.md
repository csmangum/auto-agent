# Claim State Machine

The claim lifecycle is enforced by a formal state machine in `src/claim_agent/db/state_machine.py`. Invalid transitions raise `InvalidClaimTransitionError` and are logged for compliance alerting.

## Valid Transitions

The base graph below applies to all claims. **Claim-type variants** add extra edges or optional guards (see next section).

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

## Claim-type variants

`can_transition()` and `validate_transition()` accept optional `claim_type` (or read `claim["claim_type"]` from the claim row). Rules:

> **Note:** `claim_type` and `status` are **separate fields** on a claim. Some strings (e.g., `partial_loss`, `total_loss`) are valid values for *both* fields — `status` describes where the claim is in its lifecycle, while `claim_type` describes the nature of the claim. The table below uses these strings as **claim_type** values (not statuses).

| Claim type | Transition additions | Optional dict guards on `claim` |
|------------|------------------------|----------------------------------|
| `bodily_injury` | `open` → `pending_info` (document ongoing treatment / info holds) | — |
| `partial_loss` | (none) | If key `repair_ready_for_settlement` is present and `False`, `open` → `settled` is rejected |
| `total_loss` | (none) | If key `total_loss_settlement_authorized` is present and `False`, `open` → `settled` is rejected |

Unknown or missing `claim_type` uses **only** the base transition table; optional guard keys are ignored when absent so existing flows stay valid.

To add more variants, extend `_CLAIM_TYPE_TRANSITION_ADDITIONS` or `_type_specific_guard` in `src/claim_agent/db/state_machine.py`.

## Transition Guards

### Close Guard

Transition to `closed` requires one of:

- `payout_amount` is set (including 0 for administrative closure)
- `from_status` is `denied`, `duplicate`, or `failed` (no payout required)

This ensures closure is documented (settlement or denial).

## Bypass

- `actor_id="system"` or `force=True` skips validation when calling `validate_transition()` or `can_transition()` directly (for migrations, seeding, or tests)
- At the repository layer, use `skip_validation=True` on `update_claim_status()` to bypass the state machine

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

# Bodily injury: allow open -> pending_info when claim_type is set
validate_transition(
    claim_id,
    "open",
    "pending_info",
    claim=claim,
    claim_type="bodily_injury",
)
```
