"""Compliance API routes: fraud reporting, mandatory referrals, filing status."""

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from claim_agent.api.deps import require_role
from claim_agent.db.database import get_connection
from claim_agent.rag.constants import normalize_state

RequireAdjuster = require_role("adjuster", "supervisor", "admin")

router = APIRouter(tags=["compliance"])

_CLAIM_COLS = ("id", "policy_number", "vin", "status", "claim_type", "siu_case_id", "loss_state", "created_at")
_FILING_COLS = ("claim_id", "filing_type", "report_id", "state", "filed_at")
_CANONICAL_TO_ABBREV = {"California": "CA", "Texas": "TX", "Florida": "FL", "New York": "NY", "Georgia": "GA"}


def _state_filter_values(state: str) -> tuple[str, ...]:
    """Return (canonical, abbrev) for DB matching; supports both storage formats."""
    canonical = normalize_state(state.strip())
    abbrev = _CANONICAL_TO_ABBREV.get(canonical)
    return (canonical, abbrev) if abbrev else (canonical,)


@router.get("/compliance/fraud-reporting", dependencies=[RequireAdjuster])
def get_fraud_reporting_compliance(
    state: str | None = Query(None, description="Filter by loss state (e.g. California or CA)"),
    limit: int = Query(100, ge=1, le=500),
):
    """Summary of claims with fraud indicators, SIU status, and filing compliance.

    Returns claims in fraud_suspected, under_investigation, or fraud_confirmed
    status with their fraud filing status (state bureau, NICB, NISS).
    """
    with get_connection() as conn:
        where_clauses = [
            "status IN ('fraud_suspected', 'under_investigation', 'fraud_confirmed')",
        ]
        params: dict[str, Any] = {"limit": limit}
        if state and state.strip():
            try:
                state_values = _state_filter_values(state)
            except ValueError:
                return {"claims": [], "total": 0}
            if len(state_values) == 2:
                where_clauses.append("loss_state IN (:state0, :state1)")
                params["state0"] = state_values[0]
                params["state1"] = state_values[1]
            else:
                where_clauses.append("loss_state = :state0")
                params["state0"] = state_values[0]

        where_sql = " AND ".join(where_clauses)
        claims = conn.execute(
            text(f"""
            SELECT id, policy_number, vin, status, claim_type, siu_case_id,
                   loss_state, created_at
            FROM claims
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit
            """),
            params,
        ).fetchall()

        claim_ids = [dict(zip(_CLAIM_COLS, row))["id"] for row in claims]
        filings_by_claim: dict[str, list[dict[str, Any]]] = {}
        if claim_ids:
            placeholders = ", ".join(f":id{i}" for i in range(len(claim_ids)))
            filings = conn.execute(
                text(f"""
                SELECT claim_id, filing_type, report_id, state, filed_at
                FROM fraud_report_filings
                WHERE claim_id IN ({placeholders})
                ORDER BY filed_at DESC
                """),
                {f"id{i}": cid for i, cid in enumerate(claim_ids)},
            ).fetchall()
            for row in filings:
                f = dict(zip(_FILING_COLS, row))
                cid = f["claim_id"]
                if cid not in filings_by_claim:
                    filings_by_claim[cid] = []
                filings_by_claim[cid].append({
                    "filing_type": f["filing_type"],
                    "report_id": f["report_id"],
                    "state": f["state"],
                    "filed_at": f["filed_at"],
                })

        result = []
        for row in claims:
            c = dict(zip(_CLAIM_COLS, row))
            claim_id = c["id"]
            filings = filings_by_claim.get(claim_id, [])
            state_filed = any(f["filing_type"] == "state_bureau" for f in filings)
            nicb_filed = any(f["filing_type"] == "nicb" for f in filings)
            niss_filed = any(f["filing_type"] == "niss" for f in filings)
            result.append({
                "claim_id": claim_id,
                "status": c["status"],
                "claim_type": c["claim_type"],
                "siu_case_id": c["siu_case_id"],
                "loss_state": c["loss_state"],
                "state_report_filed": state_filed,
                "nicb_filed": nicb_filed,
                "niss_filed": niss_filed,
                "filings": filings,
            })

        return {
            "claims": result,
            "total": len(result),
        }
