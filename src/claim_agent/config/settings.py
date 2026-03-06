"""Centralized configuration from environment variables with defaults."""

import os
from typing import Any


def _float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _tuple_float(key: str, default: tuple[float, float]) -> tuple[float, float]:
    raw = os.environ.get(key)
    if raw is None:
        return default
    parts = raw.replace(" ", "").split(",")
    if len(parts) != 2:
        return default
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Escalation (HITL)
# ---------------------------------------------------------------------------

def get_escalation_config() -> dict[str, Any]:
    """Escalation thresholds for human-in-the-loop review."""
    return {
        "confidence_threshold": _float("ESCALATION_CONFIDENCE_THRESHOLD", 0.7),
        "high_value_threshold": _float("ESCALATION_HIGH_VALUE_THRESHOLD", 10000.0),
        "similarity_ambiguous_range": _tuple_float(
            "ESCALATION_SIMILARITY_AMBIGUOUS_RANGE", (50.0, 80.0)
        ),
        "fraud_damage_vs_value_ratio": _float(
            "ESCALATION_FRAUD_DAMAGE_VS_VALUE_RATIO", 0.9
        ),
        "vin_claims_days": _int("ESCALATION_VIN_CLAIMS_DAYS", 90),
        "confidence_decrement_per_pattern": _float(
            "ESCALATION_CONFIDENCE_DECREMENT_PER_PATTERN", 0.15
        ),
        "description_overlap_threshold": _float(
            "ESCALATION_DESCRIPTION_OVERLAP_THRESHOLD", 0.1
        ),
    }


# ---------------------------------------------------------------------------
# Fraud detection
# ---------------------------------------------------------------------------

def get_fraud_config() -> dict[str, Any]:
    """Fraud detection thresholds and scores."""
    return {
        "multiple_claims_days": _int("FRAUD_MULTIPLE_CLAIMS_DAYS", 90),
        "multiple_claims_threshold": _int("FRAUD_MULTIPLE_CLAIMS_THRESHOLD", 2),
        "fraud_keyword_score": _int("FRAUD_KEYWORD_SCORE", 20),
        "multiple_claims_score": _int("FRAUD_MULTIPLE_CLAIMS_SCORE", 25),
        "timing_anomaly_score": _int("FRAUD_TIMING_ANOMALY_SCORE", 15),
        "damage_mismatch_score": _int("FRAUD_DAMAGE_MISMATCH_SCORE", 20),
        "high_risk_threshold": _int("FRAUD_HIGH_RISK_THRESHOLD", 50),
        "medium_risk_threshold": _int("FRAUD_MEDIUM_RISK_THRESHOLD", 30),
        "critical_risk_threshold": _int("FRAUD_CRITICAL_RISK_THRESHOLD", 75),
        "critical_indicator_count": _int("FRAUD_CRITICAL_INDICATOR_COUNT", 5),
    }


# ---------------------------------------------------------------------------
# Vehicle valuation and payout
# ---------------------------------------------------------------------------

DEFAULT_BASE_VALUE = _float("VALUATION_DEFAULT_BASE_VALUE", 12000)
DEPRECIATION_PER_YEAR = _float("VALUATION_DEPRECIATION_PER_YEAR", 500)
MIN_VEHICLE_VALUE = _float("VALUATION_MIN_VEHICLE_VALUE", 2000)
DEFAULT_DEDUCTIBLE = _int("VALUATION_DEFAULT_DEDUCTIBLE", 500)
MIN_PAYOUT_VEHICLE_VALUE = _float("VALUATION_MIN_PAYOUT_VEHICLE_VALUE", 100)


# ---------------------------------------------------------------------------
# Partial loss
# ---------------------------------------------------------------------------

PARTIAL_LOSS_THRESHOLD = _float("PARTIAL_LOSS_THRESHOLD", 0.75)
LABOR_HOURS_RNI_PER_PART = _float("PARTIAL_LOSS_LABOR_HOURS_RNI_PER_PART", 1.5)
LABOR_HOURS_PAINT_BODY = _float("PARTIAL_LOSS_LABOR_HOURS_PAINT_BODY", 2.0)
LABOR_HOURS_MIN = _float("PARTIAL_LOSS_LABOR_HOURS_MIN", 2.0)


# ---------------------------------------------------------------------------
# Token budgets and rate limits
# ---------------------------------------------------------------------------

MAX_TOKENS_PER_CLAIM = _int("CLAIM_AGENT_MAX_TOKENS_PER_CLAIM", 100_000)
MAX_LLM_CALLS_PER_CLAIM = _int("CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM", 50)


# ---------------------------------------------------------------------------
# Crew verbose mode
# ---------------------------------------------------------------------------

def get_crew_verbose() -> bool:
    """Whether CrewAI runs in verbose mode (default: True)."""
    raw = os.environ.get("CREWAI_VERBOSE", "true").strip().lower()
    return raw in ("true", "1", "yes")
