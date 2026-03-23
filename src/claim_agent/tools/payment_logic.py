"""Logic for recording claim disbursements (claim_payments) from tools."""

import json

from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.database import get_db_path
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.payment import ClaimPaymentCreate, PayeeType, PaymentMethod
from claim_agent.utils.sanitization import sanitize_payee

# Prefix for external_ref on claimant rental reimbursements so the claimant portal
# Rental tab can include them alongside rental_company direct-bill rows.
WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX = "workflow_rental:"


def record_claim_payment_impl(
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
    """Persist an authorized disbursement row.

    Uses ``ACTOR_WORKFLOW`` with authority checks skipped so settlement automation can record
    planned disbursements without per-agent limits (see configuration docs). API-created payments
    still enforce limits by actor/role.
    """
    try:
        pt = PayeeType(payee_type)
        pm = PaymentMethod(payment_method)
    except ValueError as e:
        return json.dumps(
            {
                "success": False,
                "error": str(e),
                "hint": "payee_type: claimant|repair_shop|rental_company|medical_provider|"
                "lienholder|attorney|other; payment_method: check|ach|wire|card|other",
            }
        )

    if amount <= 0:
        return json.dumps({"success": False, "error": "amount must be positive"})

    payee_clean = sanitize_payee(payee)
    if not payee_clean:
        return json.dumps({"success": False, "error": "payee is required"})

    payee_secondary_clean = payee_secondary or None

    sec_type = None
    if payee_secondary_type:
        try:
            sec_type = PayeeType(payee_secondary_type)
        except ValueError as e:
            return json.dumps({"success": False, "error": f"payee_secondary_type: {e}"})

    data = ClaimPaymentCreate(
        claim_id=claim_id,
        amount=float(amount),
        payee=payee_clean,
        payee_type=pt,
        payment_method=pm,
        check_number=(check_number.strip()[:100] if check_number else None),
        payee_secondary=payee_secondary_clean,
        payee_secondary_type=sec_type,
        external_ref=(external_ref.strip()[:200] if external_ref else None),
    )

    repo = PaymentRepository(db_path=get_db_path())
    try:
        payment_id = repo.create_payment(
            data,
            actor_id=ACTOR_WORKFLOW,
            role="adjuster",
            skip_authority_check=True,
        )
    except ClaimNotFoundError as e:
        return json.dumps({"success": False, "error": str(e)})

    row = repo.get_payment(payment_id)
    return json.dumps(
        {
            "success": True,
            "payment_id": payment_id,
            "payment": row,
        },
        default=str,
    )
