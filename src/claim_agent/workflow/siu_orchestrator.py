"""SIU investigation workflow orchestration: run_siu_investigation entry point.

Runs the SIU Investigation crew on claims under Special Investigations Unit
review. Performs document verification, records investigation, and case
management including state fraud bureau filing.

Error handling: When tools fail (adapter timeout, external service down), they
return error JSON instead of raising. Agents document failures in notes and
continue with partial results. If the crew itself fails, a failure note is added
to the SIU case and claim so adjusters are informed.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config import get_settings
from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.crews.siu_crew import create_siu_crew
from claim_agent.db.constants import SIU_INVESTIGATION_STATUSES
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.workflow_output import SIUInvestigationResult
from claim_agent.observability import get_logger, siu_workflow_scope
from claim_agent.tools.siu_logic import add_siu_investigation_note_impl
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def _parse_siu_result(result: Any) -> SIUInvestigationResult | None:
    """Extract SIUInvestigationResult from crew result.

    CrewAI may store output_pydantic in ``pydantic`` or ``output``.
    Returns None if parsing fails (fallback to raw string).
    """
    tasks_output = getattr(result, "tasks_output", None)
    if not tasks_output or not isinstance(tasks_output, list) or len(tasks_output) == 0:
        return None
    last_task = tasks_output[-1]
    last_output = getattr(last_task, "pydantic", None) or getattr(last_task, "output", None)
    if isinstance(last_output, SIUInvestigationResult):
        return last_output
    return None


def _derive_claim_state(
    claim: dict[str, Any], ctx: ClaimContext
) -> tuple[str, bool]:
    """Derive state jurisdiction for SIU reporting.

    Uses claim.state if present, else policy.state from policy adapter, else
    SIU_DEFAULT_STATE from settings. Returns (state, used_default: bool).
    State is used for fraud bureau filing and get_fraud_detection_guidance.
    """
    state = (claim.get("state") or "").strip()
    if state:
        return state, False
    policy_number = (claim.get("policy_number") or "").strip()
    if policy_number:
        try:
            policy = ctx.adapters.policy.get_policy(policy_number)
            if policy:
                pstate = (policy.get("state") or "").strip()
                if pstate:
                    return pstate, False
        except Exception:
            logger.warning(
                "Failed to look up policy state for %r; falling back to SIU_DEFAULT_STATE",
                policy_number,
                exc_info=True,
            )
    default_state = get_settings().siu_default_state or "California"
    return default_state, True


def run_siu_investigation(
    claim_id: str,
    *,
    llm: LLMProtocol | None = None,
    ctx: ClaimContext | None = None,
) -> dict[str, Any]:
    """Run the SIU investigation workflow for a claim.

    Claim must have status under_investigation or fraud_suspected.
    Creates SIU case via adapter if not already present (e.g., manual escalation).

    Args:
        claim_id: Claim ID.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.

    Returns:
        Dict with claim_id, siu_case_id, workflow_output, summary, and when
        Case Manager produced structured output: findings_summary, recommendation,
        case_status, state_report_filed, documents_verified, prior_claims_summary,
        tool_failures_noted. Falls back to raw workflow_output if parsing fails.

    Raises:
        ClaimNotFoundError: If claim does not exist.
        ValueError: If claim status is not under_investigation or fraud_suspected.
    """
    start_time = time.time()

    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=None)
    repo = ctx.repo

    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    status = claim.get("status")
    if status not in SIU_INVESTIGATION_STATUSES:
        raise ValueError(
            f"SIU investigation requires status under_investigation or fraud_suspected; got {status!r}"
        )

    siu_case_id = claim.get("siu_case_id")
    if not siu_case_id:
        case_id = ctx.adapters.siu.create_case(claim_id, indicators=[])
        repo.update_claim_siu_case_id(claim_id, case_id, actor_id="system")
        siu_case_id = case_id
        claim = repo.get_claim(claim_id) or claim

    # Derive state for SIU reporting: claim, policy, or SIU_DEFAULT_STATE
    state, state_from_default = _derive_claim_state(claim, ctx)
    if state_from_default:
        logger.info(
            "SIU state derived from default",
            extra={"claim_id": claim_id, "state": state},
        )

    claim_data_for_crew = {
        "id": claim.get("id"),
        "claim_id": claim.get("id"),
        "siu_case_id": siu_case_id,
        "policy_number": claim.get("policy_number"),
        "vin": claim.get("vin"),
        "vehicle_year": claim.get("vehicle_year"),
        "vehicle_make": claim.get("vehicle_make"),
        "vehicle_model": claim.get("vehicle_model"),
        "incident_date": claim.get("incident_date"),
        "incident_description": claim.get("incident_description"),
        "damage_description": claim.get("damage_description"),
        "status": claim.get("status"),
        "claim_type": claim.get("claim_type"),
        "state": state,
    }

    crew_inputs = {"claim_data": json.dumps(claim_data_for_crew)}

    _llm = llm or get_llm()
    siu_crew = create_siu_crew(llm=_llm)
    with siu_workflow_scope(claim_id=claim_id, case_id=siu_case_id):
        try:
            result = _kickoff_with_retry(siu_crew, crew_inputs)
        except Exception as e:
            failure_note = f"SIU workflow failed: {e!s}. Adjuster review required."
            try:
                add_siu_investigation_note_impl(
                    siu_case_id, failure_note, "general", ctx=ctx
                )
            except Exception as note_err:
                logger.warning("Failed to add SIU case failure note: %s", note_err)
            try:
                repo.add_note(claim_id, failure_note, actor_id="system")
            except Exception as note_err:
                logger.warning("Failed to add claim failure note: %s", note_err)
            raise

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )
    summary = workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output

    response: dict[str, Any] = {
        "claim_id": claim_id,
        "siu_case_id": siu_case_id,
        "workflow_output": workflow_output,
        "summary": summary,
    }
    if state_from_default:
        response["state_inferred"] = True
        response["state"] = state

    structured = _parse_siu_result(result)
    if structured is not None:
        response["findings_summary"] = structured.findings_summary
        response["recommendation"] = structured.recommendation
        response["case_status"] = structured.case_status
        response["state_report_filed"] = structured.state_report_filed
        response["documents_verified"] = structured.documents_verified
        response["prior_claims_summary"] = structured.prior_claims_summary
        response["tool_failures_noted"] = structured.tool_failures_noted

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "SIU investigation workflow completed",
        extra={"claim_id": claim_id, "elapsed_ms": elapsed_ms},
    )

    return response
