"""Individual workflow stage functions.

Each stage receives a ``_WorkflowCtx`` (defined in orchestrator) and returns
either ``None`` (proceed to next stage) or a response dict (early return).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from claim_agent.config.settings import (
    DUPLICATE_DAYS_WINDOW,
    DUPLICATE_SIMILARITY_THRESHOLD,
    DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE,
    HIGH_VALUE_DAMAGE_THRESHOLD,
    HIGH_VALUE_VEHICLE_THRESHOLD,
    PRE_ROUTING_FRAUD_DAMAGE_RATIO,
    get_router_config,
)
from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.crews.reopened_crew import create_reopened_crew
from claim_agent.crews.rental_crew import create_rental_crew
from claim_agent.crews.settlement_crew import create_settlement_crew
from claim_agent.crews.subrogation_crew import create_subrogation_crew
from claim_agent.crews.salvage_crew import create_salvage_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimType, EscalationOutput
from claim_agent.models.workflow_output import ReopenedWorkflowOutput
from claim_agent.notifications.webhook import dispatch_repair_authorized_from_workflow_output
from claim_agent.observability import get_logger
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.tools.escalation_logic import (
    detect_fraud_indicators_impl,
    evaluate_escalation_impl,
    normalize_claim_type,
    validate_router_classification_impl,
)
from claim_agent.workflow.claim_analysis import (
    _check_economic_total_loss,
    _filter_weak_fraud_indicators,
)
from claim_agent.workflow.duplicate_detection import (
    _check_for_duplicates,
    _damage_tags_overlap,
    _extract_damage_tags,
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
    _requires_salvage,
    _requires_settlement,
)
from claim_agent.workflow.routing import create_router_crew, _parse_router_output

if TYPE_CHECKING:
    from claim_agent.workflow.orchestrator import _WorkflowCtx

logger = get_logger(__name__)


def _stage_economic_analysis(ctx: _WorkflowCtx) -> dict | None:
    """Run economic total-loss analysis and set high-value flag.

    Enriches ``ctx.claim_data_with_id`` with economic flags (total loss,
    catastrophic event, damage-to-value ratio) and the high-value claim flag.
    """
    economic_check = _check_economic_total_loss(ctx.claim_data)
    ctx.claim_data_with_id["is_economic_total_loss"] = economic_check.get("is_economic_total_loss", False)
    ctx.claim_data_with_id["is_catastrophic_event"] = economic_check.get("is_catastrophic_event", False)
    ctx.claim_data_with_id["damage_indicates_total_loss"] = economic_check.get("damage_indicates_total_loss", False)
    ctx.claim_data_with_id["damage_is_repairable"] = economic_check.get("damage_is_repairable", False)
    ctx.claim_data_with_id["vehicle_value"] = economic_check.get("vehicle_value")
    ctx.claim_data_with_id["damage_to_value_ratio"] = economic_check.get("damage_to_value_ratio")

    est_damage = ctx.claim_data.get("estimated_damage")
    vehicle_value = economic_check.get("vehicle_value")
    is_high_value = (
        (est_damage is not None and est_damage > HIGH_VALUE_DAMAGE_THRESHOLD)
        or (vehicle_value is not None and vehicle_value > HIGH_VALUE_VEHICLE_THRESHOLD)
    )
    if is_high_value:
        ctx.claim_data_with_id["high_value_claim"] = True

    return None


def _stage_fraud_prescreening(ctx: _WorkflowCtx) -> dict | None:
    """Run conditional fraud pre-screening before routing.

    Only triggers when ``damage_to_value_ratio`` exceeds the pre-routing
    threshold and the claim is not catastrophic or explicitly total-loss.
    Sets ``pre_routing_fraud_indicators`` on ``ctx.claim_data_with_id``.
    """
    ratio = ctx.claim_data_with_id.get("damage_to_value_ratio") or 0
    is_catastrophic = ctx.claim_data_with_id.get("is_catastrophic_event", False)
    damage_indicates_total = ctx.claim_data_with_id.get("damage_indicates_total_loss", False)

    if ratio > PRE_ROUTING_FRAUD_DAMAGE_RATIO and not is_catastrophic and not damage_indicates_total:
        fraud_result = detect_fraud_indicators_impl(ctx.claim_data, ctx=ctx.context)
        try:
            fraud_data = json.loads(fraud_result)
        except (json.JSONDecodeError, TypeError):
            fraud_data = {}
        indicators = fraud_data if isinstance(fraud_data, list) else (fraud_data.get("indicators", []) if isinstance(fraud_data, dict) else [])
        if indicators:
            meaningful_indicators = _filter_weak_fraud_indicators(indicators)
            if meaningful_indicators:
                ctx.claim_data_with_id["pre_routing_fraud_indicators"] = meaningful_indicators

    return None


def _stage_duplicate_detection(ctx: _WorkflowCtx) -> dict | None:
    """Run duplicate detection and enrich claim with similarity data.

    Searches for existing claims by VIN, computes similarity scores, and
    sets ``existing_claims_for_vin``, ``damage_tags``, and
    ``definitive_duplicate`` on ``ctx.claim_data_with_id``.  Also rebuilds
    ``ctx.inputs`` so downstream stages see the fully enriched payload.
    """
    existing_claims = _check_for_duplicates(ctx.claim_data, current_claim_id=ctx.claim_id, ctx=ctx.context)
    if existing_claims:
        from claim_agent.tools.claims_logic import compute_similarity_score_impl

        current_incident = ctx.claim_data.get("incident_description", "") or ""
        current_damage = ctx.claim_data.get("damage_description", "") or ""
        current_combined = f"{current_incident} {current_damage}"
        current_damage_tags = _extract_damage_tags(current_combined)

        enriched_claims = []
        for c in existing_claims[:5]:
            existing_incident = c.get("incident_description", "") or ""
            existing_damage = c.get("damage_description", "") or ""
            existing_combined = f"{existing_incident} {existing_damage}"
            existing_damage_tags = _extract_damage_tags(existing_combined)
            damage_type_match = _damage_tags_overlap(current_damage_tags, existing_damage_tags)

            try:
                similarity_score = compute_similarity_score_impl(current_combined, existing_combined)
            except (TypeError, ZeroDivisionError) as e:
                logger.warning(
                    "Similarity computation failed for claim %s: %s",
                    ctx.claim_id,
                    str(e),
                )
                similarity_score = 0

            enriched_claims.append({
                "claim_id": c.get("id"),
                "incident_date": c.get("incident_date"),
                "incident_description": existing_incident[:200],
                "damage_description": existing_damage[:200],
                "damage_tags": sorted(existing_damage_tags),
                "damage_type_match": damage_type_match,
                "days_difference": c.get("days_difference"),
                "description_similarity_score": similarity_score,
            })
            if ctx.similarity_score_for_escalation is None or similarity_score > ctx.similarity_score_for_escalation:
                ctx.similarity_score_for_escalation = similarity_score

        ctx.claim_data_with_id["existing_claims_for_vin"] = enriched_claims
        ctx.claim_data_with_id["damage_tags"] = sorted(current_damage_tags)
        is_high_value = ctx.claim_data_with_id.get("high_value_claim", False)
        sim_threshold = DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE if is_high_value else DUPLICATE_SIMILARITY_THRESHOLD
        definitive_duplicate = any(
            (e.get("description_similarity_score") or 0) >= sim_threshold
            and e.get("days_difference", 999) <= DUPLICATE_DAYS_WINDOW
            and e.get("damage_type_match")
            for e in enriched_claims
        )
        ctx.claim_data_with_id["definitive_duplicate"] = definitive_duplicate
    else:
        ctx.similarity_score_for_escalation = None
        ctx.claim_data_with_id["definitive_duplicate"] = False

    ctx.inputs = {"claim_data": json.dumps(ctx.claim_data_with_id) if isinstance(ctx.claim_data_with_id, dict) else ctx.claim_data_with_id}
    claim_data_str = ctx.inputs["claim_data"] if isinstance(ctx.inputs["claim_data"], str) else json.dumps(ctx.inputs["claim_data"])
    logger.debug(
        "router_input_size claim_id=%s payload_chars=%s existing_claims_count=%s",
        ctx.claim_id,
        len(claim_data_str),
        len(ctx.claim_data_with_id.get("existing_claims_for_vin") or []),
    )

    return None


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

    # When resuming, trust claim_type from the persisted claim record (e.g., reviewer override).
    # When not resuming (fresh reprocess), always run the router so the full workflow re-executes.
    # Do not trust ctx.claim_data['claim_type'] from user input; it could bypass classification.
    if ctx.is_resume_run:
        persisted_claim = ctx.context.repo.get_claim(ctx.claim_id)
        persisted_claim_type = (
            persisted_claim.get("claim_type") if persisted_claim else None
        )
    else:
        persisted_claim_type = None
    if persisted_claim_type and str(persisted_claim_type).strip():
        normalized = normalize_claim_type(str(persisted_claim_type).strip())
        valid_types = {ct.value for ct in ClaimType}
        if normalized in valid_types:
            ctx.claim_type = normalized
            ctx.router_confidence = 1.0
            ctx.router_reasoning = "Using pre-determined claim type (reviewer override)"
            ctx.raw_output = f"claim_type: {ctx.claim_type}"
            logger.set_claim_type(ctx.claim_type)
            logger.info(
                "Skipping router classification; using claim_type from database",
                extra={"claim_id": ctx.claim_id, "claim_type": ctx.claim_type},
            )
            # Save this as checkpoint so it's consistent with normal router flow
            ctx.context.repo.save_task_checkpoint(
                ctx.claim_id,
                ctx.workflow_run_id,
                "router",
                json.dumps({
                    "claim_type": ctx.claim_type,
                    "router_confidence": ctx.router_confidence,
                    "router_reasoning": ctx.router_reasoning,
                    "raw_output": ctx.raw_output,
                }),
            )
            ctx.checkpoints["router"] = json.dumps({
                "claim_type": ctx.claim_type,
                "router_confidence": ctx.router_confidence,
                "router_reasoning": ctx.router_reasoning,
                "raw_output": ctx.raw_output,
            })
            return None

    logger.log_event("router_started", step="classification")
    router_start = time.time()

    router_crew = create_router_crew(ctx.context.llm)
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

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)

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
                    metrics=ctx.context.metrics,
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
                    ctx.raw_output = json.dumps(
                        {
                            "original_router_output": original_router_output,
                            "validation": val_data,
                        }
                    )
                    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
                else:
                    _escalate_low_router_confidence(
                        ctx.claim_id,
                        ctx.claim_type,
                        ctx.raw_output,
                        ctx.router_confidence,
                        confidence_threshold,
                        ctx.router_reasoning,
                        ctx.context,
                        logger,
                        ctx.workflow_start_time,
                        ctx.actor_id,
                    )
                    return _escalate_low_router_confidence_response(
                        ctx.claim_id,
                        ctx.claim_type,
                        ctx.raw_output,
                        ctx.router_confidence,
                        confidence_threshold,
                        router_reasoning=ctx.router_reasoning,
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("Router validation parse failed: %s", e)
                _escalate_low_router_confidence(
                    ctx.claim_id,
                    ctx.claim_type,
                    ctx.raw_output,
                    ctx.router_confidence,
                    confidence_threshold,
                    ctx.router_reasoning,
                    ctx.context,
                    logger,
                    ctx.workflow_start_time,
                    ctx.actor_id,
                )
                return _escalate_low_router_confidence_response(
                    ctx.claim_id,
                    ctx.claim_type,
                    ctx.raw_output,
                    ctx.router_confidence,
                    confidence_threshold,
                    router_reasoning=ctx.router_reasoning,
                )
        else:
            _escalate_low_router_confidence(
                ctx.claim_id,
                ctx.claim_type,
                ctx.raw_output,
                ctx.router_confidence,
                confidence_threshold,
                ctx.router_reasoning,
                ctx.context,
                logger,
                ctx.workflow_start_time,
                ctx.actor_id,
            )
            return _escalate_low_router_confidence_response(
                ctx.claim_id,
                ctx.claim_type,
                ctx.raw_output,
                ctx.router_confidence,
                confidence_threshold,
                router_reasoning=ctx.router_reasoning,
            )

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "router",
        json.dumps(
            {
                "claim_type": ctx.claim_type,
                "router_confidence": ctx.router_confidence,
                "router_reasoning": ctx.router_reasoning,
                "raw_output": ctx.raw_output,
            }
        ),
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
            ctx=ctx.context,
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
            details = json.dumps(
                {
                    "escalation_reasons": reasons,
                    "priority": priority,
                    "recommended_action": recommended_action,
                    "fraud_indicators": fraud_indicators,
                }
            )
            ctx.context.repo.save_workflow_result(
                ctx.claim_id, ctx.claim_type, ctx.raw_output, details
            )
            # Avoid overwriting review metadata / creating duplicate status-change events
            # when a resumed/retried workflow still results in needs_review.
            current_claim = ctx.context.repo.get_claim(ctx.claim_id)
            current_status = current_claim.get("status") if current_claim else None
            if current_status != STATUS_NEEDS_REVIEW:
                ctx.context.repo.update_claim_status(
                    ctx.claim_id,
                    STATUS_NEEDS_REVIEW,
                    claim_type=ctx.claim_type,
                    details=details,
                    actor_id=ctx.actor_id,
                )
                hours = _sla_hours_for_priority(priority)
                due_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                ctx.context.repo.update_claim_review_metadata(
                    ctx.claim_id,
                    priority=priority,
                    due_at=due_at,
                    review_started_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                )

            workflow_duration = (time.time() - ctx.workflow_start_time) * 1000
            logger.log_event(
                "claim_escalated",
                reasons=reasons,
                priority=priority,
                duration_ms=workflow_duration,
            )
            _record_crew_llm_usage(
                claim_id=ctx.claim_id, llm=ctx.context.llm, metrics=ctx.context.metrics
            )
            ctx.context.metrics.end_claim(ctx.claim_id, status="escalated")
            record_claim_outcome(ctx.claim_id, "escalated", (time.time() - ctx.workflow_start_time))
            ctx.context.metrics.log_claim_summary(ctx.claim_id)

            return {
                **escalation_output.model_dump(),
                "claim_type": ctx.claim_type,
                "status": STATUS_NEEDS_REVIEW,
                "router_output": ctx.raw_output,
                "workflow_output": details,
                "workflow_run_id": ctx.workflow_run_id,
                "summary": f"Escalated for review: {', '.join(reasons)}",
            }

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, "escalation_check", "{}"
    )
    return None


def _parse_reopened_output(result) -> str:
    """Extract target_claim_type from Reopened crew result. Defaults to partial_loss."""
    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output and isinstance(tasks_output, list) and len(tasks_output) > 0:
        last_output = getattr(tasks_output[-1], "output", None)
        if isinstance(last_output, ReopenedWorkflowOutput):
            target = normalize_claim_type(last_output.target_claim_type)
            if target in (
                ClaimType.PARTIAL_LOSS.value,
                ClaimType.TOTAL_LOSS.value,
                ClaimType.BODILY_INJURY.value,
            ):
                return target
    try:
        raw = str(getattr(result, "raw", None) or getattr(result, "output", None) or result)
        if "target_claim_type" in raw.lower():
            m = re.search(r'"target_claim_type"\s*:\s*"([^"]+)"', raw, re.I)
            if m:
                target = normalize_claim_type(m.group(1))
                if target in (
                    ClaimType.PARTIAL_LOSS.value,
                    ClaimType.TOTAL_LOSS.value,
                    ClaimType.BODILY_INJURY.value,
                ):
                    return target
    except (TypeError, AttributeError):
        pass
    return ClaimType.PARTIAL_LOSS.value


def _stage_workflow_crew(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the primary workflow crew.

    Populates ``ctx.workflow_output`` and ``ctx.extracted_payout``.
    For reopened claims: runs Reopened crew first, then routes to partial_loss/total_loss/bodily_injury.
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
            if wf_cp.get("target_claim_type"):
                ctx.claim_type = wf_cp["target_claim_type"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore %s from checkpoint; invalidating and re-running stage: %s",
                workflow_stage_key,
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop(workflow_stage_key, None)
        else:
            logger.info(
                "Restored %s from checkpoint", workflow_stage_key, extra={"claim_id": ctx.claim_id}
            )
            return None

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew=ctx.claim_type)
    crew_start = time.time()

    crew_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
    }

    reopened_output = ""

    if ctx.claim_type == ClaimType.REOPENED.value:
        reopened_crew = create_reopened_crew(ctx.context.llm)
        try:
            reopened_result = _kickoff_with_retry(reopened_crew, crew_inputs)
        except MidWorkflowEscalation as e:
            return _handle_mid_workflow_escalation(
                e,
                claim_id=ctx.claim_id,
                claim_type=ctx.claim_type,
                raw_output=ctx.raw_output,
                context=ctx.context,
                workflow_logger=logger,
                workflow_start_time=ctx.workflow_start_time,
                workflow_run_id=ctx.workflow_run_id,
            )
        reopened_output = str(
            getattr(reopened_result, "raw", None)
            or getattr(reopened_result, "output", None)
            or str(reopened_result)
        )
        ctx.claim_type = _parse_reopened_output(reopened_result)
        crew_inputs["claim_data"] = json.dumps(
            {**ctx.claim_data_with_id, "claim_type": ctx.claim_type}
        )

    if ctx.claim_type == ClaimType.NEW.value:
        crew = create_new_claim_crew(ctx.context.llm)
    elif ctx.claim_type == ClaimType.DUPLICATE.value:
        crew = create_duplicate_crew(ctx.context.llm)
    elif ctx.claim_type == ClaimType.FRAUD.value:
        crew = create_fraud_detection_crew(ctx.context.llm)
    elif ctx.claim_type == ClaimType.BODILY_INJURY.value:
        crew = create_bodily_injury_crew(ctx.context.llm)
    elif ctx.claim_type == ClaimType.PARTIAL_LOSS.value:
        crew = create_partial_loss_crew(ctx.context.llm)
    else:
        crew = create_total_loss_crew(ctx.context.llm)

    try:
        workflow_result = _kickoff_with_retry(crew, crew_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            context=ctx.context,
            workflow_logger=logger,
            workflow_start_time=ctx.workflow_start_time,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    crew_latency = (time.time() - crew_start) * 1000

    routed_output = str(
        getattr(workflow_result, "raw", None)
        or getattr(workflow_result, "output", None)
        or str(workflow_result)
    )

    if workflow_stage_key == f"workflow:{ClaimType.REOPENED.value}":
        ctx.workflow_output = _combine_workflow_outputs(
            reopened_output,
            routed_output,
            label="Routed workflow output",
        )
    else:
        ctx.workflow_output = routed_output

    logger.log_event("crew_completed", crew=ctx.claim_type, latency_ms=crew_latency)

    ctx.extracted_payout = _extract_payout_from_workflow_result(workflow_result, ctx.claim_type)
    if ctx.extracted_payout is not None:
        ctx.claim_data_with_id["payout_amount"] = ctx.extracted_payout

    if ctx.claim_type == ClaimType.PARTIAL_LOSS.value:
        dispatch_repair_authorized_from_workflow_output(ctx.workflow_output, log=logger)

    cp_data = {
        "workflow_output": ctx.workflow_output,
        "extracted_payout": ctx.extracted_payout,
    }
    if workflow_stage_key == f"workflow:{ClaimType.REOPENED.value}":
        cp_data["target_claim_type"] = ctx.claim_type

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        workflow_stage_key,
        json.dumps(cp_data),
    )
    return None


def _stage_rental(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the rental reimbursement crew for partial loss claims.

    Only runs when claim_type is partial_loss. Combines rental output with
    ctx.workflow_output before settlement.
    """
    if ctx.claim_type != ClaimType.PARTIAL_LOSS.value:
        return None

    if "rental" in ctx.checkpoints:
        try:
            rental_cp = json.loads(ctx.checkpoints["rental"])
            if not isinstance(rental_cp, dict):
                raise ValueError("rental checkpoint is not a JSON object")
            rental_output = rental_cp["rental_output"]
            ctx.workflow_output = _combine_workflow_outputs(
                ctx.workflow_output, rental_output, label="Rental workflow output"
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore rental from checkpoint; invalidating and re-running stage: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("rental", None)
        else:
            logger.info("Restored rental from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew="rental")
    rental_start = time.time()

    rental_crew = create_rental_crew(ctx.context.llm)
    rental_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
        "workflow_output": ctx.workflow_output,
    }

    try:
        rental_result = _kickoff_with_retry(rental_crew, rental_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            context=ctx.context,
            workflow_logger=logger,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="rental",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    rental_latency = (time.time() - rental_start) * 1000
    rental_output = str(
        getattr(rental_result, "raw", None)
        or getattr(rental_result, "output", None)
        or str(rental_result)
    )
    logger.log_event("crew_completed", crew="rental", latency_ms=rental_latency)
    ctx.workflow_output = _combine_workflow_outputs(
        ctx.workflow_output, rental_output, label="Rental workflow output"
    )

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "rental",
        json.dumps({"rental_output": rental_output}),
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

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew="settlement")
    settlement_start = time.time()

    settlement_crew = create_settlement_crew(ctx.context.llm, claim_type=ctx.claim_type)
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
            context=ctx.context,
            workflow_logger=logger,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="settlement",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    settlement_latency = (time.time() - settlement_start) * 1000
    settlement_output = str(
        getattr(settlement_result, "raw", None)
        or getattr(settlement_result, "output", None)
        or str(settlement_result)
    )
    logger.log_event("crew_completed", crew="settlement", latency_ms=settlement_latency)
    ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, settlement_output)

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "settlement",
        json.dumps({"settlement_output": settlement_output}),
    )
    return None


def _stage_subrogation(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the subrogation crew after settlement when required by claim type.

    Populates ``ctx.workflow_output`` with the combined subrogation output.
    """
    if not _requires_settlement(ctx.claim_type):
        return None

    if "subrogation" in ctx.checkpoints:
        try:
            sub_cp = json.loads(ctx.checkpoints["subrogation"])
            if not isinstance(sub_cp, dict):
                raise ValueError("subrogation checkpoint is not a JSON object")
            subrogation_output = sub_cp["subrogation_output"]
            ctx.workflow_output = _combine_workflow_outputs(
                ctx.workflow_output, subrogation_output, label="Subrogation workflow output"
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore subrogation from checkpoint; invalidating and re-running stage: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("subrogation", None)
        else:
            logger.info("Restored subrogation from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew="subrogation")
    subrogation_start = time.time()

    subrogation_crew = create_subrogation_crew(ctx.context.llm)
    subrogation_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
        "workflow_output": ctx.workflow_output,
    }

    try:
        subrogation_result = _kickoff_with_retry(subrogation_crew, subrogation_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            context=ctx.context,
            workflow_logger=logger,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="subrogation",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    subrogation_latency = (time.time() - subrogation_start) * 1000
    subrogation_output = str(
        getattr(subrogation_result, "raw", None)
        or getattr(subrogation_result, "output", None)
        or str(subrogation_result)
    )
    logger.log_event("crew_completed", crew="subrogation", latency_ms=subrogation_latency)
    ctx.workflow_output = _combine_workflow_outputs(
        ctx.workflow_output, subrogation_output, label="Subrogation workflow output"
    )

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "subrogation",
        json.dumps({"subrogation_output": subrogation_output}),
    )
    return None


def _stage_salvage(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the salvage crew after subrogation when claim is total_loss.

    Populates ``ctx.workflow_output`` with the combined salvage output.
    """
    if not _requires_salvage(ctx.claim_type):
        return None

    if "salvage" in ctx.checkpoints:
        try:
            salv_cp = json.loads(ctx.checkpoints["salvage"])
            if not isinstance(salv_cp, dict):
                raise ValueError("salvage checkpoint is not a JSON object")
            salvage_output = salv_cp["salvage_output"]
            ctx.workflow_output = _combine_workflow_outputs(
                ctx.workflow_output,
                salvage_output,
                label="Salvage workflow output",
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore salvage from checkpoint; invalidating and re-running stage: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("salvage", None)
        else:
            logger.info("Restored salvage from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew="salvage")
    salvage_start = time.time()

    salvage_crew = create_salvage_crew(ctx.context.llm)
    salvage_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
        "workflow_output": ctx.workflow_output,
    }

    try:
        salvage_result = _kickoff_with_retry(salvage_crew, salvage_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            context=ctx.context,
            workflow_logger=logger,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="salvage",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    salvage_latency = (time.time() - salvage_start) * 1000
    salvage_output = str(
        getattr(salvage_result, "raw", None)
        or getattr(salvage_result, "output", None)
        or str(salvage_result)
    )
    logger.log_event("crew_completed", crew="salvage", latency_ms=salvage_latency)
    ctx.workflow_output = _combine_workflow_outputs(
        ctx.workflow_output,
        salvage_output,
        label="Salvage workflow output",
    )

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "salvage",
        json.dumps({"salvage_output": salvage_output}),
    )
    return None
