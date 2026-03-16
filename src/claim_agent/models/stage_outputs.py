"""Structured intermediate representations for workflow stage outputs.

Each model captures the typed contract produced by its corresponding
``_stage_*`` function in ``claim_agent.workflow.stages``.  Downstream
stages read from these models instead of reaching into the loosely-typed
``claim_data_with_id`` dict with string keys.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

EscalationPriority = Literal["low", "medium", "high", "critical"]


class EconomicAnalysisResult(BaseModel):
    """Output of ``_stage_economic_analysis``."""

    is_economic_total_loss: bool = False
    is_catastrophic_event: bool = False
    damage_indicates_total_loss: bool = False
    damage_is_repairable: bool = False
    vehicle_value: float | None = None
    damage_to_value_ratio: float | None = None
    high_value_claim: bool = False


class FraudPrescreeningResult(BaseModel):
    """Output of ``_stage_fraud_prescreening``."""

    pre_routing_fraud_indicators: list[str] = Field(default_factory=list)


class EnrichedDuplicate(BaseModel):
    """A single candidate duplicate enriched with similarity data."""

    claim_id: str | None = None
    incident_date: str | None = None
    incident_description: str = ""
    damage_description: str = ""
    damage_tags: list[str] = Field(default_factory=list)
    damage_type_match: bool = False
    days_difference: int | None = None
    description_similarity_score: float = 0.0


class DuplicateDetectionResult(BaseModel):
    """Output of ``_stage_duplicate_detection``."""

    existing_claims: list[EnrichedDuplicate] = Field(default_factory=list)
    damage_tags: list[str] = Field(default_factory=list)
    definitive_duplicate: bool = False
    similarity_score_for_escalation: float | None = None


class RouterStageResult(BaseModel):
    """Output of ``_stage_router``."""

    claim_type: str = ""
    router_confidence: float = 0.0
    router_reasoning: str = ""
    raw_output: str = ""


class EscalationCheckResult(BaseModel):
    """Output of ``_stage_escalation_check``."""

    needs_review: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)
    priority: EscalationPriority = "low"
    recommended_action: str = ""
    fraud_indicators: list[str] = Field(default_factory=list)


class CoverageVerificationResult(BaseModel):
    """Output of ``_stage_coverage_verification``.

    Exactly one of passed, denied, under_investigation must be True.
    """

    passed: bool = False
    denied: bool = False
    under_investigation: bool = False
    reason: str = ""
    details: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_mutually_exclusive_outcomes(self) -> "CoverageVerificationResult":
        outcomes = sum([self.passed, self.denied, self.under_investigation])
        if outcomes != 1:
            raise ValueError(
                f"Exactly one of passed/denied/under_investigation must be True; got {outcomes}"
            )
        return self
