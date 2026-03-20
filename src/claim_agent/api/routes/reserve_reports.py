"""Actuarial / IBNR reserve reporting (aggregate, development export, adequacy summary)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from claim_agent.api.deps import require_role
from claim_agent.api.routes.claims import get_claim_context
from claim_agent.context import ClaimContext
from claim_agent.db.reserve_reporting import (
    Granularity,
    aggregate_reserves_by_period,
    reserve_adequacy_summary,
    reserve_development_rows,
    reserve_development_triangle,
)

router = APIRouter(tags=["reserve-reports"])

RequireSupervisor = require_role("supervisor", "admin", "executive")


@router.get("/reports/reserves/by-period", dependencies=[RequireSupervisor])
def get_reserve_report_by_period(
    date_from: date | None = Query(
        None,
        description="Inclusive start (ISO date). Default: ~12 months ago.",
    ),
    date_to: date | None = Query(
        None,
        description="Exclusive end (ISO date). Default: tomorrow.",
    ),
    granularity: Granularity = Query(
        "month",
        description="Calendar grouping: month or quarter (based on reserve_history.created_at).",
    ),
    claim_type: str | None = Query(None, description="Filter to a single claim_type."),
    status: str | None = Query(
        None,
        description="Comma-separated claim statuses (e.g. open,closed).",
    ),
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Aggregate reserve movements by month or quarter (joined to current claim dimensions)."""
    return aggregate_reserves_by_period(
        db_path=ctx.repo.db_path,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        granularity=granularity,
        claim_type=claim_type,
        status=status,
    )


@router.get("/reports/reserves/development", dependencies=[RequireSupervisor])
def get_reserve_development_export(
    date_from: date | None = Query(None, description="Inclusive start (ISO date). Default: ~12 months ago."),
    date_to: date | None = Query(None, description="Exclusive end (ISO date). Default: tomorrow."),
    claim_type: str | None = Query(None),
    status: str | None = Query(None, description="Comma-separated statuses."),
    limit: int = Query(500, ge=1, le=5000, description="Page size (max 5000)."),
    offset: int = Query(0, ge=0),
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Paginated reserve history joined to claim fields (valuation vs accident lag)."""
    rows, total = reserve_development_rows(
        db_path=ctx.repo.db_path,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        claim_type=claim_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
    }


@router.get("/reports/reserves/triangle", dependencies=[RequireSupervisor])
def get_reserve_development_triangle(
    date_from: date | None = Query(None, description="Inclusive start (ISO date). Default: ~12 months ago."),
    date_to: date | None = Query(None, description="Exclusive end (ISO date). Default: tomorrow."),
    claim_type: str | None = Query(None),
    status: str | None = Query(None),
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Bucketed net movements by accident year × development month (IBNR-style export)."""
    return reserve_development_triangle(
        db_path=ctx.repo.db_path,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        claim_type=claim_type,
        status=status,
    )


@router.get("/reports/reserves/adequacy-summary", dependencies=[RequireSupervisor])
def get_reserve_adequacy_aggregate(
    claim_type: str | None = Query(None),
    status: str | None = Query(None, description="Comma-separated statuses."),
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Portfolio-level adequacy counts (same rules as per-claim adequacy endpoint)."""
    return reserve_adequacy_summary(
        db_path=ctx.repo.db_path,
        claim_type=claim_type,
        status=status,
    )
