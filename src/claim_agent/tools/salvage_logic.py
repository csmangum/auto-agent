"""Salvage logic: value estimation, title transfer, disposition recording."""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from claim_agent.adapters.registry import get_nmvtis_adapter
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.db.repository import ClaimRepository

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext


logger = logging.getLogger(__name__)

_NMVTIS_MAX_ATTEMPTS = 3
_NMVTIS_BACKOFF_SEC = (0.05, 0.1, 0.2)
# Final salvage outcomes that warrant NMVTIS if not already filed
_NMVTIS_DISPOSITION_TRIGGERS = frozenset({
    "auction_complete",
    "owner_retained",
    "scrapped",
})
_DMV_REFERENCE_MAX_LEN = 256
_ALLOWED_SALVAGE_TITLE_STATUSES = frozenset({
    "pending",
    "dmv_reported",
    "certificate_issued",
})


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# Salvage value as percentage of ACV by damage type (higher damage = lower salvage)
_SALVAGE_PCT_HIGH_DAMAGE = 0.15  # flood, fire, frame
_SALVAGE_PCT_MEDIUM_DAMAGE = 0.20  # collision, rollover
_SALVAGE_PCT_LOW_DAMAGE = 0.25  # minor total loss


def get_salvage_value_impl(
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    damage_description: str = "",
    vehicle_value: float | None = None,
) -> str:
    """Estimate salvage value from vehicle data and damage.

    Uses vehicle_value when provided; otherwise estimates ACV from vehicle year and applies a damage-based salvage percentage.
    Salvage is typically 15-25% of ACV depending on damage severity.

    Returns JSON with:
    - salvage_value: float
    - vehicle_value_used: float
    - salvage_pct: float
    - disposition_recommendation: "auction" | "owner_retention" | "scrap"
    - reasoning: str
    """
    make = (make or "").strip()
    model = (model or "").strip()
    year_int = int(vehicle_year) if vehicle_year else 2020
    desc_lower = (damage_description or "").strip().lower()

    # Determine salvage percentage from damage type
    if any(kw in desc_lower for kw in ["flood", "fire", "submerged", "burned", "frame"]):
        pct = _SALVAGE_PCT_HIGH_DAMAGE
        reasoning = "High-severity damage (flood/fire/frame) reduces salvage value."
    elif any(kw in desc_lower for kw in ["totaled", "rollover", "collision", "destroyed"]):
        pct = _SALVAGE_PCT_MEDIUM_DAMAGE
        reasoning = "Moderate damage; typical salvage recovery for collision total loss."
    else:
        pct = _SALVAGE_PCT_LOW_DAMAGE
        reasoning = "Lower damage severity; higher salvage recovery potential."

    # Use provided vehicle_value or default estimate
    if vehicle_value is not None and isinstance(vehicle_value, (int, float)) and vehicle_value > 0:
        acv = float(vehicle_value)
        source = "workflow"
    else:
        current_year = _utc_now().year
        acv = max(5000, 15000 - (current_year - year_int) * 800)
        source = "estimated"

    salvage_value = round(acv * pct, 2)

    # Recommend disposition: scrap if very low value, owner_retention if policyholder may want
    if salvage_value < 500:
        disposition = "scrap"
        reasoning += " Very low salvage value; recommend scrap disposition."
    elif "owner" in desc_lower or "retain" in desc_lower:
        disposition = "owner_retention"
        reasoning += " Policyholder retention indicated; document salvage deduction."
    else:
        disposition = "auction"
        reasoning += " Auction recommended for standard total loss disposition."

    result = {
        "salvage_value": salvage_value,
        "vehicle_value_used": round(acv, 2),
        "salvage_pct": round(pct * 100, 1),
        "disposition_recommendation": disposition,
        "reasoning": reasoning,
        "source": source,
    }
    return json.dumps(result)


# NHTSA standard VINs are 17 uppercase alphanumeric characters.
# Letters I, O, and Q are excluded to avoid confusion with 1, 0, and 9.
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)


def _claim_vehicle_fields(
    claim: dict[str, Any],
) -> tuple[tuple[str, int, str, str] | None, str | None]:
    """Extract and validate vehicle fields required for NMVTIS submission.

    Returns ``(vehicle_tuple, None)`` on success or ``(None, skip_reason)``
    when a required field is absent or invalid so the caller can persist a
    proper *skipped* status instead of fabricating values.
    """
    vin = (claim.get("vin") or "").strip()
    if not vin:
        return None, "missing_vin"
    if not _VIN_RE.match(vin):
        return None, "invalid_vin"
    try:
        year = int(claim.get("vehicle_year") or 0)
    except (TypeError, ValueError):
        year = 0
    if year <= 0:
        return None, "missing_vehicle_year"
    make = str(claim.get("vehicle_make") or "").strip()
    if not make:
        return None, "missing_vehicle_make"
    model = str(claim.get("vehicle_model") or "").strip()
    if not model:
        return None, "missing_vehicle_model"
    return (vin, year, make, model), None


def _persist_nmvtis_fields(
    repo: ClaimRepository,
    claim_id: str,
    base_meta: dict[str, Any],
    nmvtis_patch: dict[str, Any],
) -> None:
    merged = {**base_meta, **nmvtis_patch}
    repo.update_claim_total_loss_metadata(claim_id, merged)


def _attempt_nmvtis_submission(
    repo: ClaimRepository,
    claim_id: str,
    *,
    trigger_event: str,
    dmv_reference: str | None,
    ctx: ClaimContext | None,
    force_resubmit: bool = False,
) -> dict[str, Any]:
    """Submit to NMVTIS with retries; merge result into total_loss_metadata. Returns API-facing fields."""
    claim = repo.get_claim(claim_id)
    if not claim:
        return {"nmvtis_error": "claim_not_found"}

    vehicle, skip_reason = _claim_vehicle_fields(claim)
    if not vehicle:
        patch = {
            "nmvtis_status": "skipped",
            "nmvtis_skip_reason": skip_reason,
            "nmvtis_last_trigger": trigger_event,
        }
        try:
            meta = repo.get_claim_total_loss_metadata(claim_id) or {}
            _persist_nmvtis_fields(repo, claim_id, meta, patch)
        except ClaimNotFoundError:
            return {"nmvtis_error": "claim_not_found"}
        return {
            "nmvtis_status": "skipped",
            "nmvtis_skip_reason": skip_reason,
        }

    vin, year, make, model = vehicle
    meta = repo.get_claim_total_loss_metadata(claim_id) or {}
    if (
        not force_resubmit
        and meta.get("nmvtis_reference")
        and meta.get("nmvtis_status") == "accepted"
    ):
        return {
            "nmvtis_skipped": True,
            "nmvtis_reference": meta.get("nmvtis_reference"),
            "nmvtis_status": "accepted",
        }

    adapter = ctx.adapters.nmvtis if ctx else get_nmvtis_adapter()
    submitted_at = _utc_now().isoformat().replace("+00:00", "Z")
    last_exc: BaseException | None = None

    try:
        for attempt in range(_NMVTIS_MAX_ATTEMPTS):
            try:
                raw = adapter.submit_total_loss_report(
                    claim_id=claim_id,
                    vin=vin,
                    vehicle_year=year,
                    make=make,
                    model=model,
                    loss_type="total_loss",
                    trigger_event=trigger_event,
                    dmv_reference=dmv_reference,
                )
                ref = raw.get("nmvtis_reference") or raw.get("reference")
                if not ref:
                    raise ValueError("NMVTIS adapter response missing nmvtis_reference")
                st = str(raw.get("status") or "accepted").strip().lower()
                success_patch = {
                    "nmvtis_reference": ref,
                    "nmvtis_status": st if st in ("accepted", "pending", "rejected") else "accepted",
                    "nmvtis_submitted_at": submitted_at,
                    "nmvtis_last_trigger": trigger_event,
                    "nmvtis_submission_attempts": attempt + 1,
                    "nmvtis_last_error": None,
                    "nmvtis_carrier_message": raw.get("message"),
                }
                fresh = repo.get_claim_total_loss_metadata(claim_id) or {}
                _persist_nmvtis_fields(repo, claim_id, fresh, success_patch)
                return {
                    "nmvtis_reference": ref,
                    "nmvtis_status": success_patch["nmvtis_status"],
                    "nmvtis_submitted_at": submitted_at,
                    "nmvtis_submission_attempts": attempt + 1,
                    **(
                        {"nmvtis_carrier_message": raw["message"]}
                        if raw.get("message")
                        else {}
                    ),
                }
            except NotImplementedError as e:
                err_patch = {
                    "nmvtis_status": "not_configured",
                    "nmvtis_last_error": str(e),
                    "nmvtis_last_trigger": trigger_event,
                    "nmvtis_submitted_at": submitted_at,
                }
                fresh = repo.get_claim_total_loss_metadata(claim_id) or {}
                _persist_nmvtis_fields(repo, claim_id, fresh, err_patch)
                logger.warning("NMVTIS adapter not configured: %s", e)
                return {
                    "nmvtis_status": "not_configured",
                    "nmvtis_coordination_error": (
                        "NMVTIS integration not configured; manual federal reporting may be required."
                    ),
                }
            except ClaimNotFoundError:
                raise
            except Exception as e:
                last_exc = e
                if attempt < _NMVTIS_MAX_ATTEMPTS - 1:
                    delay = _NMVTIS_BACKOFF_SEC[min(attempt, len(_NMVTIS_BACKOFF_SEC) - 1)]
                    time.sleep(delay)
                else:
                    break

        err_msg = str(last_exc) if last_exc else "unknown error"
        fail_patch = {
            "nmvtis_status": "failed",
            "nmvtis_last_error": err_msg,
            "nmvtis_last_trigger": trigger_event,
            "nmvtis_submitted_at": submitted_at,
            "nmvtis_submission_attempts": _NMVTIS_MAX_ATTEMPTS,
        }
        fresh = repo.get_claim_total_loss_metadata(claim_id) or {}
        _persist_nmvtis_fields(repo, claim_id, fresh, fail_patch)
        logger.warning("NMVTIS submission failed for %s after retries: %s", claim_id, err_msg)
        return {
            "nmvtis_status": "failed",
            "nmvtis_last_error": err_msg,
            "nmvtis_submission_attempts": _NMVTIS_MAX_ATTEMPTS,
        }
    except ClaimNotFoundError:
        return {"nmvtis_error": "claim_not_found"}


def initiate_title_transfer_impl(
    claim_id: str,
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    disposition_type: str,
) -> str:
    """Initiate DMV title transfer or salvage certificate (mock implementation).

    disposition_type: auction | owner_retention | scrap

    Returns JSON with transfer_id, status, dmv_reference.
    """
    valid_types = ("auction", "owner_retention", "scrap")
    if disposition_type not in valid_types:
        logger.warning(
            "Invalid disposition_type %r, defaulting to auction",
            disposition_type,
        )
        disposition_type = "auction"

    transfer_id = f"SALV-{claim_id or 'UNK'}-{_utc_now().strftime('%Y%m%d%H')}"
    dmv_ref = f"DMV-{vin[:8] if vin else 'N/A'}-{_utc_now().strftime('%Y%m%d')}"

    result = {
        "transfer_id": transfer_id,
        "claim_id": claim_id,
        "vin": vin or "",
        "vehicle_year": vehicle_year,
        "make": make or "",
        "model": model or "",
        "disposition_type": disposition_type,
        "dmv_reference": dmv_ref,
        "status": "initiated",
        "initiated_at": _utc_now().isoformat().replace("+00:00", "Z"),
        "message": f"Title transfer initiated for {disposition_type} disposition.",
    }
    return json.dumps(result)


def record_salvage_disposition_impl(
    claim_id: str,
    disposition_type: str,
    salvage_amount: float | None = None,
    status: str = "pending",
    notes: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Record salvage disposition outcome and auction/recovery status.

    Persists disposition fields to ``total_loss_metadata`` and triggers NMVTIS when the
    disposition reaches a terminal state (auction_complete, owner_retained, scrapped)
    if not already accepted.

    status: pending | auction_scheduled | auction_complete | owner_retained | scrapped
    """
    valid_statuses = ("pending", "auction_scheduled", "auction_complete", "owner_retained", "scrapped")
    if status not in valid_statuses:
        logger.warning(
            "Invalid status %r, defaulting to pending",
            status,
        )
        status = "pending"

    valid_types = ("auction", "owner_retention", "scrap")
    if disposition_type not in valid_types:
        logger.warning(
            "Invalid disposition_type %r, defaulting to auction",
            disposition_type,
        )
        disposition_type = "auction"

    recorded_at = _utc_now().isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = {
        "claim_id": claim_id,
        "disposition_type": disposition_type,
        "salvage_amount": salvage_amount,
        "status": status,
        "notes": notes or "",
        "recorded_at": recorded_at,
        "message": "Salvage disposition recorded.",
    }

    try:
        repo = ctx.repo if ctx else ClaimRepository()
        existing = repo.get_claim_total_loss_metadata(claim_id) or {}
        merged = {
            **existing,
            "salvage_disposition_type": disposition_type,
            "salvage_disposition_status": status,
            "salvage_amount_recovered": salvage_amount,
            "salvage_disposition_notes": notes or "",
            "salvage_disposition_recorded_at": recorded_at,
        }
        repo.update_claim_total_loss_metadata(claim_id, merged)

        if status in _NMVTIS_DISPOSITION_TRIGGERS:
            dmv_ref = merged.get("dmv_reference")
            if isinstance(dmv_ref, str):
                dmv_ref = dmv_ref.strip() or None
            else:
                dmv_ref = None
            nmvtis_out = _attempt_nmvtis_submission(
                repo,
                claim_id,
                trigger_event="salvage_disposition",
                dmv_reference=dmv_ref,
                ctx=ctx,
            )
            result.update(nmvtis_out)
    except ClaimNotFoundError as e:
        logger.warning("Salvage disposition persist failed (claim not found): %s", claim_id)
        result["error"] = str(e)
        return json.dumps(result)
    except Exception as e:
        logger.warning("Failed to persist salvage disposition for %s: %s", claim_id, e)
        result["error"] = str(e)
        return json.dumps(result)

    return json.dumps(result)


def record_dmv_salvage_report_impl(
    claim_id: str,
    dmv_reference: str,
    *,
    salvage_title_status: str = "dmv_reported",
    ctx: ClaimContext | None = None,
) -> str:
    """Record that salvage title was reported to state DMV.

    Updates claim total_loss_metadata with dmv_reference, reported_at,
    salvage_title_status: pending | dmv_reported | certificate_issued.

    On success, returns JSON with at least claim_id, dmv_reference, reported_at,
    salvage_title_status, message, plus NMVTIS-related keys when submission runs
    (see ``_attempt_nmvtis_submission``). On validation failure, missing claim,
    or other errors, returns JSON with exactly ``error`` (str) and ``claim_id``
    (str) so callers can branch without raising.
    """
    dmv_ref = (dmv_reference or "").strip()
    if not dmv_ref:
        return json.dumps({"error": "dmv_reference is required", "claim_id": claim_id})
    if len(dmv_ref) > _DMV_REFERENCE_MAX_LEN:
        return json.dumps(
            {
                "error": f"dmv_reference exceeds {_DMV_REFERENCE_MAX_LEN} characters",
                "claim_id": claim_id,
            }
        )
    st_norm = (salvage_title_status or "").strip()
    if st_norm not in _ALLOWED_SALVAGE_TITLE_STATUSES:
        return json.dumps(
            {
                "error": (
                    "salvage_title_status must be one of: "
                    + ", ".join(sorted(_ALLOWED_SALVAGE_TITLE_STATUSES))
                ),
                "claim_id": claim_id,
            }
        )
    dmv_reference = dmv_ref
    salvage_title_status = st_norm
    try:
        repo = ctx.repo if ctx else ClaimRepository()
        existing = repo.get_claim_total_loss_metadata(claim_id) or {}
        reported_at = _utc_now().isoformat().replace("+00:00", "Z")
        merged = {
            **existing,
            "dmv_reference": dmv_reference,
            "reported_at": reported_at,
            "salvage_title_status": salvage_title_status,
        }
        repo.update_claim_total_loss_metadata(claim_id, merged)
        result: dict[str, Any] = {
            "claim_id": claim_id,
            "dmv_reference": dmv_reference,
            "reported_at": reported_at,
            "salvage_title_status": salvage_title_status,
            "message": "DMV salvage report recorded.",
        }
        nmvtis_out = _attempt_nmvtis_submission(
            repo,
            claim_id,
            trigger_event="dmv_salvage_report",
            dmv_reference=dmv_reference,
            ctx=ctx,
        )
        result.update(nmvtis_out)
        return json.dumps(result)
    except ClaimNotFoundError as e:
        logger.warning("DMV salvage report failed (claim not found): %s", claim_id)
        return json.dumps({"error": str(e), "claim_id": claim_id})
    except Exception as e:
        logger.warning("Failed to record DMV salvage report for %s: %s", claim_id, e)
        return json.dumps({"error": str(e), "claim_id": claim_id})


def submit_nmvtis_report_impl(
    claim_id: str,
    *,
    force_resubmit: bool = False,
    ctx: ClaimContext | None = None,
) -> str:
    """Manually trigger or retry NMVTIS reporting for a total-loss claim.

    Reads DMV reference from existing ``total_loss_metadata`` when present.
    With ``force_resubmit=True``, submits again even if a prior submission was accepted
    (use sparingly; primarily for operator correction workflows).
    """
    try:
        repo = ctx.repo if ctx else ClaimRepository()
        meta = repo.get_claim_total_loss_metadata(claim_id) or {}
        dmv_ref = meta.get("dmv_reference")
        if isinstance(dmv_ref, str):
            dmv_ref = dmv_ref.strip() or None
        else:
            dmv_ref = None
        out = _attempt_nmvtis_submission(
            repo,
            claim_id,
            trigger_event="manual_resubmit",
            dmv_reference=dmv_ref,
            ctx=ctx,
            force_resubmit=force_resubmit,
        )
        payload = {"claim_id": claim_id, **out}
        return json.dumps(payload)
    except Exception as e:
        logger.warning("submit_nmvtis_report failed for %s: %s", claim_id, e)
        return json.dumps({"error": str(e), "claim_id": claim_id})
