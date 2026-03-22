"""Retention policy API routes: audit report, eligible-for-archive, eligible-for-purge."""

from typing import Any

from fastapi import APIRouter, Depends, Query

from claim_agent.api.deps import require_role
from claim_agent.config.settings import (
    get_audit_log_retention_years_after_purge,
    get_purge_after_archive_by_state,
    get_retention_by_state,
    get_retention_period_years,
    get_retention_purge_after_archive_years,
)
from claim_agent.context import ClaimContext
from claim_agent.db.database import get_db_path

router = APIRouter(prefix="/retention", tags=["retention"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


def get_claim_context() -> ClaimContext:
    """FastAPI dependency providing a per-request ClaimContext."""
    return ClaimContext.from_defaults(db_path=get_db_path())


@router.get("/report", dependencies=[RequireAdjuster])
def get_retention_report(
    ctx: ClaimContext = Depends(get_claim_context),
) -> dict[str, Any]:
    """Retention audit report: tier/status counts, litigation hold, pending archive/purge.

    Returns a snapshot of claim counts by retention tier and status, the number of claims
    pending archive or purge under the configured retention schedules, litigation hold
    counts, and audit log row statistics.
    """
    retention_years = get_retention_period_years()
    retention_by_state = get_retention_by_state()
    purge_after = get_retention_purge_after_archive_years()
    purge_by_state = get_purge_after_archive_by_state()
    audit_years = get_audit_log_retention_years_after_purge()

    return ctx.repo.retention_report(
        retention_years,
        retention_by_state=retention_by_state or None,
        purge_after_archive_years=purge_after,
        purge_by_state=purge_by_state or None,
        audit_log_retention_years_after_purge=audit_years,
    )


@router.get("/eligible-for-archive", dependencies=[RequireAdjuster])
def get_eligible_for_archive(
    include_litigation_hold: bool = Query(
        False,
        description="When true, include claims with a litigation hold in the results",
    ),
    ctx: ClaimContext = Depends(get_claim_context),
) -> dict[str, Any]:
    """List closed claims that are past their retention period and eligible to be archived.

    By default, claims with an active litigation hold are excluded because litigation hold
    suspends retention processing. Pass ``include_litigation_hold=true`` to override.

    State-specific retention periods from ``data/state_retention_periods.json`` are applied
    automatically when a claim's ``loss_state`` is set and a matching period is configured.
    """
    retention_years = get_retention_period_years()
    retention_by_state = get_retention_by_state()

    claims = ctx.repo.list_claims_for_retention(
        retention_years,
        retention_by_state=retention_by_state or None,
        exclude_litigation_hold=not include_litigation_hold,
    )

    _SAFE_FIELDS = (
        "id",
        "policy_number",
        "claim_type",
        "status",
        "loss_state",
        "retention_tier",
        "litigation_hold",
        "created_at",
        "archived_at",
    )
    safe_claims = [{k: c.get(k) for k in _SAFE_FIELDS} for c in claims]
    return {"total": len(safe_claims), "claims": safe_claims}


@router.get("/eligible-for-purge", dependencies=[RequireAdjuster])
def get_eligible_for_purge(
    include_litigation_hold: bool = Query(
        False,
        description="When true, include claims with a litigation hold in the results",
    ),
    ctx: ClaimContext = Depends(get_claim_context),
) -> dict[str, Any]:
    """List archived claims that are past the purge horizon and eligible to be purged.

    The purge horizon is defined as ``archived_at`` plus the configured purge-after-archive
    period (``RETENTION_PURGE_AFTER_ARCHIVE_YEARS``, default 2 years). State-specific
    overrides from ``data/state_retention_periods.json`` are applied automatically.

    By default, claims with an active litigation hold are excluded. Pass
    ``include_litigation_hold=true`` to override.
    """
    purge_after = get_retention_purge_after_archive_years()
    purge_by_state = get_purge_after_archive_by_state()

    claims = ctx.repo.list_claims_for_purge(
        purge_after,
        purge_by_state=purge_by_state or None,
        exclude_litigation_hold=not include_litigation_hold,
    )

    _SAFE_FIELDS = (
        "id",
        "policy_number",
        "claim_type",
        "status",
        "loss_state",
        "retention_tier",
        "litigation_hold",
        "archived_at",
        "purged_at",
    )
    safe_claims = [{k: c.get(k) for k in _SAFE_FIELDS} for c in claims]
    return {"total": len(safe_claims), "claims": safe_claims}
