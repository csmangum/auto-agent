"""Escalation handling: low-confidence routing and mid-workflow escalations."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from claim_agent.config.settings import (
    ESCALATION_SLA_HOURS_CRITICAL,
    ESCALATION_SLA_HOURS_HIGH,
    ESCALATION_SLA_HOURS_LOW,
    ESCALATION_SLA_HOURS_MEDIUM,
)
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.observability import get_logger
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.workflow.budget import _record_crew_llm_usage
from claim_agent.workflow.helpers import _combine_workflow_outputs

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = get_logger(__name__)


_KNOWN_PRIORITIES = frozenset({"critical", "high", "medium", "low"})


def _sla_hours_for_priority(priority: str) -> int:
    """Return SLA hours for the given escalation priority."""
    if priority not in _KNOWN_PRIORITIES:
        logger.warning(
            "Unknown escalation priority %r; using ESCALATION_SLA_HOURS_LOW",
            priority,
            extra={"known_priorities": list(_KNOWN_PRIORITIES)},
        )
    if priority in ("critical", "high"):
        return ESCALATION_SLA_HOURS_CRITICAL if priority == "critical" else ESCALATION_SLA_HOURS_HIGH
    if priority == "medium":
        return ESCALATION_SLA_HOURS_MEDIUM
    return ESCALATION_SLA_HOURS_LOW


def _build_low_confidence_escalation_details(
    router_confidence: float,
    confidence_threshold: float,
    claim_type: str,
    router_reasoning: str,
) -> str:
    """Build the JSON details string used by both persistence and response paths."""
    return json.dumps({
        "escalation_reasons": ["low_router_confidence"],
        "priority": "medium",
        "recommended_action": "Confirm routing classification. Router confidence below threshold.",
        "fraud_indicators": [],
        "router_confidence": router_confidence,
        "router_confidence_threshold": confidence_threshold,
        "router_claim_type": claim_type,
        "router_reasoning": router_reasoning,
    })


def _escalate_low_router_confidence(
    claim_id: str,
    claim_type: str,
    raw_output: str,
    router_confidence: float,
    confidence_threshold: float,
    router_reasoning: str,
    context: ClaimContext,
    workflow_logger: Any,
    workflow_start_time: float,
    actor_id: str,
) -> None:
    """Persist low router confidence escalation to DB.

    Low-confidence escalations are always medium priority; SLA hours come from
    ESCALATION_SLA_HOURS_MEDIUM (same as mid-workflow medium-priority escalations).
    """
    repo = context.repo
    metrics = context.metrics
    sla_hours = _sla_hours_for_priority("medium")
    details = _build_low_confidence_escalation_details(
        router_confidence, confidence_threshold, claim_type, router_reasoning,
    )
    repo.save_workflow_result(claim_id, claim_type, raw_output, details)
    repo.update_claim_status(
        claim_id, STATUS_NEEDS_REVIEW, claim_type=claim_type, details=details, actor_id=actor_id
    )
    due_at = (datetime.utcnow() + timedelta(hours=sla_hours)).strftime("%Y-%m-%d %H:%M:%S")
    repo.update_claim_review_metadata(
        claim_id,
        priority="medium",
        due_at=due_at,
        review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    workflow_duration = (time.time() - workflow_start_time) * 1000
    workflow_logger.log_event(
        "claim_escalated",
        reasons=["low_router_confidence"],
        priority="medium",
        duration_ms=workflow_duration,
    )
    _record_crew_llm_usage(claim_id=claim_id, llm=context.llm, metrics=metrics)
    metrics.end_claim(claim_id, status="escalated")
    record_claim_outcome(
        claim_id, "escalated", (time.time() - workflow_start_time)
    )
    metrics.log_claim_summary(claim_id)


def _escalate_low_router_confidence_response(
    claim_id: str,
    claim_type: str,
    raw_output: str,
    router_confidence: float,
    confidence_threshold: float,
    router_reasoning: str = "",
) -> dict:
    """Build response dict for low router confidence escalation."""
    details = _build_low_confidence_escalation_details(
        router_confidence, confidence_threshold, claim_type, router_reasoning,
    )
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": STATUS_NEEDS_REVIEW,
        "needs_review": True,
        "escalation_reasons": ["low_router_confidence"],
        "priority": "medium",
        "fraud_indicators": [],
        "router_output": raw_output,
        "workflow_output": details,
        "summary": f"Escalated: router confidence {router_confidence:.2f} below threshold {confidence_threshold}",
    }


def _handle_mid_workflow_escalation(
    e: MidWorkflowEscalation,
    *,
    claim_id: str,
    claim_type: str,
    raw_output: str,
    context: ClaimContext,
    workflow_logger: Any,
    workflow_start_time: float,
    prior_workflow_output: str | None = None,
    actor_id: str | None = None,
    stage: str | None = None,
    payout_amount: float | None = None,
    workflow_run_id: str | None = None,
) -> dict:
    """Build and return an escalation response for a MidWorkflowEscalation.

    When *stage* is provided (e.g. ``"settlement"``), the escalation details
    include that stage, the claim status is updated to ``STATUS_NEEDS_REVIEW``,
    and review metadata (priority / due-at) are persisted.  Without *stage*
    (primary crew escalation), only the workflow result is saved.

    Cleans up any checkpoints for *workflow_run_id* so that a future resume
    does not reuse stale cached outputs from a run that ended in escalation.
    """
    repo = context.repo
    metrics = context.metrics
    if workflow_run_id:
        repo.delete_task_checkpoints(claim_id, workflow_run_id)
    details_payload: dict[str, Any] = {
        "escalation": True,
        "mid_workflow": True,
        "reason": e.reason,
        "indicators": e.indicators,
        "priority": e.priority,
    }
    if stage is not None:
        details_payload["stage"] = stage

    escalation_details = json.dumps(details_payload)

    if stage is not None and prior_workflow_output is not None:
        saved_output = _combine_workflow_outputs(prior_workflow_output, escalation_details)
    else:
        saved_output = escalation_details

    repo.save_workflow_result(claim_id, claim_type, raw_output, saved_output)

    if stage is not None:
        current_claim = repo.get_claim(claim_id)
        current_status = current_claim.get("status") if current_claim else None
        if current_status != STATUS_NEEDS_REVIEW:
            repo.update_claim_status(
                claim_id,
                STATUS_NEEDS_REVIEW,
                claim_type=claim_type,
                details=escalation_details,
                payout_amount=payout_amount,
                actor_id=actor_id,
            )
            hours = _sla_hours_for_priority(e.priority)
            due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            repo.update_claim_review_metadata(
                claim_id,
                priority=e.priority,
                due_at=due_at,
                review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            )

    workflow_duration = (time.time() - workflow_start_time) * 1000
    workflow_logger.log_event(
        "claim_escalated",
        reasons=[e.reason],
        priority=e.priority,
        duration_ms=workflow_duration,
    )
    _record_crew_llm_usage(claim_id=claim_id, llm=context.llm, metrics=metrics)
    metrics.end_claim(claim_id, status="escalated")
    record_claim_outcome(
        claim_id, "escalated", (time.time() - workflow_start_time)
    )
    metrics.log_claim_summary(claim_id)

    summary = f"Escalated during {stage}: {e.reason}" if stage else f"Escalated mid-workflow: {e.reason}"
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": STATUS_NEEDS_REVIEW,
        "needs_review": True,
        "escalation_reasons": [e.reason],
        "priority": e.priority,
        "fraud_indicators": e.indicators,
        "router_output": raw_output,
        "workflow_output": saved_output,
        "workflow_run_id": workflow_run_id,
        "summary": summary,
    }
