"""SIU investigation logic: document verification, claimant history, state bureau filing."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

GENERIC_ACCESS_DENIED = json.dumps({"error": "Access denied", "message": "Invalid claim or case for this operation"})


def _validate_siu_scope(claim_id: str | None = None, case_id: str | None = None) -> str | None:
    """Validate claim_id/case_id against SIU workflow scope. Returns error JSON string or None if valid."""
    scope = None
    try:
        from claim_agent.observability import get_siu_workflow_scope
        scope = get_siu_workflow_scope()
    except ImportError:
        return GENERIC_ACCESS_DENIED
    if not scope:
        return None
    if case_id is not None and (scope.get("case_id") or "").strip() != (case_id or "").strip():
        return GENERIC_ACCESS_DENIED
    if claim_id is not None and (scope.get("claim_id") or "").strip() != (claim_id or "").strip():
        return GENERIC_ACCESS_DENIED
    return None

VALID_SIU_CASE_STATUSES = frozenset({"open", "investigating", "referred", "closed"})
VALID_SIU_NOTE_CATEGORIES = frozenset(
    {"general", "document_review", "claimant_interview", "records_check", "findings"}
)


def get_siu_case_details_impl(case_id: str, *, ctx: ClaimContext | None = None) -> str:
    """Retrieve SIU case details by case_id."""
    err = _validate_siu_scope(case_id=case_id)
    if err:
        return err
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
    err = _validate_siu_scope(case_id=case_id)
    if err:
        return err
    from claim_agent.adapters.registry import get_siu_adapter

    category_lower = (category or "general").strip().lower()
    if category_lower not in VALID_SIU_NOTE_CATEGORIES:
        return json.dumps({
            "success": False,
            "message": f"Invalid category {category!r}; must be one of: {sorted(VALID_SIU_NOTE_CATEGORIES)}",
            "case_id": case_id,
        })

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    try:
        ok = adapter.add_investigation_note(case_id, note, category_lower)
    except NotImplementedError:
        return json.dumps({"success": False, "message": "SIU case notes not implemented"})
    return json.dumps({"success": ok, "case_id": case_id, "category": category_lower})


def update_siu_case_status_impl(
    case_id: str, status: str, *, ctx: ClaimContext | None = None
) -> str:
    """Update SIU case status (open, investigating, referred, closed)."""
    err = _validate_siu_scope(case_id=case_id)
    if err:
        return err
    from claim_agent.adapters.registry import get_siu_adapter

    status_lower = (status or "").strip().lower()
    if status_lower not in VALID_SIU_CASE_STATUSES:
        return json.dumps({
            "success": False,
            "message": f"Invalid status {status!r}; must be one of: {sorted(VALID_SIU_CASE_STATUSES)}",
            "case_id": case_id,
        })

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    try:
        ok = adapter.update_case_status(case_id, status_lower)
    except NotImplementedError:
        return json.dumps({"success": False, "message": "SIU case status update not implemented"})
    return json.dumps({"success": ok, "case_id": case_id, "status": status_lower})


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
    err = _validate_siu_scope(claim_id=claim_id)
    if err:
        return err
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
    err = _validate_siu_scope(claim_id=claim_id)
    if err:
        return err
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
        if not vin and not policy_number and claim:
            vin = (claim.get("vin") or "").strip()
            policy_number = (claim.get("policy_number") or "").strip()
    except (sqlite3.Error, OSError) as e:
        logger.debug("check_claimant_investigation_history: get_claim failed: %s", e)
    except Exception as e:
        logger.warning("check_claimant_investigation_history: unexpected get_claim error: %s", e, exc_info=True)

    if vin or policy_number:
        try:
            # Search by VIN and/or policy separately; merge to find prior claims on same vehicle or policy
            seen_ids: set[str] = set()
            all_claims: list[dict[str, Any]] = []
            if vin:
                for c in repo.search_claims(vin=vin, incident_date=None, policy_number=None):
                    if c.get("id") and c.get("id") not in seen_ids:
                        seen_ids.add(c["id"])
                        all_claims.append(c)
            if policy_number:
                for c in repo.search_claims(vin=None, incident_date=None, policy_number=policy_number):
                    if c.get("id") and c.get("id") not in seen_ids:
                        seen_ids.add(c["id"])
                        all_claims.append(c)
            fraud_claims = [c for c in all_claims if c.get("status") in ("fraud_suspected", "fraud_confirmed") and c.get("id") != claim_id]
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
        except (sqlite3.Error, OSError) as e:
            logger.debug("check_claimant_investigation_history: search_claims failed: %s", e)
        except Exception as e:
            logger.warning("check_claimant_investigation_history: unexpected error: %s", e, exc_info=True)

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
    err = _validate_siu_scope(claim_id=claim_id, case_id=case_id)
    if err:
        return err
    try:
        ind_list = json.loads(indicators) if indicators else []
    except json.JSONDecodeError:
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
