"""Workflow orchestration for claim processing.

New code should import from this package rather than from
``claim_agent.crews.main_crew``.
"""

from claim_agent.exceptions import TokenBudgetExceeded
from claim_agent.workflow.budget import (
    _check_token_budget,
    _get_llm_usage_snapshot,
    _record_crew_llm_usage,
)
from claim_agent.workflow.claim_analysis import (
    _check_economic_total_loss,
    _filter_weak_fraud_indicators,
    _has_catastrophic_event_keywords,
    _has_catastrophic_keywords,
    _has_explicit_total_loss_keywords,
    _has_repairable_damage_keywords,
)
from claim_agent.workflow.duplicate_detection import (
    _check_for_duplicates,
    _damage_tags_overlap,
    _extract_damage_tags,
)
from claim_agent.workflow.escalation import (
    _escalate_low_router_confidence,
    _escalate_low_router_confidence_response,
    _handle_mid_workflow_escalation,
)
from claim_agent.workflow.helpers import (
    WORKFLOW_STAGES,
    _checkpoint_keys_to_invalidate,
    _combine_workflow_outputs,
    _extract_payout_from_workflow_result,
    _final_status,
    _kickoff_with_retry,
    _requires_settlement,
)
from claim_agent.workflow.routing import (
    _parse_claim_type,
    _parse_router_output,
    create_main_crew,
    create_router_crew,
)


def __getattr__(name: str):
    """Lazy import of orchestrator/stages to avoid circular import with crews.main_crew."""
    if name == "stages":
        import claim_agent.workflow.stages as stages
        return stages
    if name in ("_WorkflowCtx", "_normalize_claim_data", "run_claim_workflow"):
        from claim_agent.workflow.orchestrator import (
            _WorkflowCtx,
            _normalize_claim_data,
            run_claim_workflow,
        )
        return {"_WorkflowCtx": _WorkflowCtx, "_normalize_claim_data": _normalize_claim_data, "run_claim_workflow": run_claim_workflow}[name]
    if name in ("_stage_escalation_check", "_stage_router", "_stage_settlement", "_stage_workflow_crew"):
        from claim_agent.workflow.stages import (
            _stage_escalation_check,
            _stage_router,
            _stage_settlement,
            _stage_workflow_crew,
        )
        return {"_stage_escalation_check": _stage_escalation_check, "_stage_router": _stage_router, "_stage_settlement": _stage_settlement, "_stage_workflow_crew": _stage_workflow_crew}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "WORKFLOW_STAGES",
    "TokenBudgetExceeded",
    "_WorkflowCtx",
    "_check_economic_total_loss",
    "_check_for_duplicates",
    "_check_token_budget",
    "_checkpoint_keys_to_invalidate",
    "_combine_workflow_outputs",
    "_damage_tags_overlap",
    "_escalate_low_router_confidence",
    "_escalate_low_router_confidence_response",
    "_extract_damage_tags",
    "_extract_payout_from_workflow_result",
    "_filter_weak_fraud_indicators",
    "_final_status",
    "_get_llm_usage_snapshot",
    "_handle_mid_workflow_escalation",
    "_has_catastrophic_event_keywords",
    "_has_catastrophic_keywords",
    "_has_explicit_total_loss_keywords",
    "_has_repairable_damage_keywords",
    "_kickoff_with_retry",
    "_normalize_claim_data",
    "_parse_claim_type",
    "_parse_router_output",
    "_record_crew_llm_usage",
    "_requires_settlement",
    "_stage_escalation_check",
    "_stage_router",
    "_stage_settlement",
    "_stage_workflow_crew",
    "create_main_crew",
    "create_router_crew",
    "run_claim_workflow",
]
