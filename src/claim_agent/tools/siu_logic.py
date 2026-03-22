"""SIU investigation logic: document verification, claimant history, state bureau filing."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import TYPE_CHECKING, Any

from claim_agent.compliance.fraud_report_templates import get_fraud_report_template
from claim_agent.db.repository import ClaimRepository
from claim_agent.utils.retry import RETRYABLE_EXCEPTIONS

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

GENERIC_ACCESS_DENIED = json.dumps({"error": "Access denied", "message": "Invalid claim or case for this operation"})

# Transient adapter errors (timeout, connection) - tools return error JSON instead of raising
_ADAPTER_RETRY_ATTEMPTS = 3


def _adapter_error_json(
    message: str,
    case_id: str | None = None,
    claim_id: str | None = None,
    retryable: bool = False,
) -> str:
    """Return structured error JSON for adapter failures so agents can document and continue."""
    payload: dict[str, Any] = {"error": message, "tool_failure": True}
    if case_id:
        payload["case_id"] = case_id
    if claim_id:
        payload["claim_id"] = claim_id
    if retryable:
        payload["retryable"] = True
    return json.dumps(payload)


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


def _is_empty_required_field_value(value: Any) -> bool:
    """Return True when a template-required field value should be treated as missing/empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def get_siu_case_details_impl(case_id: str, *, ctx: ClaimContext | None = None) -> str:
    """Retrieve SIU case details by case_id. Retries on transient failures (timeout, connection)."""
    err = _validate_siu_scope(case_id=case_id)
    if err:
        return err
    from claim_agent.adapters.registry import get_siu_adapter

    adapter = ctx.adapters.siu if ctx else get_siu_adapter()
    for attempt in range(_ADAPTER_RETRY_ATTEMPTS):
        try:
            case = adapter.get_case(case_id)
            if case is None:
                return json.dumps({"error": "Case not found", "case_id": case_id})
            return json.dumps(case)
        except NotImplementedError:
            return _adapter_error_json("SIU case lookup not implemented", case_id=case_id)
        except RETRYABLE_EXCEPTIONS as e:
            if attempt < _ADAPTER_RETRY_ATTEMPTS - 1:
                wait = 2**attempt  # 1s, 2s
                logger.warning(
                    "get_siu_case_details retry %d/%d: %s (wait %.0fs)",
                    attempt + 1,
                    _ADAPTER_RETRY_ATTEMPTS,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                return _adapter_error_json(
                    f"SIU case lookup failed after retries: {e!s}", case_id=case_id, retryable=True
                )
        except Exception as e:
            logger.warning("get_siu_case_details failed: %s", e, exc_info=True)
            return _adapter_error_json(f"SIU case lookup failed: {e!s}", case_id=case_id)
    # Defensive: unreachable when _ADAPTER_RETRY_ATTEMPTS >= 1; satisfies type checker
    return _adapter_error_json("SIU case lookup failed: no attempts made", case_id=case_id)


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
        return _adapter_error_json("SIU case notes not implemented", case_id=case_id)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("add_siu_investigation_note failed: %s", e)
        return _adapter_error_json(f"SIU note add failed: {e!s}", case_id=case_id, retryable=True)
    except Exception as e:
        logger.warning("add_siu_investigation_note failed: %s", e, exc_info=True)
        return _adapter_error_json(f"SIU note add failed: {e!s}", case_id=case_id)
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
        return _adapter_error_json("SIU case status update not implemented", case_id=case_id)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("update_siu_case_status failed: %s", e)
        return _adapter_error_json(f"SIU status update failed: {e!s}", case_id=case_id, retryable=True)
    except Exception as e:
        logger.warning("update_siu_case_status failed: %s", e, exc_info=True)
        return _adapter_error_json(f"SIU status update failed: {e!s}", case_id=case_id)
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
    try:
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
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("verify_document_authenticity failed: %s", e)
        return _adapter_error_json(
            f"Document verification failed: {e!s}", claim_id=claim_id, retryable=True
        )
    except Exception as e:
        logger.warning("verify_document_authenticity failed: %s", e, exc_info=True)
        return _adapter_error_json(f"Document verification failed: {e!s}", claim_id=claim_id)


def check_claimant_investigation_history_impl(
    claim_id: str,
    vin: str = "",
    policy_number: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check claimant and vehicle history for prior fraud flags and investigations.

    Uses ClaimRepository (local SQLite). Returns tool_failure JSON on repository
    failures for consistency with other SIU tools.
    """
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
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("check_claimant_investigation_history: get_claim failed: %s", e)
        return _adapter_error_json(
            f"Records lookup failed: {e!s}", claim_id=claim_id, retryable=True
        )
    except sqlite3.Error as e:
        logger.debug("check_claimant_investigation_history: get_claim failed: %s", e)
    except Exception as e:
        logger.warning("check_claimant_investigation_history: get_claim failed: %s", e, exc_info=True)
        return _adapter_error_json(f"Records lookup failed: {e!s}", claim_id=claim_id)

    try:
        if vin or policy_number:
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
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("check_claimant_investigation_history: search_claims failed: %s", e)
        return _adapter_error_json(
            f"Records lookup failed: {e!s}", claim_id=claim_id, retryable=True
        )
    except sqlite3.Error as e:
        logger.debug("check_claimant_investigation_history: search_claims failed: %s", e)
    except Exception as e:
        logger.warning("check_claimant_investigation_history: unexpected error: %s", e, exc_info=True)
        return _adapter_error_json(f"Records lookup failed: {e!s}", claim_id=claim_id)

    return json.dumps(result)


def file_fraud_report_state_bureau_impl(
    claim_id: str,
    case_id: str,
    state: str = "California",
    indicators: str = "[]",
    payload_json: str = "{}",
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

    template = get_fraud_report_template(state or "California")
    if not template:
        return json.dumps({
            "success": False,
            "error": f"Unsupported fraud report template state: {state or 'California'}",
            "validation_error": True,
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state or "California",
        })

    try:
        payload = json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError:
        return json.dumps({
            "success": False,
            "error": "Invalid payload_json: expected JSON object",
            "validation_error": True,
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state or "California",
        })
    if not isinstance(payload, dict):
        return json.dumps({
            "success": False,
            "error": "Invalid payload_json: expected JSON object",
            "validation_error": True,
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state or "California",
        })

    if "claim_id" not in payload:
        payload["claim_id"] = claim_id
    repo = ctx.repo if ctx else ClaimRepository()
    try:
        claim = repo.get_claim(claim_id)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("file_fraud_report_state_bureau: get_claim failed: %s", e)
        return _adapter_error_json(
            f"State bureau payload validation failed: {e!s}",
            case_id=case_id,
            claim_id=claim_id,
            retryable=True,
        )
    except Exception as e:
        logger.warning("file_fraud_report_state_bureau: get_claim failed: %s", e, exc_info=True)
        return _adapter_error_json(
            f"State bureau payload validation failed: {e!s}",
            case_id=case_id,
            claim_id=claim_id,
        )

    if claim:
        defaults = {
            "policy_number": claim.get("policy_number"),
            "vin": claim.get("vin"),
            "incident_date": claim.get("incident_date"),
            "estimated_loss": claim.get("estimated_damage"),
        }
        for key, value in defaults.items():
            if key not in payload and value not in (None, ""):
                payload[key] = value
        if "claimant_name" not in payload:
            claimant = repo.get_claim_party_by_type(claim_id, "claimant")
            if claimant and claimant.get("name"):
                payload["claimant_name"] = claimant.get("name")

    required_fields = template.get("required_fields", [])
    missing_fields: list[str] = []
    for field in required_fields:
        if _is_empty_required_field_value(payload.get(field)):
            missing_fields.append(field)

    if missing_fields:
        return json.dumps({
            "success": False,
            "error": "Fraud report payload validation failed",
            "validation_error": True,
            "claim_id": claim_id,
            "case_id": case_id,
            "state": template.get("state", state or "California"),
            "missing_required_fields": missing_fields,
            "required_fields": required_fields,
            "can_retry": True,
        })

    # Mock: simulate filing. In production this would call state bureau API.
    # try/except for RETRYABLE_EXCEPTIONS is for future adapter integration.
    state_code = (state or "California").strip()[:2].upper() or "CA"
    claim_suffix = (claim_id or "")[-6:] or "MOCK"
    try:
        report_id = f"FRB-{state_code}-{claim_suffix}-MOCK"
        result: dict[str, Any] = {
            "success": True,
            "report_id": report_id,
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state or "California",
            "indicators_count": len(ind_list),
            "validated_required_fields": required_fields,
            "message": f"Fraud report filed with {state or 'California'} fraud bureau (mock). Report ID: {report_id}",
        }
        _persist_fraud_filing(
            ctx, claim_id, "state_bureau", report_id,
            siu_case_id=case_id, state=state or "California", indicators_count=len(ind_list),
        )
        return json.dumps(result)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("file_fraud_report_state_bureau failed: %s", e)
        return _adapter_error_json(
            f"State bureau filing failed: {e!s}",
            case_id=case_id,
            claim_id=claim_id,
            retryable=True,
        )
    except Exception as e:
        logger.warning("file_fraud_report_state_bureau failed: %s", e, exc_info=True)
        return _adapter_error_json(
            f"State bureau filing failed: {e!s}",
            case_id=case_id,
            claim_id=claim_id,
        )


def _persist_fraud_filing(
    ctx: ClaimContext | None,
    claim_id: str,
    filing_type: str,
    report_id: str,
    *,
    siu_case_id: str | None = None,
    state: str | None = None,
    indicators_count: int = 0,
) -> None:
    """Persist fraud filing to fraud_report_filings for compliance audit."""
    try:
        repo = ctx.repo if ctx else ClaimRepository()
        repo.record_fraud_filing(
            claim_id=claim_id,
            filing_type=filing_type,
            report_id=report_id,
            siu_case_id=siu_case_id,
            state=state,
            filed_by="siu_crew",
            indicators_count=indicators_count,
        )
    except Exception as persist_err:
        logger.warning(
            "Failed to persist fraud filing for audit: %s",
            persist_err,
            extra={"claim_id": claim_id, "report_id": report_id, "filing_type": filing_type},
            exc_info=True,
        )


def file_nicb_report_impl(
    claim_id: str,
    case_id: str,
    report_type: str = "theft",
    indicators: str = "[]",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """File a report with NICB (National Insurance Crime Bureau).

    Required for theft, salvage, and certain fraud referrals per state law.
    Mock implementation returns confirmation and persists for audit.
    """
    err = _validate_siu_scope(claim_id=claim_id, case_id=case_id)
    if err:
        return err
    try:
        ind_list = json.loads(indicators) if indicators else []
    except json.JSONDecodeError:
        ind_list = []
    claim_suffix = (claim_id or "")[-6:] or "MOCK"
    try:
        report_id = f"NICB-{report_type.upper()[:6]}-{claim_suffix}-MOCK"
        result: dict[str, Any] = {
            "success": True,
            "report_id": report_id,
            "claim_id": claim_id,
            "case_id": case_id,
            "report_type": report_type,
            "indicators_count": len(ind_list),
            "message": f"NICB {report_type} report filed (mock). Report ID: {report_id}",
        }
        _persist_fraud_filing(
            ctx, claim_id, "nicb", report_id,
            siu_case_id=case_id, indicators_count=len(ind_list),
        )
        return json.dumps(result)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("file_nicb_report failed: %s", e)
        return _adapter_error_json(
            f"NICB filing failed: {e!s}", case_id=case_id, claim_id=claim_id, retryable=True,
        )
    except Exception as e:
        logger.warning("file_nicb_report failed: %s", e, exc_info=True)
        return _adapter_error_json(
            f"NICB filing failed: {e!s}", case_id=case_id, claim_id=claim_id,
        )


def file_niss_report_impl(
    claim_id: str,
    case_id: str,
    report_type: str = "fraud",
    indicators: str = "[]",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """File a report with NISS (National Insurance Special Investigation System).

    Required for certain fraud referrals and cross-carrier reporting.
    Mock implementation returns confirmation and persists for audit.
    """
    err = _validate_siu_scope(claim_id=claim_id, case_id=case_id)
    if err:
        return err
    try:
        ind_list = json.loads(indicators) if indicators else []
    except json.JSONDecodeError:
        ind_list = []
    claim_suffix = (claim_id or "")[-6:] or "MOCK"
    try:
        report_id = f"NISS-{report_type.upper()[:6]}-{claim_suffix}-MOCK"
        result: dict[str, Any] = {
            "success": True,
            "report_id": report_id,
            "claim_id": claim_id,
            "case_id": case_id,
            "report_type": report_type,
            "indicators_count": len(ind_list),
            "message": f"NISS {report_type} report filed (mock). Report ID: {report_id}",
        }
        _persist_fraud_filing(
            ctx, claim_id, "niss", report_id,
            siu_case_id=case_id, indicators_count=len(ind_list),
        )
        return json.dumps(result)
    except RETRYABLE_EXCEPTIONS as e:
        logger.warning("file_niss_report failed: %s", e)
        return _adapter_error_json(
            f"NISS filing failed: {e!s}", case_id=case_id, claim_id=claim_id, retryable=True,
        )
    except Exception as e:
        logger.warning("file_niss_report failed: %s", e, exc_info=True)
        return _adapter_error_json(
            f"NISS filing failed: {e!s}", case_id=case_id, claim_id=claim_id,
        )
