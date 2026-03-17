"""Incoming webhook routes (e.g. repair status updates from shops)."""

import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from claim_agent.config.settings import get_webhook_config
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
