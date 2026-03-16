"""Payments API routes: create, list, issue, clear, void."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.api.routes.claims import get_claim_context
from claim_agent.context import ClaimContext
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.exceptions import (
    ClaimNotFoundError,
    DomainValidationError,
    PaymentAuthorityError,
)
from claim_agent.models.payment import ClaimPayment, ClaimPaymentCreate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])
RequireAdjuster = require_role("adjuster", "supervisor", "admin")


def _get_payment_repo(ctx: ClaimContext) -> PaymentRepository:
    return PaymentRepository(db_path=getattr(ctx.repo, "_db_path", None))


@router.post(
    "/claims/{claim_id}/payments",
    response_model=ClaimPayment,
    status_code=201,
    dependencies=[Depends(RequireAdjuster)],
)
def create_payment(
    claim_id: str,
    body: ClaimPaymentCreate,
    ctx: ClaimContext = Depends(get_claim_context),
    auth: AuthContext = Depends(RequireAdjuster),
) -> ClaimPayment:
    """Create a new payment (authorized status). Respects payment authority limits."""
    if body.claim_id != claim_id:
        raise HTTPException(400, "claim_id in path and body must match")
    role = auth.role or "adjuster"
    actor_id = auth.actor_id or "anonymous"
    repo = _get_payment_repo(ctx)
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
    response_model=dict,
    dependencies=[Depends(RequireAdjuster)],
)
def list_payments(
    claim_id: str,
    ctx: ClaimContext = Depends(get_claim_context),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List payments for a claim."""
    repo = _get_payment_repo(ctx)
    payments, total = repo.get_payments_for_claim(
        claim_id, status=status, limit=limit, offset=offset
    )
    return {
        "payments": [ClaimPayment(**p) for p in payments],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/claims/{claim_id}/payments/{payment_id}",
    response_model=ClaimPayment,
    dependencies=[Depends(RequireAdjuster)],
)
def get_payment(
    claim_id: str,
    payment_id: int,
    ctx: ClaimContext = Depends(get_claim_context),
) -> ClaimPayment:
    """Get a single payment by ID."""
    repo = _get_payment_repo(ctx)
    payment = repo.get_payment(payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    return ClaimPayment(**payment)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/issue",
    response_model=ClaimPayment,
    dependencies=[Depends(RequireAdjuster)],
)
def issue_payment(
    claim_id: str,
    payment_id: int,
    ctx: ClaimContext = Depends(get_claim_context),
    auth: AuthContext = Depends(RequireAdjuster),
    check_number: Optional[str] = Query(None),
) -> ClaimPayment:
    """Transition payment from authorized to issued. Optionally set check_number."""
    actor_id = auth.actor_id or "anonymous"
    repo = _get_payment_repo(ctx)
    try:
        updated = repo.issue_payment(
            payment_id, check_number=check_number, actor_id=actor_id
        )
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    if updated["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    return ClaimPayment(**updated)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/clear",
    response_model=ClaimPayment,
    dependencies=[Depends(RequireAdjuster)],
)
def clear_payment(
    claim_id: str,
    payment_id: int,
    ctx: ClaimContext = Depends(get_claim_context),
    auth: AuthContext = Depends(RequireAdjuster),
) -> ClaimPayment:
    """Transition payment from issued to cleared."""
    actor_id = auth.actor_id or "anonymous"
    repo = _get_payment_repo(ctx)
    try:
        updated = repo.clear_payment(payment_id, actor_id=actor_id)
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    if updated["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    return ClaimPayment(**updated)


@router.post(
    "/claims/{claim_id}/payments/{payment_id}/void",
    response_model=ClaimPayment,
    dependencies=[Depends(RequireAdjuster)],
)
def void_payment(
    claim_id: str,
    payment_id: int,
    ctx: ClaimContext = Depends(get_claim_context),
    auth: AuthContext = Depends(RequireAdjuster),
    reason: Optional[str] = Query(None),
) -> ClaimPayment:
    """Void a payment (reversal workflow). Works from authorized or issued."""
    actor_id = auth.actor_id or "anonymous"
    repo = _get_payment_repo(ctx)
    try:
        updated = repo.void_payment(payment_id, reason=reason, actor_id=actor_id)
    except DomainValidationError as e:
        raise HTTPException(400, str(e))
    if updated["claim_id"] != claim_id:
        raise HTTPException(404, "Payment not found for this claim")
    return ClaimPayment(**updated)
