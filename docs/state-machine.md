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

**Note:** `under_investigation` is also set by **non-SIU** paths (e.g. FNOL coverage verification when the policy adapter fails, the policy response is invalid, or the claimant does not match named insureds/drivers). See [Configuration](configuration.md#environment-variables) for coverage behavior; use claim audit / workflow output to tell *why* a claim landed in this status.
| fraud_suspected | fraud_confirmed, needs_review |
| fraud_confirmed | closed |
| duplicate | closed |
| failed | closed, processing |
| dispute_resolved | closed |
| pending_info | needs_review, processing, closed |
| closed | archived |
| archived | purged |
| purged | (terminal) |
| partial_loss | closed, settled, needs_review |

## Claim-type variants

`can_transition()` and `validate_transition()` accept optional `claim_type` (or read `claim["claim_type"]` from the claim row). Rules:

> **Note:** `claim_type` and `status` are **separate fields** on a claim. Some strings (e.g., `partial_loss`, `total_loss`) are valid values for *both* fields — `status` describes where the claim is in its lifecycle, while `claim_type` describes the nature of the claim. The table below uses these strings as **claim_type** values (not statuses).

| Claim type | Transition additions | Optional dict guards on `claim` |
|------------|------------------------|----------------------------------|
| `bodily_injury` | `open` → `pending_info` (document ongoing treatment / info holds) | — |
| `partial_loss` | (none) | If key `repair_ready_for_settlement` is present and `False`, `open` → `settled` is rejected |
| `total_loss` | (none) | If key `total_loss_settlement_authorized` is present and `False`, `open` → `settled` is rejected |

For `partial_loss` / `total_loss`, those guard keys are persisted on the claim row as nullable integers (`repair_ready_for_settlement`, `total_loss_settlement_authorized`): **NULL** means unset (guard does not apply); **0** blocks `open` → `settled`. `ClaimRepository.update_claim_status` loads them into the dict passed to `validate_transition` and can set them with optional boolean kwargs (`repair_ready_for_settlement=`, `total_loss_settlement_authorized=`).

Unknown or missing `claim_type` uses **only** the base transition table; optional guard keys are ignored when absent so existing flows stay valid.

To add more variants, extend `_CLAIM_TYPE_TRANSITION_ADDITIONS` or `_type_specific_guard` in `src/claim_agent/db/state_machine.py`.

## Transition Guards

### Close Guard

Transition to `closed` requires one of:

- `payout_amount` is set (including 0 for administrative closure)
- `from_status` is `denied`, `duplicate`, or `failed` (no payout required)

This ensures closure is documented (settlement or denial).

### Reserve adequacy gate (`closed` / `settled`)

When transitioning **to** `closed` or `settled`, reserve adequacy may be enforced (same benchmark as `check_reserve_adequacy`: max of positive `estimated_damage` and positive `payout_amount`).

- **Configuration:** `RESERVE_CLOSE_SETTLE_ADEQUACY_GATE` (`off` \| `block` \| `warn`, default `warn`). See [Configuration](configuration.md#reserve-management).
- **`block`:** inadequate reserve rejects the transition unless `ClaimRepository.update_claim_status(..., skip_adequacy_check=True, role="supervisor"|"admin"|"executive")`.
- **`warn`:** transition is allowed; an extra audit row `reserve_adequacy_gate` records the inadequacy.
- **`off`:** no adequacy check.

`can_transition()` / `validate_transition()` accept `skip_adequacy_check` and `role` for parity with the repository. The claim dict passed in should include `reserve_amount` and `estimated_damage` (as loaded by `update_claim_status`).

## Bypass

- `actor_id="system"` or `force=True` skips validation when calling `validate_transition()` or `can_transition()` directly (for migrations, seeding, or tests)
- At the repository layer, use `skip_validation=True` on `update_claim_status()` to bypass the **entire** state machine: transition graph, close guard, claim-type guards (e.g. `open` → `settled` for partial loss), **and** the reserve adequacy gate for `closed` / `settled`. In `block` mode, an inadequate close/settle applied this way is not rejected and does not produce a `reserve_adequacy_gate` audit row (that event is only for allowed transitions that still record inadequacy or waiver). Prefer normal validation plus `skip_adequacy_check=True` with an elevated `role` when supervisors intentionally override the gate.

## REST API

For non-streaming JSON REST endpoints, `InvalidClaimTransitionError` is handled globally in the FastAPI app (`create_app`): responses use **409 Conflict** with JSON fields `detail`, `claim_id`, `from_status`, `to_status`, and `reason`. Route handlers avoid catching it inside broad `except Exception` blocks that would map errors to 400 or 503; Pydantic validation failures use `ValidationError` only so domain transition errors are not misclassified.

For streaming/SSE endpoints (e.g., `/api/chat`), a JSON 409 response cannot be issued mid-stream. Transition errors are surfaced as an SSE `data` event with `type: "error"`, `error_type: "InvalidClaimTransition"`, `status_code: 409`, and the same fields as the REST body (`detail`, `claim_id`, `from_status`, `to_status`, `reason`), followed by `type: "done"`.

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
