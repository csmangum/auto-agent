"""Individual workflow stage functions.

Each stage receives a ``_WorkflowCtx`` (defined in orchestrator) and returns
either ``None`` (proceed to next stage) or a response dict (early return).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from claim_agent.config.settings import (
    DUPLICATE_DAYS_WINDOW,
    DUPLICATE_SIMILARITY_THRESHOLD,
    DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE,
    HIGH_VALUE_DAMAGE_THRESHOLD,
    HIGH_VALUE_VEHICLE_THRESHOLD,
    PRE_ROUTING_FRAUD_DAMAGE_RATIO,
    get_coverage_config,
    get_escalation_config,
    get_router_config,
)
from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.escalation_crew import create_escalation_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.crews.reopened_crew import create_reopened_crew
from claim_agent.crews.liability_determination_crew import create_liability_determination_crew
from claim_agent.crews.rental_crew import create_rental_crew
from claim_agent.crews.settlement_crew import create_settlement_crew
from claim_agent.crews.subrogation_crew import create_subrogation_crew
from claim_agent.crews.after_action_crew import create_after_action_crew
from claim_agent.crews.task_planner_crew import create_task_planner_crew
from claim_agent.crews.salvage_crew import create_salvage_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.db.constants import STATUS_DENIED, STATUS_NEEDS_REVIEW, STATUS_UNDER_INVESTIGATION
from claim_agent.rag.constants import DEFAULT_STATE
from pydantic import ValidationError

from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimType, EscalationOutput, LiabilityDeterminationOutput
from claim_agent.models.stage_outputs import (
    CoverageVerificationResult,
    DuplicateDetectionResult,
    EconomicAnalysisResult,
    EnrichedDuplicate,
    EscalationCheckResult,
    FraudPrescreeningResult,
    RouterStageResult,
)
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
from claim_agent.tools.claims_logic import compute_similarity_score_impl
from claim_agent.workflow.duplicate_detection import (
    _check_for_duplicates,
    _damage_tags_overlap,
    _extract_damage_tags,
)
from claim_agent.workflow.budget import _check_token_budget, _record_crew_usage_delta
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
from claim_agent.workflow.coverage_verification import verify_coverage_impl
from claim_agent.workflow.routing import create_router_crew, _parse_router_output

if TYPE_CHECKING:
    from claim_agent.workflow.orchestrator import _WorkflowCtx

logger = get_logger(__name__)


def _stage_coverage_verification(ctx: _WorkflowCtx) -> dict | None:
    """Run coverage verification as first FNOL gate. Deny or escalate before routing."""
    if "coverage_verification" in ctx.checkpoints:
        try:
            cp = json.loads(ctx.checkpoints["coverage_verification"])
            if isinstance(cp, dict) and cp.get("passed"):
                ctx.coverage_result = CoverageVerificationResult(
                    passed=True,
                    reason=cp.get("reason", "Restored from checkpoint"),
                    details=cp.get("details", {}),
                )
                logger.info(
                    "Restored coverage_verification from checkpoint",
                    extra={"claim_id": ctx.claim_id},
                )
                return None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Failed to restore coverage_verification from checkpoint: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("coverage_verification", None)

    config = get_coverage_config()
    if not config.get("enabled", True):
        ctx.coverage_result = CoverageVerificationResult(
            passed=True,
            reason="Coverage verification disabled",
            details={"enabled": False},
        )
        ctx.context.repo.save_task_checkpoint(
            ctx.claim_id,
            ctx.workflow_run_id,
            "coverage_verification",
            json.dumps(
                {
                    "passed": True,
                    "reason": "Coverage verification disabled",
                    "details": {"enabled": False},
                }
            ),
        )
        return None

    result = verify_coverage_impl(ctx.claim_data, ctx=ctx.context, config=config)
    ctx.coverage_result = result

    if result.denied:
        reason = result.reason or "Coverage verification failed"
        ctx.context.repo.deny_claim_at_claimant(
            ctx.claim_id,
            reason,
            actor_id=ctx.actor_id,
            coverage_verification_details=result.details,
        )
        workflow_output = json.dumps(
            {
                "coverage_verification": "denied",
                "reason": reason,
                "details": result.details,
            }
        )
        ctx.context.repo.save_workflow_result(ctx.claim_id, ctx.claim_type, "", workflow_output)
        ctx.context.metrics.end_claim(ctx.claim_id, status=STATUS_DENIED)
        record_claim_outcome(ctx.claim_id, STATUS_DENIED, (time.time() - ctx.workflow_start_time))
        ctx.context.metrics.log_claim_summary(ctx.claim_id)
        logger.log_event(
            "coverage_denied",
            reason=reason,
            extra={"claim_id": ctx.claim_id},
        )
        return {
            "claim_id": ctx.claim_id,
            "claim_type": ctx.claim_type,
            "status": STATUS_DENIED,
            "router_output": "",
            "workflow_output": workflow_output,
            "workflow_run_id": ctx.workflow_run_id,
            "summary": reason,
        }

    if result.under_investigation:
        reason = result.reason or "Coverage under investigation"
        ctx.context.repo.update_claim_status(
            ctx.claim_id,
            STATUS_UNDER_INVESTIGATION,
            details=reason,
            actor_id=ctx.actor_id,
        )
        ctx.context.repo.insert_coverage_verification_audit(
            ctx.claim_id,
            "under_investigation",
            {"reason": reason, **result.details},
            actor_id=ctx.actor_id,
        )
        workflow_output = json.dumps(
            {
                "coverage_verification": "under_investigation",
                "reason": reason,
                "details": result.details,
            }
        )
        ctx.context.repo.save_workflow_result(ctx.claim_id, ctx.claim_type, "", workflow_output)
        ctx.context.metrics.end_claim(ctx.claim_id, status=STATUS_UNDER_INVESTIGATION)
        record_claim_outcome(
            ctx.claim_id,
            STATUS_UNDER_INVESTIGATION,
            (time.time() - ctx.workflow_start_time),
        )
        ctx.context.metrics.log_claim_summary(ctx.claim_id)
        logger.log_event(
            "coverage_under_investigation",
            reason=reason,
            extra={"claim_id": ctx.claim_id},
        )
        return {
            "claim_id": ctx.claim_id,
            "claim_type": ctx.claim_type,
            "status": STATUS_UNDER_INVESTIGATION,
            "router_output": "",
            "workflow_output": workflow_output,
            "workflow_run_id": ctx.workflow_run_id,
            "summary": reason,
        }

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        "coverage_verification",
        json.dumps(
            {
                "passed": True,
                "reason": result.reason,
                "details": result.details,
            }
        ),
    )
    return None


def _stage_economic_analysis(ctx: _WorkflowCtx) -> dict | None:
    """Run economic total-loss analysis and set high-value flag.

    Enriches ``ctx.claim_data_with_id`` with economic flags (total loss,
    catastrophic event, damage-to-value ratio) and the high-value claim flag.
    Stores the typed result in ``ctx.economic_result``.
    """
    economic_check = _check_economic_total_loss(ctx.claim_data)

    est_damage = ctx.claim_data.get("estimated_damage")
    vehicle_value = economic_check.get("vehicle_value")
    is_high_value = (est_damage is not None and est_damage > HIGH_VALUE_DAMAGE_THRESHOLD) or (
        vehicle_value is not None and vehicle_value > HIGH_VALUE_VEHICLE_THRESHOLD
    )

    result = EconomicAnalysisResult(
        is_economic_total_loss=economic_check.get("is_economic_total_loss", False),
        is_catastrophic_event=economic_check.get("is_catastrophic_event", False),
        damage_indicates_total_loss=economic_check.get("damage_indicates_total_loss", False),
        damage_is_repairable=economic_check.get("damage_is_repairable", False),
        vehicle_value=vehicle_value,
        damage_to_value_ratio=economic_check.get("damage_to_value_ratio"),
        high_value_claim=is_high_value,
    )
    ctx.economic_result = result

    ctx.claim_data_with_id["is_economic_total_loss"] = result.is_economic_total_loss
    ctx.claim_data_with_id["is_catastrophic_event"] = result.is_catastrophic_event
    ctx.claim_data_with_id["damage_indicates_total_loss"] = result.damage_indicates_total_loss
    ctx.claim_data_with_id["damage_is_repairable"] = result.damage_is_repairable
    ctx.claim_data_with_id["vehicle_value"] = result.vehicle_value
    ctx.claim_data_with_id["damage_to_value_ratio"] = result.damage_to_value_ratio
    if result.high_value_claim:
        ctx.claim_data_with_id["high_value_claim"] = True

    return None


def _stage_fraud_prescreening(ctx: _WorkflowCtx) -> dict | None:
    """Run conditional fraud pre-screening before routing.

    Only triggers when ``damage_to_value_ratio`` exceeds the pre-routing
    threshold and the claim is not catastrophic or explicitly total-loss.
    Stores the typed result in ``ctx.fraud_prescreening_result``.
    """
    econ = ctx.economic_result
    ratio = (
        (econ.damage_to_value_ratio or 0)
        if econ
        else (ctx.claim_data_with_id.get("damage_to_value_ratio") or 0)
    )
    is_catastrophic = (
        econ.is_catastrophic_event
        if econ
        else ctx.claim_data_with_id.get("is_catastrophic_event", False)
    )
    damage_indicates_total = (
        econ.damage_indicates_total_loss
        if econ
        else ctx.claim_data_with_id.get("damage_indicates_total_loss", False)
    )

    meaningful_indicators: list[str] = []
    if (
        ratio > PRE_ROUTING_FRAUD_DAMAGE_RATIO
        and not is_catastrophic
        and not damage_indicates_total
    ):
        fraud_result = detect_fraud_indicators_impl(ctx.claim_data, ctx=ctx.context)
        try:
            fraud_data = json.loads(fraud_result)
        except (json.JSONDecodeError, TypeError):
            fraud_data = {}
        indicators = (
            fraud_data
            if isinstance(fraud_data, list)
            else (fraud_data.get("indicators", []) if isinstance(fraud_data, dict) else [])
        )
        if indicators:
            meaningful_indicators = _filter_weak_fraud_indicators(indicators)
            if meaningful_indicators:
                ctx.claim_data_with_id["pre_routing_fraud_indicators"] = meaningful_indicators

    ctx.fraud_prescreening_result = FraudPrescreeningResult(
        pre_routing_fraud_indicators=meaningful_indicators,
    )

    return None


def _stage_duplicate_detection(ctx: _WorkflowCtx) -> dict | None:
    """Run duplicate detection and enrich claim with similarity data.

    Searches for existing claims by VIN, computes similarity scores, and
    sets ``existing_claims_for_vin``, ``damage_tags``, and
    ``definitive_duplicate`` on ``ctx.claim_data_with_id``.  Also rebuilds
    ``ctx.inputs`` so downstream stages see the fully enriched payload.
    Stores the typed result in ``ctx.duplicate_result``.
    """
    existing_claims = _check_for_duplicates(
        ctx.claim_data, current_claim_id=ctx.claim_id, ctx=ctx.context
    )
    if existing_claims:
        current_incident = ctx.claim_data.get("incident_description", "") or ""
        current_damage = ctx.claim_data.get("damage_description", "") or ""
        current_combined = f"{current_incident} {current_damage}"
        current_damage_tags = _extract_damage_tags(current_combined)

        enriched_models: list[EnrichedDuplicate] = []
        max_sim: float | None = None
        for c in existing_claims[:5]:
            existing_incident = c.get("incident_description", "") or ""
            existing_damage = c.get("damage_description", "") or ""
            existing_combined = f"{existing_incident} {existing_damage}"
            existing_damage_tags = _extract_damage_tags(existing_combined)
            damage_type_match = _damage_tags_overlap(current_damage_tags, existing_damage_tags)

            try:
                similarity_score = compute_similarity_score_impl(
                    current_combined, existing_combined
                )
            except (TypeError, ZeroDivisionError) as e:
                logger.warning(
                    "Similarity computation failed for claim %s: %s",
                    ctx.claim_id,
                    str(e),
                )
                similarity_score = 0.0

            enriched_models.append(
                EnrichedDuplicate(
                    claim_id=c.get("id"),
                    incident_date=c.get("incident_date"),
                    incident_description=existing_incident[:200],
                    damage_description=existing_damage[:200],
                    damage_tags=sorted(existing_damage_tags),
                    damage_type_match=damage_type_match,
                    days_difference=c.get("days_difference"),
                    description_similarity_score=similarity_score,
                )
            )
            if max_sim is None or similarity_score > max_sim:
                max_sim = similarity_score

        ctx.similarity_score_for_escalation = max_sim

        econ = ctx.economic_result
        is_high_value = (
            econ.high_value_claim if econ else ctx.claim_data_with_id.get("high_value_claim", False)
        )
        sim_threshold = (
            DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE
            if is_high_value
            else DUPLICATE_SIMILARITY_THRESHOLD
        )
        definitive_duplicate = any(
            e.description_similarity_score >= sim_threshold
            and (e.days_difference or 999) <= DUPLICATE_DAYS_WINDOW
            and e.damage_type_match
            for e in enriched_models
        )

        dup_result = DuplicateDetectionResult(
            existing_claims=enriched_models,
            damage_tags=sorted(current_damage_tags),
            definitive_duplicate=definitive_duplicate,
            similarity_score_for_escalation=max_sim,
        )

        enriched_dicts = [e.model_dump(mode="json") for e in enriched_models]
        ctx.claim_data_with_id["existing_claims_for_vin"] = enriched_dicts
        ctx.claim_data_with_id["damage_tags"] = dup_result.damage_tags
        ctx.claim_data_with_id["definitive_duplicate"] = definitive_duplicate
    else:
        ctx.similarity_score_for_escalation = None
        ctx.claim_data_with_id["definitive_duplicate"] = False
        dup_result = DuplicateDetectionResult(definitive_duplicate=False)

    ctx.duplicate_result = dup_result

    ctx.inputs = {
        "claim_data": json.dumps(ctx.claim_data_with_id)
        if isinstance(ctx.claim_data_with_id, dict)
        else ctx.claim_data_with_id
    }
    claim_data_str = (
        ctx.inputs["claim_data"]
        if isinstance(ctx.inputs["claim_data"], str)
        else json.dumps(ctx.inputs["claim_data"])
    )
    logger.debug(
        "router_input_size claim_id=%s payload_chars=%s existing_claims_count=%s",
        ctx.claim_id,
        len(claim_data_str),
        len(ctx.claim_data_with_id.get("existing_claims_for_vin") or []),
    )

    return None


def _run_stage(
    ctx: _WorkflowCtx,
    stage_key: str,
    *,
    restore: Callable[["_WorkflowCtx", dict], None],
    run: Callable[["_WorkflowCtx"], dict | None],
    get_checkpoint_data: Callable[["_WorkflowCtx"], dict],
) -> dict | None:
    """Generic checkpoint wrapper: check/restore, run body, save checkpoint.

    If stage_key is in checkpoints: parse JSON, validate dict, call restore(ctx, cp).
    On success: log and return None. On exception: log warning, pop checkpoint, fall through.
    Call run(ctx); if it returns a non-None dict (early return), propagate it.
    Otherwise save checkpoint and return None.
    """
    if stage_key in ctx.checkpoints:
        try:
            cp = json.loads(ctx.checkpoints[stage_key])
            if not isinstance(cp, dict):
                raise ValueError(f"{stage_key} checkpoint is not a JSON object")
            restore(ctx, cp)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore %s from checkpoint; invalidating and re-running stage: %s",
                stage_key,
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop(stage_key, None)
        else:
            logger.info("Restored %s from checkpoint", stage_key, extra={"claim_id": ctx.claim_id})
            return None

    early_return = run(ctx)
    if early_return is not None:
        return early_return

    ctx.context.repo.save_task_checkpoint(
        ctx.claim_id,
        ctx.workflow_run_id,
        stage_key,
        json.dumps(get_checkpoint_data(ctx)),
    )
    return None


def _run_crew_stage_body(
    ctx: _WorkflowCtx,
    crew_name: str,
    create_crew: Callable[["_WorkflowCtx"], object],
    get_inputs: Callable[["_WorkflowCtx"], dict],
    combine_label: str | None,
) -> dict | None:
    """Execute crew and combine output. Sets ctx._last_stage_output for checkpoint."""
    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    logger.log_event("crew_started", crew=crew_name)
    start = time.time()
    crew = create_crew(ctx)
    inputs = get_inputs(ctx)
    try:
        result = _kickoff_with_retry(crew, inputs, create_crew_no_args=lambda: create_crew(ctx))
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
            stage=crew_name,
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )
    _record_crew_usage_delta(
        ctx.claim_id,
        ctx.context.llm,
        ctx.context.metrics,
        crew_name,
        ctx.claim_type or None,
    )
    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    output_str = str(getattr(result, "raw", None) or getattr(result, "output", None) or str(result))
    logger.log_event("crew_completed", crew=crew_name, latency_ms=(time.time() - start) * 1000)
    ctx._last_stage_output = output_str
    if combine_label:
        ctx.workflow_output = _combine_workflow_outputs(
            ctx.workflow_output, output_str, label=combine_label
        )
    else:
        ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, output_str)
    return None


def _run_crew_stage(
    ctx: _WorkflowCtx,
    stage_key: str,
    crew_name: str,
    output_key: str,
    *,
    create_crew: Callable[["_WorkflowCtx"], object],
    get_inputs: Callable[["_WorkflowCtx"], dict],
    combine_label: str | None = None,
) -> dict | None:
    """Run a crew stage with checkpoint restore/run/save via _run_stage."""

    def restore(c: _WorkflowCtx, cp: dict) -> None:
        output = cp[output_key]
        if combine_label:
            c.workflow_output = _combine_workflow_outputs(
                c.workflow_output, output, label=combine_label
            )
        else:
            c.workflow_output = _combine_workflow_outputs(c.workflow_output, output)

    return _run_stage(
        ctx,
        stage_key,
        restore=restore,
        run=lambda c: _run_crew_stage_body(c, crew_name, create_crew, get_inputs, combine_label),
        get_checkpoint_data=lambda c: {output_key: c._last_stage_output},
    )


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
        persisted_claim_type = persisted_claim.get("claim_type") if persisted_claim else None
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
                json.dumps(
                    {
                        "claim_type": ctx.claim_type,
                        "router_confidence": ctx.router_confidence,
                        "router_reasoning": ctx.router_reasoning,
                        "raw_output": ctx.raw_output,
                    }
                ),
            )
            ctx.checkpoints["router"] = json.dumps(
                {
                    "claim_type": ctx.claim_type,
                    "router_confidence": ctx.router_confidence,
                    "router_reasoning": ctx.router_reasoning,
                    "raw_output": ctx.raw_output,
                }
            )
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

    _record_crew_usage_delta(
        ctx.claim_id, ctx.context.llm, ctx.context.metrics, "router", claim_type=ctx.claim_type
    )
    _check_token_budget(ctx.claim_id, ctx.context.metrics, ctx.context.llm)
    ctx.context.metrics.update_claim_type(ctx.claim_id, ctx.claim_type)

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

    ctx.router_result = RouterStageResult(
        claim_type=ctx.claim_type,
        router_confidence=ctx.router_confidence,
        router_reasoning=ctx.router_reasoning,
        raw_output=ctx.raw_output,
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


def _parse_escalation_crew_result(result: Any) -> EscalationCheckResult | None:
    """Extract EscalationCheckResult from escalation crew result.

    CrewAI may store output_pydantic result in either ``pydantic`` or ``output``
    depending on version; check both for robustness.
    """
    tasks_output = getattr(result, "tasks_output", None)
    if not tasks_output or not isinstance(tasks_output, list) or len(tasks_output) == 0:
        return None
    last_task = tasks_output[-1]
    last_output = getattr(last_task, "pydantic", None) or getattr(last_task, "output", None)
    if isinstance(last_output, EscalationCheckResult):
        return last_output
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
        escalation_result: dict | None = None
        use_agent = get_escalation_config().get("use_agent", True)
        escalation_crew_ran = False

        if use_agent:
            try:
                claim_data_json = json.dumps(ctx.claim_data_with_id, default=str)
                sim_str = (
                    str(ctx.similarity_score_for_escalation)
                    if ctx.similarity_score_for_escalation is not None
                    else ""
                )
                conf_str = str(ctx.router_confidence) if ctx.router_confidence is not None else ""
                crew = create_escalation_crew(ctx.context.llm)
                crew_result = _kickoff_with_retry(
                    crew,
                    {
                        "claim_data": claim_data_json,
                        "router_output": ctx.raw_output or "",
                        "similarity_score": sim_str,
                        "payout_amount": "",
                        "router_confidence": conf_str,
                    },
                )
                escalation_crew_ran = True
                decision = _parse_escalation_crew_result(crew_result)
                if decision is not None:
                    escalation_result = {
                        "needs_review": decision.needs_review,
                        "escalation_reasons": decision.escalation_reasons,
                        "priority": decision.priority,
                        "recommended_action": decision.recommended_action,
                        "fraud_indicators": decision.fraud_indicators,
                    }
            except MidWorkflowEscalation:
                raise
            except ValidationError as e:
                logger.warning(
                    "Escalation crew output validation failed, falling back to rules: %s",
                    e,
                    exc_info=True,
                )
            except Exception as e:
                logger.warning(
                    "Escalation crew failed, falling back to rules: %s",
                    e,
                    exc_info=True,
                )

        if escalation_result is None:
            escalation_json = evaluate_escalation_impl(
                ctx.claim_data,
                ctx.raw_output,
                similarity_score=ctx.similarity_score_for_escalation,
                payout_amount=None,
                router_confidence=ctx.router_confidence,
                ctx=ctx.context,
            )
            escalation_result = json.loads(escalation_json)

        if escalation_crew_ran:
            _record_crew_usage_delta(
                ctx.claim_id,
                ctx.context.llm,
                ctx.context.metrics,
                "escalation",
                ctx.claim_type,
            )

        if escalation_result.get("needs_review"):
            reasons = escalation_result.get("escalation_reasons", [])
            priority = escalation_result.get("priority", "low")
            recommended_action = escalation_result.get("recommended_action", "")
            fraud_indicators = escalation_result.get("fraud_indicators", [])
            ctx.escalation_result = EscalationCheckResult(
                needs_review=True,
                escalation_reasons=reasons,
                priority=priority,
                recommended_action=recommended_action,
                fraud_indicators=fraud_indicators,
            )
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
                due_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
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

    ctx.escalation_result = EscalationCheckResult(needs_review=False)
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

    def restore(c: _WorkflowCtx, cp: dict) -> None:
        c.workflow_output = cp["workflow_output"]
        c.extracted_payout = cp.get("extracted_payout")
        if c.extracted_payout is not None:
            c.claim_data_with_id["payout_amount"] = c.extracted_payout
        if cp.get("target_claim_type"):
            c.claim_type = cp["target_claim_type"]

    def run(c: _WorkflowCtx) -> dict | None:
        _check_token_budget(c.claim_id, c.context.metrics, c.context.llm)
        logger.log_event("crew_started", crew=c.claim_type)
        crew_start = time.time()
        crew_inputs = {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
        }
        reopened_output = ""

        if c.claim_type == ClaimType.REOPENED.value:
            reopened_crew = create_reopened_crew(c.context.llm)
            try:
                reopened_result = _kickoff_with_retry(reopened_crew, crew_inputs)
            except MidWorkflowEscalation as e:
                return _handle_mid_workflow_escalation(
                    e,
                    claim_id=c.claim_id,
                    claim_type=c.claim_type,
                    raw_output=c.raw_output,
                    context=c.context,
                    workflow_logger=logger,
                    workflow_start_time=c.workflow_start_time,
                    workflow_run_id=c.workflow_run_id,
                )
            _record_crew_usage_delta(
                c.claim_id,
                c.context.llm,
                c.context.metrics,
                "reopened",
                c.claim_type,
            )
            reopened_output = str(
                getattr(reopened_result, "raw", None)
                or getattr(reopened_result, "output", None)
                or str(reopened_result)
            )
            c.claim_type = _parse_reopened_output(reopened_result)
            crew_inputs["claim_data"] = json.dumps(
                {**c.claim_data_with_id, "claim_type": c.claim_type}
            )

        if c.claim_type == ClaimType.NEW.value:
            crew = create_new_claim_crew(c.context.llm)
        elif c.claim_type == ClaimType.DUPLICATE.value:
            crew = create_duplicate_crew(c.context.llm)
        elif c.claim_type == ClaimType.FRAUD.value:
            crew = create_fraud_detection_crew(c.context.llm)
        elif c.claim_type == ClaimType.BODILY_INJURY.value:
            crew = create_bodily_injury_crew(c.context.llm)
        elif c.claim_type == ClaimType.PARTIAL_LOSS.value:
            crew = create_partial_loss_crew(c.context.llm)
        else:
            loss_state = c.claim_data_with_id.get("loss_state") or DEFAULT_STATE
            crew = create_total_loss_crew(c.context.llm, state=loss_state, use_rag=True)

        try:
            workflow_result = _kickoff_with_retry(crew, crew_inputs)
        except MidWorkflowEscalation as e:
            return _handle_mid_workflow_escalation(
                e,
                claim_id=c.claim_id,
                claim_type=c.claim_type,
                raw_output=c.raw_output,
                context=c.context,
                workflow_logger=logger,
                workflow_start_time=c.workflow_start_time,
                workflow_run_id=c.workflow_run_id,
            )

        _check_token_budget(c.claim_id, c.context.metrics, c.context.llm)
        _record_crew_usage_delta(
            c.claim_id,
            c.context.llm,
            c.context.metrics,
            c.claim_type,
            c.claim_type,
        )
        crew_latency = (time.time() - crew_start) * 1000
        routed_output = str(
            getattr(workflow_result, "raw", None)
            or getattr(workflow_result, "output", None)
            or str(workflow_result)
        )

        if workflow_stage_key == f"workflow:{ClaimType.REOPENED.value}":
            c.workflow_output = _combine_workflow_outputs(
                reopened_output,
                routed_output,
                label="Routed workflow output",
            )
        else:
            c.workflow_output = routed_output

        logger.log_event("crew_completed", crew=c.claim_type, latency_ms=crew_latency)
        c.extracted_payout = _extract_payout_from_workflow_result(workflow_result, c.claim_type)
        if c.extracted_payout is not None:
            c.claim_data_with_id["payout_amount"] = c.extracted_payout

        if c.claim_type == ClaimType.PARTIAL_LOSS.value:
            dispatch_repair_authorized_from_workflow_output(c.workflow_output, log=logger)
        return None

    def get_checkpoint_data(c: _WorkflowCtx) -> dict:
        cp_data: dict = {
            "workflow_output": c.workflow_output,
            "extracted_payout": c.extracted_payout,
        }
        if workflow_stage_key == f"workflow:{ClaimType.REOPENED.value}":
            cp_data["target_claim_type"] = c.claim_type
        return cp_data

    return _run_stage(
        ctx,
        workflow_stage_key,
        restore=restore,
        run=run,
        get_checkpoint_data=get_checkpoint_data,
    )


def _stage_task_creation(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the task planner crew to create follow-up tasks.

    Analyzes the routed claim and workflow output to generate actionable
    tasks for adjusters and downstream agents. Always runs regardless of
    claim type.
    """
    return _run_crew_stage(
        ctx,
        "task_creation",
        "task_planner",
        "task_creation_output",
        create_crew=lambda c: create_task_planner_crew(c.context.llm),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
        combine_label="Task planning output",
    )


def _stage_rental(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the rental reimbursement crew for partial loss claims.

    Only runs when claim_type is partial_loss. Combines rental output with
    ctx.workflow_output before settlement.
    """
    if ctx.claim_type != ClaimType.PARTIAL_LOSS.value:
        return None
    return _run_crew_stage(
        ctx,
        "rental",
        "rental",
        "rental_output",
        create_crew=lambda c: create_rental_crew(c.context.llm),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
        combine_label="Rental workflow output",
    )


def _stage_liability_determination(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the liability determination crew before settlement.

    Runs only for settlement-requiring claims. Persists liability_percentage and
    liability_basis to the claim after crew completes.
    """
    if not _requires_settlement(ctx.claim_type):
        return None

    def run_liability(c: _WorkflowCtx) -> dict | None:
        _check_token_budget(c.claim_id, c.context.metrics, c.context.llm)
        logger.log_event("crew_started", crew="liability_determination")
        start = time.time()
        loss_state = c.claim_data.get("loss_state") or DEFAULT_STATE
        crew = create_liability_determination_crew(c.context.llm, state=loss_state, use_rag=True)
        inputs = {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        }
        try:
            result = _kickoff_with_retry(crew, inputs)
        except MidWorkflowEscalation as e:
            return _handle_mid_workflow_escalation(
                e,
                claim_id=c.claim_id,
                claim_type=c.claim_type,
                raw_output=c.raw_output,
                context=c.context,
                workflow_logger=logger,
                workflow_start_time=c.workflow_start_time,
                prior_workflow_output=c.workflow_output,
                actor_id=c.actor_id,
                stage="liability_determination",
                payout_amount=c.extracted_payout,
                workflow_run_id=c.workflow_run_id,
            )
        _check_token_budget(c.claim_id, c.context.metrics, c.context.llm)
        _record_crew_usage_delta(
            c.claim_id,
            c.context.llm,
            c.context.metrics,
            "liability_determination",
            c.claim_type,
        )
        output_str = str(
            getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
        )
        logger.log_event(
            "crew_completed",
            crew="liability_determination",
            latency_ms=(time.time() - start) * 1000,
        )
        c._last_stage_output = output_str
        c.workflow_output = _combine_workflow_outputs(
            c.workflow_output, output_str, label="Liability determination output"
        )
        # Extract pydantic output and persist to claim
        tasks_output = getattr(result, "tasks_output", None)
        if tasks_output and isinstance(tasks_output, list) and len(tasks_output) > 0:
            last_task = tasks_output[-1]
            output = getattr(last_task, "pydantic", None) or getattr(last_task, "output", None)
            if isinstance(output, LiabilityDeterminationOutput):
                liab_pct = output.liability_percentage
                liab_basis = output.liability_basis or ""
                if liab_pct is not None or liab_basis:
                    c.context.repo.update_claim_liability(
                        c.claim_id,
                        liability_percentage=liab_pct,
                        liability_basis=liab_basis if liab_basis else None,
                    )
                    c.claim_data_with_id["liability_percentage"] = liab_pct
                    c.claim_data_with_id["liability_basis"] = liab_basis or None
        return None

    def restore(c: _WorkflowCtx, cp: dict) -> None:
        output = cp.get("liability_determination_output", "")
        if output:
            c.workflow_output = _combine_workflow_outputs(
                c.workflow_output, output, label="Liability determination output"
            )
        # Repopulate structured liability fields so downstream stages (settlement/subrogation) have them.
        claim = c.context.repo.get_claim(c.claim_id)
        if claim:
            if "liability_percentage" in claim:
                c.claim_data_with_id["liability_percentage"] = claim["liability_percentage"]
            if "liability_basis" in claim:
                c.claim_data_with_id["liability_basis"] = claim["liability_basis"]

    return _run_stage(
        ctx,
        "liability_determination",
        restore=restore,
        run=lambda c: run_liability(c),
        get_checkpoint_data=lambda c: {  # noqa: B008
            "liability_determination_output": getattr(c, "_last_stage_output", ""),
        },
    )


def _stage_settlement(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the settlement crew when required by claim type.

    Returns an early-return response dict on mid-workflow escalation.
    Populates ``ctx.workflow_output`` with the combined final output.
    """
    if not _requires_settlement(ctx.claim_type):
        return None
    return _run_crew_stage(
        ctx,
        "settlement",
        "settlement",
        "settlement_output",
        create_crew=lambda c: create_settlement_crew(c.context.llm, claim_type=c.claim_type),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
    )


def _stage_subrogation(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the subrogation crew after settlement when required by claim type.

    Populates ``ctx.workflow_output`` with the combined subrogation output.
    """
    if not _requires_settlement(ctx.claim_type):
        return None
    return _run_crew_stage(
        ctx,
        "subrogation",
        "subrogation",
        "subrogation_output",
        create_crew=lambda c: create_subrogation_crew(c.context.llm),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
        combine_label="Subrogation workflow output",
    )


def _stage_salvage(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the salvage crew after subrogation when claim is total_loss.

    Populates ``ctx.workflow_output`` with the combined salvage output.
    """
    if not _requires_salvage(ctx.claim_type):
        return None
    return _run_crew_stage(
        ctx,
        "salvage",
        "salvage",
        "salvage_output",
        create_crew=lambda c: create_salvage_crew(c.context.llm),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
        combine_label="Salvage workflow output",
    )


def _stage_after_action(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the after-action crew to compile a summary note and evaluate closure.

    Always runs regardless of claim type. Combines output with
    ``ctx.workflow_output`` so it is captured in the final workflow result.
    """
    return _run_crew_stage(
        ctx,
        "after_action",
        "after_action",
        "after_action_output",
        create_crew=lambda c: create_after_action_crew(c.context.llm),
        get_inputs=lambda c: {
            "claim_data": json.dumps({**c.claim_data_with_id, "claim_type": c.claim_type}),
            "workflow_output": c.workflow_output,
        },
        combine_label="After-action workflow output",
    )
