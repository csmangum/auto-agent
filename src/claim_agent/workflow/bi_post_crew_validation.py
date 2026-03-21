"""Deterministic validation after Bodily Injury crew completes.

Re-runs PIP/MedPay exhaustion and minor court-approval rules so workflow
outcomes do not rely solely on LLM tool discipline.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from claim_agent.context import ClaimContext
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimType
from claim_agent.models.workflow_output import BIWorkflowOutput
from claim_agent.observability import get_logger
from claim_agent.rag.constants import DEFAULT_STATE
from claim_agent.tools.bodily_injury_logic import (
    check_minor_settlement_approval_impl,
    check_pip_medpay_exhaustion_impl,
)
from claim_agent.workflow.escalation import _handle_mid_workflow_escalation

logger = get_logger(__name__)


def extract_bi_workflow_output_from_crew_result(result: Any) -> BIWorkflowOutput | None:
    """Return parsed BIWorkflowOutput from the last crew task, if present."""
    tasks_output = getattr(result, "tasks_output", None)
    if not tasks_output or not isinstance(tasks_output, list):
        return None
    try:
        last_task = tasks_output[-1]
        output = getattr(last_task, "output", None)
    except (IndexError, TypeError, AttributeError):
        return None
    if output is None:
        return None
    if isinstance(output, BIWorkflowOutput):
        return output
    if isinstance(output, dict):
        try:
            return BIWorkflowOutput.model_validate(output)
        except ValidationError:
            return None
    return None


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _resolve_claimant_age(claim_data: dict[str, Any]) -> int | None:
    age = _coerce_int(claim_data.get("claimant_age"))
    if age is not None:
        return age
    parties = claim_data.get("parties") or []
    if not isinstance(parties, list):
        return None
    for p in parties:
        if isinstance(p, dict) and p.get("age") is not None:
            a = _coerce_int(p.get("age"))
            if a is not None:
                return a
    return None


def maybe_escalate_bodily_injury_post_crew(
    *,
    claim_type: str,
    claim_id: str,
    claim_data: dict[str, Any],
    workflow_result: Any,
    routed_output: str,
    raw_output: str,
    context: ClaimContext,
    workflow_start_time: float,
    workflow_run_id: str | None,
    actor_id: str | None,
) -> dict | None:
    """If BI gates fail deterministically, return escalation response; else None."""
    if claim_type != ClaimType.BODILY_INJURY.value:
        return None

    bio = extract_bi_workflow_output_from_crew_result(workflow_result)
    if bio is None:
        logger.info(
            "BI post-crew validation skipped: no BIWorkflowOutput on last task (claim_id=%s)",
            claim_id,
        )
        return None

    policy_number = str(claim_data.get("policy_number") or "").strip()
    loss_state = str(claim_data.get("loss_state") or DEFAULT_STATE).strip()
    medical_charges = float(bio.medical_charges) if bio.medical_charges is not None else 0.0

    pip_raw = check_pip_medpay_exhaustion_impl(
        claim_id=claim_id,
        policy_number=policy_number,
        medical_charges=medical_charges,
        loss_state=loss_state,
    )
    try:
        pip = json.loads(pip_raw)
    except json.JSONDecodeError:
        logger.warning("BI PIP check returned invalid JSON (claim_id=%s)", claim_id)
        return None
    if pip.get("error"):
        return None
    if pip.get("has_pip_medpay") and not pip.get("bi_settlement_allowed", True):
        return _handle_mid_workflow_escalation(
            MidWorkflowEscalation(
                reason="pip_medpay_not_exhausted",
                indicators=["pip_medpay_gate"],
                priority="high",
                claim_id=claim_id,
            ),
            claim_id=claim_id,
            claim_type=claim_type,
            raw_output=raw_output,
            context=context,
            workflow_logger=logger,
            workflow_start_time=workflow_start_time,
            prior_workflow_output=routed_output,
            actor_id=actor_id,
            stage="workflow",
            payout_amount=None,
            workflow_run_id=workflow_run_id,
        )

    claimant_age = _resolve_claimant_age(claim_data)
    incap = bool(claim_data.get("claimant_incapacitated", False))
    court_ok = bool(claim_data.get("minor_court_approval_obtained", False))

    minor_raw = check_minor_settlement_approval_impl(
        claim_id=claim_id,
        claimant_age=claimant_age,
        claimant_incapacitated=incap,
        loss_state=loss_state,
        court_approval_obtained=court_ok,
    )
    try:
        minor = json.loads(minor_raw)
    except json.JSONDecodeError:
        logger.warning("BI minor check returned invalid JSON (claim_id=%s)", claim_id)
        return None
    if minor.get("error"):
        return None
    if minor.get("court_approval_required") and not minor.get("court_approval_obtained", False):
        return _handle_mid_workflow_escalation(
            MidWorkflowEscalation(
                reason="minor_settlement_court_approval_required",
                indicators=["minor_court_approval_gate"],
                priority="high",
                claim_id=claim_id,
            ),
            claim_id=claim_id,
            claim_type=claim_type,
            raw_output=raw_output,
            context=context,
            workflow_logger=logger,
            workflow_start_time=workflow_start_time,
            prior_workflow_output=routed_output,
            actor_id=actor_id,
            stage="workflow",
            payout_amount=None,
            workflow_run_id=workflow_run_id,
        )

    return None
