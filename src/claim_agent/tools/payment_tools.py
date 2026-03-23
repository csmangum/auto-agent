"""CrewAI tools for claim payment / disbursement ledger."""

from crewai.tools import tool

from claim_agent.tools.payment_logic import (
    WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX,
    record_claim_payment_impl,
)

_P = WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX

_RECORD_CLAIM_PAYMENT_DOC = f"""Create an authorized claim_payments row (disbursement ledger).

Recorded under the workflow actor with payment authority limits bypassed for automation.

Use after the distribution plan is clear: one call per payee/amount (e.g. shop labor deposit,
rental reimbursement, medical provider, settlement to claimant, two-party check with payee_secondary).

Args:
    claim_id: Claim ID.
    amount: Payment amount in dollars (must be > 0).
    payee: Primary payee name.
    payee_type: claimant | repair_shop | rental_company | medical_provider | lienholder | attorney | other
    payment_method: check | ach | wire | card | other
    check_number: Optional; usually set at issue time via API.
    payee_secondary: Optional second payee for two-party checks.
    payee_secondary_type: Payee type for secondary when applicable.
    external_ref: Optional idempotency key per claim (duplicate ref returns existing row).
        For loss-of-use reimbursement paid to the claimant (not the rental company),
        use a ref starting with {_P!r} (e.g. {_P}{{claim_id}})
        so the portal Rental tab can surface the payment.

Returns:
    JSON with success, payment_id, and payment record (or error).
"""


def _record_claim_payment(
    claim_id: str,
    amount: float,
    payee: str,
    payee_type: str,
    payment_method: str,
    check_number: str | None = None,
    payee_secondary: str | None = None,
    payee_secondary_type: str | None = None,
    external_ref: str | None = None,
) -> str:
    return record_claim_payment_impl(
        claim_id,
        amount,
        payee,
        payee_type,
        payment_method,
        check_number=check_number,
        payee_secondary=payee_secondary,
        payee_secondary_type=payee_secondary_type,
        external_ref=external_ref,
    )


_record_claim_payment.__doc__ = _RECORD_CLAIM_PAYMENT_DOC

record_claim_payment = tool("Record Claim Payment")(_record_claim_payment)
