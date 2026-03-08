"""Top-level workflow orchestration: run_claim_workflow and supporting context."""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

import litellm

from claim_agent.config.llm import get_llm
from claim_agent.config.settings import (
    DUPLICATE_DAYS_WINDOW,
    DUPLICATE_SIMILARITY_THRESHOLD,
    DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE,
    HIGH_VALUE_DAMAGE_THRESHOLD,
    HIGH_VALUE_VEHICLE_THRESHOLD,
    PRE_ROUTING_FRAUD_DAMAGE_RATIO,
)
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.db.constants import STATUS_FAILED, STATUS_PROCESSING
from claim_agent.models.claim import ClaimInput
from claim_agent.observability import claim_context, get_logger
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.observability.tracing import LiteLLMTracingCallback
from claim_agent.tools.escalation_logic import detect_fraud_indicators_impl
from claim_agent.utils.sanitization import sanitize_claim_data
from claim_agent.workflow.budget import _record_crew_llm_usage
from claim_agent.workflow.claim_analysis import (
    _check_economic_total_loss,
    _filter_weak_fraud_indicators,
)
from claim_agent.workflow.duplicate_detection import (
    _check_for_duplicates,
    _damage_tags_overlap,
    _extract_damage_tags,
)
from claim_agent.workflow.helpers import (
    _checkpoint_keys_to_invalidate,
    _final_status,
)
from claim_agent.workflow.stages import (
    _stage_escalation_check,
    _stage_router,
    _stage_settlement,
    _stage_workflow_crew,
)

logger = get_logger(__name__)

# Protects append/remove of litellm.callbacks. We replace the list (never mutate
# in place), so litellm's iteration during LLM calls continues on the list it
# captured; risk of iteration races is low.
_callbacks_lock = threading.Lock()


def _normalize_claim_data(claim_data: dict) -> tuple[ClaimInput, dict]:
    """Sanitize and validate claim data, returning model + JSON-safe dict.

    This ensures numeric fields are coerced and extra fields are dropped before
    we pass data to LLM prompts or business logic.
    """
    sanitized = sanitize_claim_data(claim_data)
    claim_input = ClaimInput.model_validate(sanitized)
    normalized = claim_input.model_dump(mode="json")
    return claim_input, normalized


@dataclass
class _WorkflowCtx:
    """Shared mutable context threaded through workflow stages."""

    claim_id: str
    claim_data: dict
    claim_data_with_id: dict
    inputs: dict
    similarity_score_for_escalation: float | None
    context: ClaimContext
    workflow_run_id: str
    workflow_start_time: float
    actor_id: str
    checkpoints: dict[str, str] = field(default_factory=dict)

    claim_type: str = ""
    router_confidence: float = 0.0
    router_reasoning: str = ""
    raw_output: str = ""
    workflow_output: str = ""
    extracted_payout: float | None = None


def run_claim_workflow(
    claim_data: dict,
    llm=None,
    existing_claim_id: str | None = None,
    *,
    actor_id: str | None = None,
    resume_run_id: str | None = None,
    from_stage: str | None = None,
    ctx: ClaimContext | None = None,
) -> dict:
    """Run the full claim workflow: classify with router crew, then run the appropriate workflow crew.

    Persists claim to SQLite, logs state changes, and saves workflow result.

    Supports resumable execution via checkpoints.  When *resume_run_id* is
    provided, completed stages are skipped using cached outputs.  When
    *from_stage* is also given, checkpoints at and after that stage are
    invalidated so execution restarts from that point.

    Args:
        claim_data: dict with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                   incident_date, incident_description, damage_description, estimated_damage (optional).
        llm: Optional LLM instance (legacy). Prefer passing via *ctx*.
        existing_claim_id: if set, re-run workflow for this claim (no new claim created).
        actor_id: Actor to record in audit log entries.
        resume_run_id: Reuse checkpoints from this workflow run (resume mode).
        from_stage: When resuming, invalidate checkpoints at and after this stage
            and re-execute from here.  One of ``WORKFLOW_STAGES``.
        ctx: Dependency-injection context. When ``None``, one is built from defaults.

    Returns:
        dict with claim_id, claim_type, status, summary, workflow_output, and
        workflow_run_id (for future resume).
    """
    workflow_start_time = time.time()
    _actor = actor_id if actor_id is not None else ACTOR_WORKFLOW

    _llm = llm or (ctx.llm if ctx else None) or get_llm()
    claim_input, claim_data = _normalize_claim_data(claim_data)
    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=_llm)
    elif ctx.llm is None or llm is not None:
        # Apply _llm: fill in when ctx has none, or override when explicit llm was passed
        ctx = ClaimContext(
            repo=ctx.repo,
            adjuster_service=ctx.adjuster_service,
            adapters=ctx.adapters,
            metrics=ctx.metrics,
            llm=_llm,
        )
    repo = ctx.repo
    metrics = ctx.metrics

    if existing_claim_id:
        claim_id = existing_claim_id
        if repo.get_claim(claim_id) is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        logger.info("Reprocessing existing claim", extra={"claim_id": claim_id})
    else:
        claim_id = repo.create_claim(claim_input, actor_id=_actor)
        logger.info(
            "Created new claim",
            extra={
                "claim_id": claim_id,
                "extra_data": {
                    "event": "claim_created",
                    "policy_number": claim_data.get("policy_number"),
                    "vin": claim_data.get("vin"),
                },
            },
        )

    metrics.start_claim(claim_id)

    with claim_context(
        claim_id=claim_id,
        policy_number=claim_data.get("policy_number"),
        vin=claim_data.get("vin"),
    ):
        repo.update_claim_status(claim_id, STATUS_PROCESSING, actor_id=_actor)
        logger.log_event("workflow_started", status=STATUS_PROCESSING)

        litellm_callback = LiteLLMTracingCallback(
            claim_id=claim_id,
            metrics_collector=metrics,
        )
        with _callbacks_lock:  # protects list replacement, not litellm's iteration
            prev_litellm_callbacks = list(getattr(litellm, "callbacks", None) or [])
            litellm.callbacks = prev_litellm_callbacks + [litellm_callback]

        try:
            if from_stage and not resume_run_id:
                logger.warning(
                    "from_stage=%s ignored because resume_run_id is not set",
                    from_stage,
                    extra={"claim_id": claim_id},
                )
                from_stage = None

            workflow_run_id = resume_run_id or uuid.uuid4().hex
            checkpoints: dict[str, str] = {}
            if resume_run_id:
                checkpoints = repo.get_task_checkpoints(claim_id, workflow_run_id)
                if from_stage:
                    keys_to_drop = _checkpoint_keys_to_invalidate(from_stage, checkpoints)
                    if keys_to_drop:
                        repo.delete_task_checkpoints(claim_id, workflow_run_id, keys_to_drop)
                        for k in keys_to_drop:
                            checkpoints.pop(k, None)
                logger.info(
                    "Resuming workflow run %s with %d checkpoint(s)",
                    workflow_run_id,
                    len(checkpoints),
                    extra={"claim_id": claim_id},
                )

            economic_check = _check_economic_total_loss(claim_data)
            claim_data_with_id = {**claim_data, "claim_id": claim_id}
            claim_data_with_id["is_economic_total_loss"] = economic_check.get("is_economic_total_loss", False)
            claim_data_with_id["is_catastrophic_event"] = economic_check.get("is_catastrophic_event", False)
            claim_data_with_id["damage_indicates_total_loss"] = economic_check.get("damage_indicates_total_loss", False)
            claim_data_with_id["damage_is_repairable"] = economic_check.get("damage_is_repairable", False)
            claim_data_with_id["vehicle_value"] = economic_check.get("vehicle_value")
            claim_data_with_id["damage_to_value_ratio"] = economic_check.get("damage_to_value_ratio")

            is_catastrophic = economic_check.get("is_catastrophic_event", False)
            damage_indicates_total = economic_check.get("damage_indicates_total_loss", False)

            if (economic_check.get("damage_to_value_ratio") or 0) > PRE_ROUTING_FRAUD_DAMAGE_RATIO and not is_catastrophic and not damage_indicates_total:
                fraud_result = detect_fraud_indicators_impl(claim_data, ctx=ctx)
                try:
                    fraud_data = json.loads(fraud_result)
                except (json.JSONDecodeError, TypeError):
                    fraud_data = {}
                indicators = fraud_data if isinstance(fraud_data, list) else (fraud_data.get("indicators", []) if isinstance(fraud_data, dict) else [])
                if indicators:
                    meaningful_indicators = _filter_weak_fraud_indicators(indicators)
                    if meaningful_indicators:
                        claim_data_with_id["pre_routing_fraud_indicators"] = meaningful_indicators

            est_damage = claim_data.get("estimated_damage")
            vehicle_value = economic_check.get("vehicle_value")
            is_high_value = (
                (est_damage is not None and est_damage > HIGH_VALUE_DAMAGE_THRESHOLD)
                or (vehicle_value is not None and vehicle_value > HIGH_VALUE_VEHICLE_THRESHOLD)
            )
            if is_high_value:
                claim_data_with_id["high_value_claim"] = True

            existing_claims = _check_for_duplicates(claim_data, current_claim_id=claim_id, ctx=ctx)
            similarity_score_for_escalation = None
            if existing_claims:
                from claim_agent.tools.claims_logic import compute_similarity_score_impl
                current_incident = claim_data.get("incident_description", "") or ""
                current_damage = claim_data.get("damage_description", "") or ""
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
                            claim_id,
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
                    if similarity_score_for_escalation is None or similarity_score > similarity_score_for_escalation:
                        similarity_score_for_escalation = similarity_score

                claim_data_with_id["existing_claims_for_vin"] = enriched_claims
                claim_data_with_id["damage_tags"] = sorted(current_damage_tags)
                is_high_value = claim_data_with_id.get("high_value_claim", False)
                sim_threshold = DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE if is_high_value else DUPLICATE_SIMILARITY_THRESHOLD
                definitive_duplicate = any(
                    (e.get("description_similarity_score") or 0) >= sim_threshold
                    and e.get("days_difference", 999) <= DUPLICATE_DAYS_WINDOW
                    and e.get("damage_type_match")
                    for e in enriched_claims
                )
                claim_data_with_id["definitive_duplicate"] = definitive_duplicate
            else:
                similarity_score_for_escalation = None
                claim_data_with_id["definitive_duplicate"] = False
            inputs = {"claim_data": json.dumps(claim_data_with_id) if isinstance(claim_data_with_id, dict) else claim_data_with_id}
            claim_data_str = inputs["claim_data"] if isinstance(inputs["claim_data"], str) else json.dumps(inputs["claim_data"])
            logger.debug(
                "router_input_size claim_id=%s payload_chars=%s existing_claims_count=%s",
                claim_id,
                len(claim_data_str),
                len(claim_data_with_id.get("existing_claims_for_vin") or []),
            )

            wf_ctx = _WorkflowCtx(
                claim_id=claim_id,
                claim_data=claim_data,
                claim_data_with_id=claim_data_with_id,
                inputs=inputs,
                similarity_score_for_escalation=similarity_score_for_escalation,
                context=ctx,
                workflow_run_id=workflow_run_id,
                workflow_start_time=workflow_start_time,
                actor_id=_actor,
                checkpoints=checkpoints,
            )

            for stage_fn in (_stage_router, _stage_escalation_check, _stage_workflow_crew, _stage_settlement):
                early_return = stage_fn(wf_ctx)
                if early_return is not None:
                    return early_return

            final_status = _final_status(wf_ctx.claim_type)
            repo.save_workflow_result(claim_id, wf_ctx.claim_type, wf_ctx.raw_output, wf_ctx.workflow_output)
            repo.update_claim_status(
                claim_id,
                final_status,
                details=wf_ctx.workflow_output[:500] if len(wf_ctx.workflow_output) > 500 else wf_ctx.workflow_output,
                claim_type=wf_ctx.claim_type,
                payout_amount=wf_ctx.extracted_payout,
                actor_id=_actor,
            )

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_completed",
                status=final_status,
                duration_ms=workflow_duration,
            )

            _record_crew_llm_usage(claim_id=claim_id, llm=ctx.llm, metrics=metrics)

            metrics.end_claim(claim_id, status=final_status)
            record_claim_outcome(
                claim_id, final_status, (time.time() - workflow_start_time)
            )
            metrics.log_claim_summary(claim_id)

            return {
                "claim_id": claim_id,
                "claim_type": wf_ctx.claim_type,
                "status": final_status,
                "router_output": wf_ctx.raw_output,
                "workflow_output": wf_ctx.workflow_output,
                "workflow_run_id": workflow_run_id,
                "summary": wf_ctx.workflow_output[:500] + "..." if len(wf_ctx.workflow_output) > 500 else wf_ctx.workflow_output,
            }
        except Exception as e:
            details = str(e)
            if len(details) > 500:
                details = details[:500] + "..."
            repo.update_claim_status(claim_id, STATUS_FAILED, details=details, actor_id=_actor)

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_failed",
                error=details,
                duration_ms=workflow_duration,
                level=logging.ERROR,
            )

            _record_crew_llm_usage(claim_id=claim_id, llm=ctx.llm, metrics=metrics)

            metrics.end_claim(claim_id, status="error")
            record_claim_outcome(
                claim_id, "error", (time.time() - workflow_start_time)
            )
            metrics.log_claim_summary(claim_id)

            raise
        finally:
            with _callbacks_lock:  # protects list replacement, not litellm's iteration
                current_callbacks = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = [cb for cb in current_callbacks if cb is not litellm_callback]
