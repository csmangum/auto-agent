"""Payments API routes: create, list, issue, clear, void."""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.db.database import get_db_path
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.exceptions import (
    DomainValidationError,
    ClaimNotFoundError,
    PaymentAuthorityError,
    PaymentNotFoundError,
)
from claim_agent.models.payment import (
    ClaimPayment,
    ClaimPaymentCreate,
    ClaimPaymentList,
    IssuePaymentBody,
    PaymentStatus,
    VoidPaymentBody,
)

router = APIRouter(tags=["payments"])
RequireAdjuster = require_role("adjuster", "supervisor", "admin")


def _get_payment_repo() -> PaymentRepository:
    return PaymentRepository(db_path=get_db_path())


@router.post(
    "/claims/{claim_id}/payments",
    response_model=ClaimPayment,
    status_code=201,
)
def create_payment(
    claim_id: str,
    body: ClaimPaymentCreate,
    auth: AuthContext = RequireAdjuster,
) -> ClaimPayment:
    """Create a new payment (authorized status). Respects payment authority limits."""
    if body.claim_id != claim_id:
        raise HTTPException(400, "claim_id in path and body must match")
    role = auth.role or "adjuster"
    actor_id = auth.identity or "anonymous"
    repo = _get_payment_repo()
    try:
        payment_id = repo.create_payment(body, actor_id=actor_id, role=role)
    except ClaimNotFoundError as e:
        raise HTTPException(404, str(e))
    except PaymentAuthorityError as e:
        raise HTTPException(403, str(e))
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(500, "Payment created but not found")
    return ClaimPayment(**payment)


@router.get(
    "/claims/{claim_id}/payments",
    response_model=ClaimPaymentList,
    dependencies=[RequireAdjuster],
)
def list_payments(
    claim_id: str,
    status: Optional[PaymentStatus] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ClaimPaymentList:
    """List payments for a claim."""
    repo = _get_payment_repo()
    payments, total = repo.get_payments_for_claim(
        claim_id, status=status.value if status else None, limit=limit, offset=offset
    )
    return ClaimPaymentList(
        payments=[ClaimPayment(**p) for p in payments],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/claims/{claim_id}/payments/{payment_id}",
    response_model=ClaimPayment,
    dependencies=[RequireAdjuster],
)
def get_payment(
    claim_id: str,
    payment_id: int,
) -> ClaimPayment:
    """Get a single payment by ID."""
    repo = _get_payment_repo()
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    return ClaimPayment(**payment)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/issue",
    response_model=ClaimPayment,
)
def issue_payment(
    claim_id: str,
    payment_id: int,
    auth: AuthContext = RequireAdjuster,
    body: Optional[IssuePaymentBody] = Body(None),
) -> ClaimPayment:
    """Transition payment from authorized to issued. Optionally set check_number."""
    actor_id = auth.identity or "anonymous"
    check_number = body.check_number if body else None
    repo = _get_payment_repo()
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    try:
        updated = repo.issue_payment(
            payment_id, check_number=check_number, actor_id=actor_id
        )
    except PaymentNotFoundError as e:
        raise HTTPException(404, str(e))
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    return ClaimPayment(**updated)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/clear",
    response_model=ClaimPayment,
)
def clear_payment(
    claim_id: str,
    payment_id: int,
    auth: AuthContext = RequireAdjuster,
) -> ClaimPayment:
    """Transition payment from issued to cleared."""
    actor_id = auth.identity or "anonymous"
    repo = _get_payment_repo()
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    try:
        updated = repo.clear_payment(payment_id, actor_id=actor_id)
    except PaymentNotFoundError as e:
        raise HTTPException(404, str(e))
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    return ClaimPayment(**updated)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/void",
    response_model=ClaimPayment,
)
def void_payment(
    claim_id: str,
    payment_id: int,
    auth: AuthContext = RequireAdjuster,
    body: Optional[VoidPaymentBody] = Body(None),
) -> ClaimPayment:
    """Void a payment (reversal workflow). Works from authorized or issued."""
    actor_id = auth.identity or "anonymous"
    reason = body.reason if body else None
    repo = _get_payment_repo()
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    try:
        updated = repo.void_payment(payment_id, reason=reason, actor_id=actor_id)
    except PaymentNotFoundError as e:
        raise HTTPException(404, str(e))
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    return ClaimPayment(**updated)
