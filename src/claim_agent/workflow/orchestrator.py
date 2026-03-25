"""Top-level workflow orchestration: run_claim_workflow and supporting context."""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

import litellm
from sqlalchemy.exc import IntegrityError, OperationalError

from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.config import get_settings
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.payment_repository import (
    PaymentRepository,
    settlement_payee_and_party_id_from_claim_data,
)
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.payment import ClaimPaymentCreate, PayeeType, PaymentMethod
from claim_agent.models.stage_outputs import (
    CoverageVerificationResult,
    DuplicateDetectionResult,
    EconomicAnalysisResult,
    EscalationCheckResult,
    FraudPrescreeningResult,
    RouterStageResult,
)
from claim_agent.exceptions import ClaimNotFoundError, ClaimWorkflowTimeoutError, DomainValidationError
from claim_agent.db.constants import STATUS_FAILED, STATUS_PROCESSING
from claim_agent.models.claim import ClaimInput
from claim_agent.observability import claim_context, get_logger
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.observability.tracing import LiteLLMTracingCallback
from claim_agent.utils.sanitization import sanitize_claim_data
from claim_agent.workflow.budget import _record_crew_usage_delta
from claim_agent.workflow.helpers import (
    _checkpoint_keys_to_invalidate,
    _final_status,
)
from claim_agent.workflow.stages import (
    _stage_after_action,
    _stage_coverage_verification,
    _stage_duplicate_detection,
    _stage_economic_analysis,
    _stage_escalation_check,
    _stage_fraud_prescreening,
    _stage_liability_determination,
    _stage_rental,
    _stage_router,
    _stage_salvage,
    _stage_settlement,
    _stage_subrogation,
    _stage_task_creation,
    _stage_workflow_crew,
)

logger = get_logger(__name__)

# Protects append/remove of litellm.callbacks. We replace the list (never mutate
# in place), so litellm's iteration during LLM calls continues on the list it
# captured; risk of iteration races is low.
_callbacks_lock = threading.Lock()


REOPENED_EXTRA_FIELDS = ("prior_claim_id", "reopening_reason", "is_reopened")


def _normalize_claim_data(claim_data: dict) -> tuple[ClaimInput, dict]:
    """Sanitize and validate claim data, returning model + JSON-safe dict.

    This ensures numeric fields are coerced and extra fields are dropped before
    we pass data to LLM prompts or business logic. Preserves reopened-related
    fields (prior_claim_id, reopening_reason, is_reopened) for router recognition.
    """
    sanitized = sanitize_claim_data(claim_data)
    claim_input = ClaimInput.model_validate(sanitized)
    normalized = claim_input.model_dump(mode="json")
    for key in REOPENED_EXTRA_FIELDS:
        if key in sanitized and sanitized[key] is not None:
            normalized[key] = sanitized[key]
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
    is_resume_run: bool = False

    claim_type: str = ""
    router_confidence: float = 0.0
    router_reasoning: str = ""
    raw_output: str = ""
    workflow_output: str = ""
    extracted_payout: float | None = None
    _last_stage_output: str = ""

    coverage_result: CoverageVerificationResult | None = None
    economic_result: EconomicAnalysisResult | None = None
    fraud_prescreening_result: FraudPrescreeningResult | None = None
    duplicate_result: DuplicateDetectionResult | None = None
    router_result: RouterStageResult | None = None
    escalation_result: EscalationCheckResult | None = None


def _maybe_record_workflow_settlement_payment(
    *,
    claim_id: str,
    wf_ctx: _WorkflowCtx,
    workflow_run_id: str,
    claim_repo: ClaimRepository,
) -> None:
    """When enabled, create one authorized claim_payments row for extracted settlement payout."""
    if not get_settings().payment.auto_record_from_settlement:
        return
    payout = wf_ctx.extracted_payout
    if payout is None or payout <= 0:
        return
    payee, party_id = settlement_payee_and_party_id_from_claim_data(wf_ctx.claim_data_with_id)
    ext_ref = f"workflow_settlement:{workflow_run_id}"
    pdata = ClaimPaymentCreate(
        claim_id=claim_id,
        amount=float(payout),
        payee=payee,
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref=ext_ref,
        claim_party_id=party_id,
    )
    pay_repo = PaymentRepository(db_path=claim_repo.db_path)
    try:
        pay_repo.create_payment(
            pdata,
            actor_id=ACTOR_WORKFLOW,
            role="adjuster",
            skip_authority_check=True,
        )
    except (IntegrityError, OperationalError, DomainValidationError) as e:
        logger.warning(
            "Workflow settlement payment ledger insert failed (best-effort); continuing",
            extra={
                "claim_id": claim_id,
                "workflow_run_id": workflow_run_id,
                "error": str(e),
            },
        )


def run_claim_workflow(
    claim_data: dict,
    llm: LLMProtocol | None = None,
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

    _incident_date = claim_data.get("incident_date")
    if _incident_date is not None and hasattr(_incident_date, "isoformat"):
        _incident_date_str = _incident_date.isoformat()
    elif isinstance(_incident_date, str):
        _incident_date_str = _incident_date
    else:
        _incident_date_str = None

    with claim_context(
        claim_id=claim_id,
        policy_number=claim_data.get("policy_number"),
        vin=claim_data.get("vin"),
        incident_date=_incident_date_str,
        incident_latitude=claim_data.get("incident_latitude"),
        incident_longitude=claim_data.get("incident_longitude"),
    ):
        repo.update_claim_status(claim_id, STATUS_PROCESSING, actor_id=_actor)
        logger.log_event("workflow_started", status=STATUS_PROCESSING)
        
        db_parties = repo.get_claim_parties(claim_id)
        if db_parties:
            claim_data["parties"] = db_parties

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

            claim_data_with_id = {**claim_data, "claim_id": claim_id}
            inputs = {"claim_data": json.dumps(claim_data_with_id)}

            wf_ctx = _WorkflowCtx(
                claim_id=claim_id,
                claim_data=claim_data,
                claim_data_with_id=claim_data_with_id,
                inputs=inputs,
                similarity_score_for_escalation=None,
                context=ctx,
                workflow_run_id=workflow_run_id,
                workflow_start_time=workflow_start_time,
                actor_id=_actor,
                checkpoints=checkpoints,
                is_resume_run=resume_run_id is not None,
            )

            for stage_fn in (
                _stage_coverage_verification,
                _stage_economic_analysis,
                _stage_fraud_prescreening,
                _stage_duplicate_detection,
                _stage_router,
                _stage_escalation_check,
                _stage_workflow_crew,
                _stage_task_creation,
                _stage_rental,
                _stage_liability_determination,
                _stage_settlement,
                _stage_subrogation,
                _stage_salvage,
                _stage_after_action,
            ):
                _timeout_seconds = get_settings().claim_workflow_timeout_seconds
                _elapsed = time.time() - workflow_start_time
                if _elapsed >= _timeout_seconds:
                    raise ClaimWorkflowTimeoutError(claim_id, _elapsed, _timeout_seconds)
                early_return = stage_fn(wf_ctx)
                if early_return is not None:
                    return early_return

            current_claim = repo.get_claim(claim_id)
            current_status = current_claim.get("status") if current_claim else None
            from claim_agent.db.constants import STATUS_CLOSED

            already_closed = current_status == STATUS_CLOSED
            if already_closed:
                final_status = STATUS_CLOSED
            else:
                final_status = _final_status(wf_ctx.claim_type)
            repo.save_workflow_result(
                claim_id, wf_ctx.claim_type, wf_ctx.raw_output, wf_ctx.workflow_output
            )
            if not already_closed:
                repo.update_claim_status(
                    claim_id,
                    final_status,
                    details=wf_ctx.workflow_output[:500]
                    if len(wf_ctx.workflow_output) > 500
                    else wf_ctx.workflow_output,
                    claim_type=wf_ctx.claim_type,
                    payout_amount=wf_ctx.extracted_payout,
                    actor_id=_actor,
                )
                try:
                    _maybe_record_workflow_settlement_payment(
                        claim_id=claim_id,
                        wf_ctx=wf_ctx,
                        workflow_run_id=workflow_run_id,
                        claim_repo=repo,
                    )
                except Exception as payment_err:
                    logger.warning(
                        "Failed to auto-record settlement payment, but workflow completed successfully",
                        extra={"claim_id": claim_id, "error": str(payment_err)},
                    )

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_completed",
                status=final_status,
                duration_ms=workflow_duration,
            )

            _record_crew_usage_delta(
                claim_id=claim_id,
                llm=ctx.llm,
                metrics=metrics,
                crew="residual",
                claim_type=wf_ctx.claim_type or None,
            )

            metrics.end_claim(claim_id, status=final_status)
            record_claim_outcome(claim_id, final_status, (time.time() - workflow_start_time))
            metrics.log_claim_summary(claim_id)

            return {
                "claim_id": claim_id,
                "claim_type": wf_ctx.claim_type,
                "status": final_status,
                "router_output": wf_ctx.raw_output,
                "workflow_output": wf_ctx.workflow_output,
                "workflow_run_id": workflow_run_id,
                "summary": wf_ctx.workflow_output[:500] + "..."
                if len(wf_ctx.workflow_output) > 500
                else wf_ctx.workflow_output,
            }
        except Exception as e:
            details = str(e)
            if len(details) > 500:
                details = details[:500] + "..."
            repo.update_claim_status(
                claim_id,
                STATUS_FAILED,
                details=details,
                actor_id=_actor,
                skip_validation=True,
            )

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_failed",
                error=details,
                duration_ms=workflow_duration,
                level=logging.ERROR,
            )

            if isinstance(e, ClaimWorkflowTimeoutError):
                try:
                    from claim_agent.notifications.webhook import dispatch_webhook
                    dispatch_webhook(
                        "claim.timeout",
                        {
                            "claim_id": claim_id,
                            "elapsed_seconds": e.elapsed_seconds,
                            "timeout_seconds": e.timeout_seconds,
                            "reason": str(e),
                        },
                    )
                except Exception as webhook_err:
                    logger.warning(
                        "Timeout webhook dispatch failed (best-effort): %s",
                        webhook_err,
                        extra={"claim_id": claim_id},
                    )

            _record_crew_usage_delta(
                claim_id=claim_id,
                llm=ctx.llm,
                metrics=metrics,
                crew="residual",
                claim_type=getattr(wf_ctx, "claim_type", None) or None,
            )

            metrics.end_claim(claim_id, status="error")
            record_claim_outcome(claim_id, "error", (time.time() - workflow_start_time))
            metrics.log_claim_summary(claim_id)

            raise
        finally:
            with _callbacks_lock:  # protects list replacement, not litellm's iteration
                current_callbacks = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = [cb for cb in current_callbacks if cb is not litellm_callback]
