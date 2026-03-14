"""SIU investigation logic: document verification, claimant history, state bureau filing."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def get_siu_case_details_impl(case_id: str, *, ctx: ClaimContext | None = None) -> str:
    """Retrieve SIU case details by case_id."""
    from claim_agent.adapters.registry import get_siu_adapter

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    try:
        case = adapter.get_case(case_id)
    except NotImplementedError:
        return json.dumps({"error": "SIU case lookup not implemented", "case_id": case_id})
    if case is None:
        return json.dumps({"error": "Case not found", "case_id": case_id})
    return json.dumps(case)


def add_siu_investigation_note_impl(
    case_id: str, note: str, category: str = "general", *, ctx: ClaimContext | None = None
) -> str:
    """Add an investigation note to an SIU case."""
    from claim_agent.adapters.registry import get_siu_adapter

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    try:
        ok = adapter.add_investigation_note(case_id, note, category)
    except NotImplementedError:
        return json.dumps({"success": False, "message": "SIU case notes not implemented"})
    return json.dumps({"success": ok, "case_id": case_id, "category": category})


def update_siu_case_status_impl(
    case_id: str, status: str, *, ctx: ClaimContext | None = None
) -> str:
    """Update SIU case status (open, investigating, referred, closed)."""
    from claim_agent.adapters.registry import get_siu_adapter

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    try:
        ok = adapter.update_case_status(case_id, status)
    except NotImplementedError:
        return json.dumps({"success": False, "message": "SIU case status update not implemented"})
    return json.dumps({"success": ok, "case_id": case_id, "status": status})


def verify_document_authenticity_impl(
    document_type: str,
    claim_id: str,
    document_summary: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Mock document verification for SIU investigation.

    In production this would integrate with document verification services.
    Returns a structured result indicating verification outcome.
    """
    # Mock: simulate verification based on document type
    doc_types = ("proof_of_loss", "repair_estimate", "id", "title", "registration", "photos")
    doc_lower = (document_type or "").strip().lower() or "unknown"
    if doc_lower not in doc_types:
        doc_lower = "other"

    # Deterministic mock: odd-length claim_id = pass, even = flag for review
    claim_id_clean = (claim_id or "").strip()
    mock_pass = len(claim_id_clean) % 2 == 1 if claim_id_clean else True

    result: dict[str, Any] = {
        "document_type": doc_lower,
        "claim_id": claim_id_clean,
        "verified": mock_pass,
        "confidence": "high" if mock_pass else "medium",
        "findings": [],
        "recommendation": "Document acceptable" if mock_pass else "Request original for verification",
    }
    if not mock_pass:
        result["findings"].append("Minor inconsistencies; recommend physical inspection")
    return json.dumps(result)


def check_claimant_investigation_history_impl(
    claim_id: str,
    vin: str = "",
    policy_number: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check claimant and vehicle history for prior fraud flags and investigations."""
    from claim_agent.db.repository import ClaimRepository

    repo = ctx.repo if ctx else ClaimRepository()
    result: dict[str, Any] = {
        "claim_id": claim_id,
        "prior_claims": [],
        "prior_fraud_flags": [],
        "prior_siu_cases": [],
        "risk_summary": "low",
    }

    try:
        claim = repo.get_claim(claim_id)
        vin = vin or (claim.get("vin") if claim else "") or ""
        policy_number = policy_number or (claim.get("policy_number") if claim else "") or ""
    except Exception:
        pass

    if vin:
        try:
            all_claims = repo.search_claims(vin=vin, incident_date=None)
            fraud_claims = [c for c in all_claims if c.get("status") in ("fraud_suspected", "fraud_confirmed")]
            siu_claims = [c for c in all_claims if c.get("siu_case_id") and c.get("id") != claim_id]
            result["prior_claims"] = [
                {"claim_id": c.get("id"), "status": c.get("status"), "incident_date": c.get("incident_date")}
                for c in all_claims
                if c.get("id") != claim_id
            ][:10]
            result["prior_fraud_flags"] = [c.get("id") for c in fraud_claims if c.get("id") != claim_id]
            result["prior_siu_cases"] = [c.get("siu_case_id") for c in siu_claims if c.get("siu_case_id")]

            if fraud_claims or siu_claims:
                result["risk_summary"] = "elevated"
            if len(fraud_claims) >= 2 or len(siu_claims) >= 1:
                result["risk_summary"] = "high"
        except Exception as e:
            logger.debug("check_claimant_investigation_history: %s", e)

    return json.dumps(result)


def file_fraud_report_state_bureau_impl(
    claim_id: str,
    case_id: str,
    state: str = "California",
    indicators: str = "[]",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """File a fraud report with the state insurance fraud bureau.

    Per state requirements (e.g., CA CDI, TX DFR, FL DIFS, NY FBU).
    Mock implementation returns confirmation.
    """
    import json as _json

    try:
        ind_list = _json.loads(indicators) if indicators else []
    except _json.JSONDecodeError:
        ind_list = []

    # Mock: simulate filing
    report_id = f"FRB-{state[:2].upper()}-{claim_id[-6:]}-MOCK"
    result: dict[str, Any] = {
        "success": True,
        "report_id": report_id,
        "claim_id": claim_id,
        "case_id": case_id,
        "state": state,
        "indicators_count": len(ind_list),
        "message": f"Fraud report filed with {state} fraud bureau (mock). Report ID: {report_id}",
    }
    return json.dumps(result)
