"""Individual workflow stage functions.

Each stage receives a ``_WorkflowCtx`` (defined in orchestrator) and returns
either ``None`` (proceed to next stage) or a response dict (early return).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from claim_agent.config.settings import get_router_config
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.crews.settlement_crew import create_settlement_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimType, EscalationOutput
from claim_agent.notifications.webhook import dispatch_repair_authorized
from claim_agent.observability import get_logger
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.tools.escalation_logic import (
    evaluate_escalation_impl,
    normalize_claim_type,
    validate_router_classification_impl,
)
from claim_agent.workflow.budget import _check_token_budget, _record_crew_llm_usage
from claim_agent.workflow.escalation import (
    _escalate_low_router_confidence,
    _escalate_low_router_confidence_response,
    _handle_mid_workflow_escalation,
    _sla_hours_for_priority,
)
from claim_agent.workflow.helpers import (
    _combine_workflow_outputs,
    _extract_payout_from_workflow_result,
    _kickoff_with_retry,
    _requires_settlement,
)
from claim_agent.workflow.routing import create_router_crew, _parse_router_output

if TYPE_CHECKING:
    from claim_agent.workflow.orchestrator import _WorkflowCtx

logger = get_logger(__name__)


def _stage_router(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the router classification stage.

    Returns an early-return response dict when the router escalates,
    otherwise populates ``ctx.claim_type``, ``ctx.router_confidence``,
    ``ctx.router_reasoning``, and ``ctx.raw_output`` and returns ``None``.
    """
    if "router" in ctx.checkpoints:
        try:
            router_cp = json.loads(ctx.checkpoints["router"])
            ctx.claim_type = router_cp["claim_type"]
            ctx.router_confidence = router_cp["router_confidence"]
            ctx.router_reasoning = router_cp["router_reasoning"]
            ctx.raw_output = router_cp["raw_output"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Failed to restore router from checkpoint; discarding and re-running stage",
                extra={"claim_id": ctx.claim_id},
                exc_info=exc,
            )
            ctx.checkpoints.pop("router", None)
        else:
            logger.set_claim_type(ctx.claim_type)
            logger.info("Restored router from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    logger.log_event("router_started", step="classification")
    router_start = time.time()

    router_crew = create_router_crew(ctx.llm)
    result = _kickoff_with_retry(router_crew, ctx.inputs)

    router_latency = (time.time() - router_start) * 1000
    ctx.raw_output = str(
        getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    )
    ctx.claim_type, ctx.router_confidence, ctx.router_reasoning = _parse_router_output(
        result, ctx.raw_output
    )

    logger.set_claim_type(ctx.claim_type)
    logger.log_event(
        "router_completed",
        claim_type=ctx.claim_type,
        confidence=ctx.router_confidence,
        latency_ms=router_latency,
    )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)

    router_config = get_router_config()
    confidence_threshold = router_config["confidence_threshold"]
    validation_enabled = router_config.get("validation_enabled", False)

    if ctx.router_confidence < confidence_threshold:
        if validation_enabled:
            try:
                val_json = validate_router_classification_impl(
                    ctx.claim_data_with_id,
                    ctx.claim_type,
                    ctx.router_confidence,
                    ctx.router_reasoning,
                    metrics=ctx.metrics,
                    claim_id=ctx.claim_id,
                )
                val_data = json.loads(val_json)
                val_claim_type = normalize_claim_type(val_data.get("claim_type", ctx.claim_type))
                val_confidence = max(0.0, min(1.0, float(val_data.get("confidence", 0))))
                val_agrees = val_data.get("validation_agrees", True)
                if val_confidence >= confidence_threshold:
                    if not val_agrees:
                        logger.log_event(
                            "router_reclassified",
                            original_claim_type=ctx.claim_type,
                            final_claim_type=val_claim_type,
                            validation_confidence=val_confidence,
                        )
                    ctx.claim_type = val_claim_type
                    ctx.router_confidence = val_confidence
                    ctx.router_reasoning = val_data.get("reasoning", ctx.router_reasoning)
                    logger.set_claim_type(ctx.claim_type)
                    try:
                        original_router_output = json.loads(ctx.raw_output)
                    except (TypeError, ValueError):
                        original_router_output = ctx.raw_output
                    ctx.raw_output = json.dumps({
                        "original_router_output": original_router_output,
                        "validation": val_data,
                    })
                    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
                else:
                    _escalate_low_router_confidence(
                        ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                        confidence_threshold, ctx.router_reasoning,
                        ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                        ctx.actor_id,
                    )
                    return _escalate_low_router_confidence_response(
                        ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                        confidence_threshold, router_reasoning=ctx.router_reasoning,
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("Router validation parse failed: %s", e)
                _escalate_low_router_confidence(
                    ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                    confidence_threshold, ctx.router_reasoning,
                    ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                    ctx.actor_id,
                )
                return _escalate_low_router_confidence_response(
                    ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                    confidence_threshold, router_reasoning=ctx.router_reasoning,
                )
        else:
            _escalate_low_router_confidence(
                ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                confidence_threshold, ctx.router_reasoning,
                ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                ctx.actor_id,
            )
            return _escalate_low_router_confidence_response(
                ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                confidence_threshold, router_reasoning=ctx.router_reasoning,
            )

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, "router",
        json.dumps({
            "claim_type": ctx.claim_type,
            "router_confidence": ctx.router_confidence,
            "router_reasoning": ctx.router_reasoning,
            "raw_output": ctx.raw_output,
        }),
    )
    return None


def _stage_escalation_check(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the pre-workflow escalation check.

    Returns an early-return response dict when the claim is escalated,
    otherwise returns ``None``.
    """
    if "escalation_check" in ctx.checkpoints:
        logger.info("Restored escalation_check from checkpoint", extra={"claim_id": ctx.claim_id})
        return None

    if ctx.claim_type != ClaimType.FRAUD.value:
        escalation_json = evaluate_escalation_impl(
            ctx.claim_data,
            ctx.raw_output,
            similarity_score=ctx.similarity_score_for_escalation,
            payout_amount=None,
            router_confidence=ctx.router_confidence,
        )
        escalation_result = json.loads(escalation_json)
        if escalation_result.get("needs_review"):
            reasons = escalation_result.get("escalation_reasons", [])
            priority = escalation_result.get("priority", "low")
            recommended_action = escalation_result.get("recommended_action", "")
            fraud_indicators = escalation_result.get("fraud_indicators", [])
            escalation_output = EscalationOutput(
                claim_id=ctx.claim_id,
                needs_review=True,
                escalation_reasons=reasons,
                priority=priority,
                recommended_action=recommended_action,
                fraud_indicators=fraud_indicators,
            )
            details = json.dumps({
                "escalation_reasons": reasons,
                "priority": priority,
                "recommended_action": recommended_action,
                "fraud_indicators": fraud_indicators,
            })
            ctx.repo.save_workflow_result(ctx.claim_id, ctx.claim_type, ctx.raw_output, details)
            # Avoid overwriting review metadata / creating duplicate status-change events
            # when a resumed/retried workflow still results in needs_review.
            current_claim = ctx.repo.get_claim(ctx.claim_id)
            current_status = current_claim.get("status") if current_claim else None
            if current_status != STATUS_NEEDS_REVIEW:
                ctx.repo.update_claim_status(
                    ctx.claim_id, STATUS_NEEDS_REVIEW, claim_type=ctx.claim_type,
                    details=details, actor_id=ctx.actor_id,
                )
                hours = _sla_hours_for_priority(priority)
                due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                ctx.repo.update_claim_review_metadata(
                    ctx.claim_id, priority=priority, due_at=due_at,
                    review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                )

            workflow_duration = (time.time() - ctx.workflow_start_time) * 1000
            logger.log_event(
                "claim_escalated", reasons=reasons, priority=priority,
                duration_ms=workflow_duration,
            )
            _record_crew_llm_usage(claim_id=ctx.claim_id, llm=ctx.llm, metrics=ctx.metrics)
            ctx.metrics.end_claim(ctx.claim_id, status="escalated")
            record_claim_outcome(
                ctx.claim_id, "escalated", (time.time() - ctx.workflow_start_time)
            )
            ctx.metrics.log_claim_summary(ctx.claim_id)

            return {
                **escalation_output.model_dump(),
                "claim_type": ctx.claim_type,
                "status": STATUS_NEEDS_REVIEW,
                "router_output": ctx.raw_output,
                "workflow_output": details,
                "workflow_run_id": ctx.workflow_run_id,
                "summary": f"Escalated for review: {', '.join(reasons)}",
            }

    ctx.repo.save_task_checkpoint(ctx.claim_id, ctx.workflow_run_id, "escalation_check", "{}")
    return None


def _dispatch_repair_authorization_webhook(workflow_output: str, log: Any) -> None:
    """Best-effort dispatch of repair.authorized webhook from workflow output.

    Parses the workflow output for authorization data (authorization_id,
    shop_id, etc.) and fires the webhook if found.
    """
    try:
        data = json.loads(workflow_output)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(data, dict):
        return
    authorization_id = data.get("authorization_id")
    if not authorization_id:
        return
    try:
        dispatch_repair_authorized(
            claim_id=data.get("claim_id", ""),
            shop_id=data.get("shop_id", ""),
            shop_name=data.get("shop_name", ""),
            shop_phone=data.get("shop_phone", ""),
            authorized_amount=float(data.get("authorized_amount", 0) or 0),
            authorization_id=authorization_id,
            shop_webhook_url=data.get("shop_webhook_url"),
        )
    except Exception as e:
        log.warning("Repair authorization webhook dispatch failed (best-effort): %s", e)


def _stage_workflow_crew(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the primary workflow crew.

    Populates ``ctx.workflow_output`` and ``ctx.extracted_payout``.
    Returns an early-return response dict on mid-workflow escalation.
    """
    workflow_stage_key = f"workflow:{ctx.claim_type}"

    if workflow_stage_key in ctx.checkpoints:
        try:
            wf_cp = json.loads(ctx.checkpoints[workflow_stage_key])
            if not isinstance(wf_cp, dict):
                raise ValueError("workflow checkpoint is not a JSON object")
            ctx.workflow_output = wf_cp["workflow_output"]
            ctx.extracted_payout = wf_cp.get("extracted_payout")
            if ctx.extracted_payout is not None:
                ctx.claim_data_with_id["payout_amount"] = ctx.extracted_payout
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore %s from checkpoint; invalidating and re-running stage: %s",
                workflow_stage_key,
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop(workflow_stage_key, None)
        else:
            logger.info("Restored %s from checkpoint", workflow_stage_key, extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    logger.log_event("crew_started", crew=ctx.claim_type)
    crew_start = time.time()

    if ctx.claim_type == ClaimType.NEW.value:
        crew = create_new_claim_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.DUPLICATE.value:
        crew = create_duplicate_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.FRAUD.value:
        crew = create_fraud_detection_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.PARTIAL_LOSS.value:
        crew = create_partial_loss_crew(ctx.llm)
    else:
        crew = create_total_loss_crew(ctx.llm)

    crew_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
    }

    try:
        workflow_result = _kickoff_with_retry(crew, crew_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            repo=ctx.repo,
            logger=logger,
            metrics=ctx.metrics,
            llm=ctx.llm,
            workflow_start_time=ctx.workflow_start_time,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    crew_latency = (time.time() - crew_start) * 1000

    ctx.workflow_output = str(
        getattr(workflow_result, "raw", None)
        or getattr(workflow_result, "output", None)
        or str(workflow_result)
    )

    logger.log_event("crew_completed", crew=ctx.claim_type, latency_ms=crew_latency)

    ctx.extracted_payout = _extract_payout_from_workflow_result(workflow_result, ctx.claim_type)
    if ctx.extracted_payout is not None:
        ctx.claim_data_with_id["payout_amount"] = ctx.extracted_payout

    if ctx.claim_type == ClaimType.PARTIAL_LOSS.value:
        _dispatch_repair_authorization_webhook(ctx.workflow_output, logger)

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, workflow_stage_key,
        json.dumps({
            "workflow_output": ctx.workflow_output,
            "extracted_payout": ctx.extracted_payout,
        }),
    )
    return None


def _stage_settlement(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the settlement crew when required by claim type.

    Returns an early-return response dict on mid-workflow escalation.
    Populates ``ctx.workflow_output`` with the combined final output.
    """
    if not _requires_settlement(ctx.claim_type):
        return None

    if "settlement" in ctx.checkpoints:
        try:
            stl_cp = json.loads(ctx.checkpoints["settlement"])
            if not isinstance(stl_cp, dict):
                raise ValueError("settlement checkpoint is not a JSON object")
            settlement_output = stl_cp["settlement_output"]
            ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, settlement_output)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore settlement from checkpoint; invalidating and re-running stage: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("settlement", None)
        else:
            logger.info("Restored settlement from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    logger.log_event("crew_started", crew="settlement")
    settlement_start = time.time()

    settlement_crew = create_settlement_crew(ctx.llm, claim_type=ctx.claim_type)
    settlement_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
        "workflow_output": ctx.workflow_output,
    }

    try:
        settlement_result = _kickoff_with_retry(settlement_crew, settlement_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            repo=ctx.repo,
            logger=logger,
            metrics=ctx.metrics,
            llm=ctx.llm,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="settlement",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    settlement_latency = (time.time() - settlement_start) * 1000
    settlement_output = str(
        getattr(settlement_result, "raw", None)
        or getattr(settlement_result, "output", None)
        or str(settlement_result)
    )
    logger.log_event("crew_completed", crew="settlement", latency_ms=settlement_latency)
    ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, settlement_output)

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, "settlement",
        json.dumps({"settlement_output": settlement_output}),
    )
    return None
