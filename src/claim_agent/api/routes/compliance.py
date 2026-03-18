"""Compliance API routes: fraud reporting, mandatory referrals, filing status."""

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from claim_agent.api.deps import require_role
from claim_agent.db.database import get_connection

RequireAdjuster = require_role("adjuster", "supervisor", "admin")

router = APIRouter(tags=["compliance"])


@router.get("/compliance/fraud-reporting", dependencies=[RequireAdjuster])
def get_fraud_reporting_compliance(
    state: str | None = Query(None, description="Filter by loss state"),
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
        if state:
            where_clauses.append("loss_state = :state")
            params["state"] = state.strip()

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

        claim_ids = [row[0] for row in claims]
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
                cid = row[0]
                if cid not in filings_by_claim:
                    filings_by_claim[cid] = []
                filings_by_claim[cid].append({
                    "filing_type": row[1],
                    "report_id": row[2],
                    "state": row[3],
                    "filed_at": row[4],
                })

        result = []
        for row in claims:
            claim_id = row[0]
            filings = filings_by_claim.get(claim_id, [])
            state_filed = any(f["filing_type"] == "state_bureau" for f in filings)
            nicb_filed = any(f["filing_type"] == "nicb" for f in filings)
            niss_filed = any(f["filing_type"] == "niss" for f in filings)
            result.append({
                "claim_id": claim_id,
                "status": row[3],
                "claim_type": row[4],
                "siu_case_id": row[5],
                "loss_state": row[6],
                "state_report_filed": state_filed,
                "nicb_filed": nicb_filed,
                "niss_filed": niss_filed,
                "filings": filings,
            })

        return {
            "claims": result,
            "total": len(result),
        }
