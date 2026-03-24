"""Incoming webhook routes (e.g. repair status updates from shops)."""

import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from claim_agent.config.settings import get_webhook_config
from claim_agent.adapters.base import VALID_ERP_EVENT_TYPES
from claim_agent.db.constants import VALID_REPAIR_STATUSES
from claim_agent.db.database import get_db_path
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.db.repository import ClaimRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_webhook_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify HMAC-SHA256 signature. Secret is required for repair-status webhook."""
    if not secret or not secret.strip():
        return False  # Secret required; reject when unset
    if not signature_header or not signature_header.strip():
        return False
    if not signature_header.startswith("sha256="):
        return False
    received = signature_header[7:]
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


class RepairStatusWebhookPayload(BaseModel):
    """Payload for POST /webhooks/repair-status."""

    claim_id: str = Field(..., min_length=1, max_length=64)
    shop_id: str = Field(..., min_length=1, max_length=128)
    authorization_id: str | None = Field(default=None, max_length=64)
    status: str = Field(..., min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


def _claim_has_authorization(claim_id: str, shop_id: str, authorization_id: str | None) -> bool:
    """Check that the claim has a matching partial loss authorization."""
    from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output

    repo = ClaimRepository(db_path=get_db_path())
    runs = repo.get_workflow_runs(claim_id, limit=10)
    for run in runs:
        if run.get("claim_type") != "partial_loss":
            continue
        wf_output = run.get("workflow_output") or ""
        parsed = _parse_partial_loss_workflow_output(wf_output)
        if not parsed:
            continue
        wf_shop = str(parsed.get("shop_id", "")).strip()
        wf_auth = str(parsed.get("authorization_id", "")).strip()
        if shop_id and wf_shop and shop_id != wf_shop:
            continue
        if authorization_id and wf_auth and authorization_id != wf_auth:
            continue
        return True
    return False


@router.post("/repair-status")
async def repair_status_webhook(request: Request) -> Response:
    """Receive repair status updates from shops.

    Payload: claim_id, shop_id, authorization_id (optional), status, notes (optional).
    Status: received, disassembly, parts_ordered, repair, paint, reassembly, qa, ready, paused_supplement.
    Requests must include X-Webhook-Signature: sha256=<hex> (WEBHOOK_SECRET is required).
    """
    body = await request.body()
    config = get_webhook_config()
    if not _verify_webhook_signature(
        body,
        request.headers.get("X-Webhook-Signature"),
        config.get("secret") or "",
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing webhook signature"},
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid JSON: {e!s}"},
        )

    try:
        parsed = RepairStatusWebhookPayload(**payload)
    except ValidationError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid payload"},
        )

    if parsed.status not in VALID_REPAIR_STATUSES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Invalid status. Must be one of: {sorted(VALID_REPAIR_STATUSES)}",
            },
        )

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(parsed.claim_id)
    if claim is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Claim not found: {parsed.claim_id}"},
        )

    if claim.get("claim_type") != "partial_loss":
        return JSONResponse(
            status_code=400,
            content={"detail": "Repair status only applies to partial_loss claims"},
        )

    if not _claim_has_authorization(
        parsed.claim_id,
        parsed.shop_id,
        parsed.authorization_id,
    ):
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Claim has no matching repair authorization for this shop/authorization_id",
            },
        )

    status_repo = RepairStatusRepository(db_path=get_db_path())
    try:
        row_id = status_repo.insert_repair_status(
            claim_id=parsed.claim_id,
            shop_id=parsed.shop_id,
            status=parsed.status,
            authorization_id=parsed.authorization_id,
            notes=parsed.notes,
        )
    except Exception as e:
        logger.exception("Repair status insert failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to record repair status"},
        )

    return JSONResponse(
        status_code=200,
        content={"ok": True, "repair_status_id": row_id},
    )


# ---------------------------------------------------------------------------
# ERP inbound webhook (ERP → carrier)
# ---------------------------------------------------------------------------


class ERPWebhookPayload(BaseModel):
    """Payload for ``POST /webhooks/erp``.

    ERP systems POST signed events to this endpoint to notify the carrier of
    estimate approvals, parts delays, and supplement requests.  The signature
    scheme is the same HMAC-SHA256 pattern used by the repair-status webhook.

    event_type values
    -----------------
    - ``estimate_approved``  – ERP approved the repair estimate.
    - ``parts_delayed``      – Parts are delayed; repair timeline extended.
    - ``supplement_requested`` – Shop discovered additional damage needing authorization.

    Optional fields per event type
    -------------------------------
    - ``estimate_approved``: ``approved_amount`` (float).
    - ``parts_delayed``: ``delay_reason`` (str), ``expected_availability_date`` (str).
    - ``supplement_requested``: ``supplement_amount`` (float), ``description`` (str).
    """

    event_type: str = Field(..., min_length=1, max_length=64)
    claim_id: str = Field(..., min_length=1, max_length=64)
    shop_id: str = Field(..., min_length=1, max_length=128)
    erp_event_id: str = Field(..., min_length=1, max_length=128)
    occurred_at: str = Field(..., min_length=1, max_length=64)
    # event_type-specific optional fields
    approved_amount: float | None = Field(default=None)
    delay_reason: str | None = Field(default=None, max_length=1000)
    expected_availability_date: str | None = Field(default=None, max_length=64)
    supplement_amount: float | None = Field(default=None)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/erp")
async def erp_webhook(request: Request) -> Response:
    """Receive inbound events from repair/shop management systems (ERP).

    Payload: event_type, claim_id, shop_id, erp_event_id, occurred_at, and
    event-type-specific optional fields.

    Supported event types: estimate_approved, parts_delayed, supplement_requested.

    Requests must include ``X-Webhook-Signature: sha256=<hex>``
    (``WEBHOOK_SECRET`` is required).
    """
    body = await request.body()
    config = get_webhook_config()
    if not _verify_webhook_signature(
        body,
        request.headers.get("X-Webhook-Signature"),
        config.get("secret") or "",
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing webhook signature"},
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid JSON: {e!s}"},
        )

    try:
        parsed = ERPWebhookPayload(**payload)
    except ValidationError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid payload"},
        )

    if parsed.event_type not in VALID_ERP_EVENT_TYPES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Invalid event_type. Must be one of: {sorted(VALID_ERP_EVENT_TYPES)}"
                ),
            },
        )

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(parsed.claim_id)
    if claim is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Claim not found: {parsed.claim_id}"},
        )

    # Record the inbound ERP event as a repair status update when applicable
    if parsed.event_type == "estimate_approved":
        # Transition to 'repair' stage on approval if claim is a partial_loss
        if claim.get("claim_type") == "partial_loss":
            status_repo = RepairStatusRepository(db_path=get_db_path())
            try:
                status_repo.insert_repair_status(
                    claim_id=parsed.claim_id,
                    shop_id=parsed.shop_id,
                    status="repair",
                    notes=(
                        "ERP estimate approved"
                        + (
                            f"; amount={parsed.approved_amount}"
                            if parsed.approved_amount is not None
                            else ""
                        )
                        + f"; erp_event_id={parsed.erp_event_id}"
                    ),
                )
            except Exception as e:
                logger.exception(
                    "ERP webhook: failed to record repair status for estimate_approved: %s", e
                )

    elif parsed.event_type == "parts_delayed":
        if claim.get("claim_type") == "partial_loss":
            status_repo = RepairStatusRepository(db_path=get_db_path())
            try:
                note = f"ERP parts delayed; erp_event_id={parsed.erp_event_id}"
                if parsed.delay_reason:
                    note += f"; reason={parsed.delay_reason}"
                if parsed.expected_availability_date:
                    note += f"; eta={parsed.expected_availability_date}"
                status_repo.insert_repair_status(
                    claim_id=parsed.claim_id,
                    shop_id=parsed.shop_id,
                    status="parts_ordered",
                    notes=note,
                    pause_reason=parsed.delay_reason,
                )
            except Exception as e:
                logger.exception(
                    "ERP webhook: failed to record repair status for parts_delayed: %s", e
                )

    elif parsed.event_type == "supplement_requested":
        # Log supplement request; adjuster workflow handles approval
        logger.info(
            "ERP webhook: supplement_requested claim_id=%s shop_id=%s "
            "supplement_amount=%s erp_event_id=%s",
            parsed.claim_id,
            parsed.shop_id,
            parsed.supplement_amount,
            parsed.erp_event_id,
        )

    return JSONResponse(
        status_code=200,
        content={"ok": True, "event_type": parsed.event_type, "claim_id": parsed.claim_id},
    )
