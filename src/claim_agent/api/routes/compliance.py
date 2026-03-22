"""Compliance API routes: fraud reporting, mandatory referrals, filing status."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from claim_agent.api.deps import require_role
from claim_agent.db.database import get_connection
from claim_agent.rag.constants import _STATE_ABBREV_TO_CANONICAL, normalize_state

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")

router = APIRouter(tags=["compliance"])

_CLAIM_COLS = ("id", "policy_number", "vin", "status", "claim_type", "siu_case_id", "loss_state", "created_at")
_FILING_COLS = ("claim_id", "filing_type", "report_id", "state", "filed_at")
_CANONICAL_TO_ABBREV = {v: k for k, v in _STATE_ABBREV_TO_CANONICAL.items()}


def _state_filter_values(state: str) -> tuple[str, ...]:
    """Return (canonical, abbrev) for DB matching; supports both storage formats."""
    canonical = normalize_state(state.strip())
    abbrev = _CANONICAL_TO_ABBREV.get(canonical)
    return (canonical, abbrev) if abbrev else (canonical,)


def _is_fraud_signal(claim: dict[str, Any]) -> bool:
    """Return True if the claim has a fraud-specific signal (claim_type or SIU case)."""
    return claim.get("claim_type") == "fraud" or claim.get("siu_case_id") is not None


def _required_filing_types_for_claim(claim: dict[str, Any]) -> list[str]:
    """Return mandatory filing types for a fraud-related claim.

    Rules engine:
    - fraud_suspected: state bureau filing required
    - under_investigation with fraud signal (claim_type='fraud' or siu_case_id set):
      state bureau filing required
    - fraud_confirmed: cross-carrier reporting required (state_bureau + NICB + NISS)

    Non-fraud under_investigation claims (e.g. coverage verification) have no
    fraud filing obligations and return an empty list.
    """
    status_norm = (claim.get("status") or "").strip().lower()
    if status_norm == "fraud_suspected":
        return ["state_bureau"]
    if status_norm == "under_investigation" and _is_fraud_signal(claim):
        return ["state_bureau"]
    if status_norm == "fraud_confirmed":
        return ["state_bureau", "nicb", "niss"]
    return []


@router.get("/compliance/fraud-reporting", dependencies=[RequireAdjuster])
def get_fraud_reporting_compliance(
    state: str | None = Query(None, description="Filter by loss state (e.g. California or CA)"),
    limit: int = Query(100, ge=1, le=500),
):
    """Summary of claims with fraud indicators, SIU status, and filing compliance.

    Returns claims in fraud_suspected or fraud_confirmed status, plus
    under_investigation claims that carry a fraud-specific signal
    (claim_type='fraud' or siu_case_id IS NOT NULL). Coverage-verification
    claims that are merely under_investigation are excluded so they are not
    incorrectly reported as non-compliant with fraud filing obligations.
    """
    with get_connection() as conn:
        where_clauses = [
            (
                "(status IN ('fraud_suspected', 'fraud_confirmed')"
                " OR (status = 'under_investigation'"
                " AND (claim_type = 'fraud' OR siu_case_id IS NOT NULL)))"
            ),
        ]
        params: dict[str, Any] = {"limit": limit}
        if state and state.strip():
            try:
                state_values = _state_filter_values(state)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
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
            required_filing_types = _required_filing_types_for_claim(c)
            filed_types = {f["filing_type"] for f in filings}
            missing_required_filings = [
                filing_type for filing_type in required_filing_types if filing_type not in filed_types
            ]
            result.append({
                "claim_id": claim_id,
                "status": c["status"],
                "claim_type": c["claim_type"],
                "siu_case_id": c["siu_case_id"],
                "loss_state": c["loss_state"],
                "state_report_filed": state_filed,
                "nicb_filed": nicb_filed,
                "niss_filed": niss_filed,
                "required_filing_types": required_filing_types,
                "missing_required_filings": missing_required_filings,
                "compliant": len(missing_required_filings) == 0,
                "filings": filings,
            })

        return {
            "claims": result,
            "total": len(result),
        }
