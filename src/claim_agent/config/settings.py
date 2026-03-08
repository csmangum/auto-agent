"""Centralized configuration from environment variables with defaults."""

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)


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
# Router confidence
# ---------------------------------------------------------------------------

def get_router_config() -> dict[str, Any]:
    """Router classification thresholds and behavior."""
    return {
        "confidence_threshold": _float("ROUTER_CONFIDENCE_THRESHOLD", 0.7),
        "validation_enabled": os.environ.get("ROUTER_VALIDATION_ENABLED", "false").strip().lower() in ("true", "1", "yes"),
    }


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
# Duplicate detection
# ---------------------------------------------------------------------------

DUPLICATE_SIMILARITY_THRESHOLD = _int("DUPLICATE_SIMILARITY_THRESHOLD", 40)
DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE = _int("DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE", 60)
DUPLICATE_DAYS_WINDOW = _int("DUPLICATE_DAYS_WINDOW", 3)

# ---------------------------------------------------------------------------
# High-value claim thresholds
# ---------------------------------------------------------------------------

HIGH_VALUE_DAMAGE_THRESHOLD = _int("HIGH_VALUE_DAMAGE_THRESHOLD", 25_000)
HIGH_VALUE_VEHICLE_THRESHOLD = _int("HIGH_VALUE_VEHICLE_THRESHOLD", 50_000)

# ---------------------------------------------------------------------------
# Pre-routing fraud
# ---------------------------------------------------------------------------

PRE_ROUTING_FRAUD_DAMAGE_RATIO = _float("PRE_ROUTING_FRAUD_DAMAGE_RATIO", 0.9)

# ---------------------------------------------------------------------------
# Escalation SLA hours (by priority)
# ---------------------------------------------------------------------------

ESCALATION_SLA_HOURS_CRITICAL = _int("ESCALATION_SLA_HOURS_CRITICAL", 24)
ESCALATION_SLA_HOURS_HIGH = _int("ESCALATION_SLA_HOURS_HIGH", 24)
ESCALATION_SLA_HOURS_MEDIUM = _int("ESCALATION_SLA_HOURS_MEDIUM", 48)
ESCALATION_SLA_HOURS_LOW = _int("ESCALATION_SLA_HOURS_LOW", 72)

# ---------------------------------------------------------------------------
# Token budgets and rate limits
# ---------------------------------------------------------------------------

MAX_TOKENS_PER_CLAIM = _int("CLAIM_AGENT_MAX_TOKENS_PER_CLAIM", 100_000)
MAX_LLM_CALLS_PER_CLAIM = _int("CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM", 50)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_api_keys_config() -> dict[str, str]:
    """API keys mapping key -> role. From API_KEYS (key:role,key:role) or CLAIMS_API_KEY (single admin key)."""
    api_keys_raw = os.environ.get("API_KEYS", "").strip()
    if api_keys_raw:
        result: dict[str, str] = {}
        for part in api_keys_raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                key, role = part.split(":", 1)
                result[key.strip()] = role.strip()
            else:
                result[part] = "admin"
        return result
    claims_key = os.environ.get("CLAIMS_API_KEY", "").strip()
    if claims_key:
        return {claims_key: "admin"}
    return {}


def get_jwt_secret() -> str | None:
    """JWT secret for verifying Bearer tokens. None if not configured."""
    raw = os.environ.get("JWT_SECRET", "").strip()
    return raw if raw else None


# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------

def get_mask_pii() -> bool:
    """Whether to mask PII (policy_number, vin) in logs and metrics. Default: True (production-safe)."""
    raw = os.environ.get("CLAIM_AGENT_MASK_PII", "true").strip().lower()
    return raw in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Data retention
# ---------------------------------------------------------------------------

def get_retention_period_years() -> int:
    """Retention period in years from env, compliance config, or default (5)."""
    raw = os.environ.get("RETENTION_PERIOD_YEARS", "").strip()
    if raw:
        try:
            value = int(raw)
            if value < 1:
                _log.warning(
                    "RETENTION_PERIOD_YEARS must be >= 1 (got %r); using default 5.",
                    raw,
                )
            else:
                return value
        except ValueError:
            _log.warning(
                "RETENTION_PERIOD_YEARS is set but invalid (%r); using compliance/default.",
                raw,
            )
    try:
        from claim_agent.data.loader import get_compliance_retention_years

        compliance_years = get_compliance_retention_years()
        if compliance_years is not None:
            return compliance_years
    except (ImportError, TypeError, ValueError, KeyError) as e:
        _log.warning(
            "Could not load retention period from compliance config: %s; using default 5 years.",
            e,
        )
    return 5


# ---------------------------------------------------------------------------
# Crew verbose mode
# ---------------------------------------------------------------------------

def get_crew_verbose() -> bool:
    """Whether CrewAI runs in verbose mode (default: True)."""
    raw = os.environ.get("CREWAI_VERBOSE", "true").strip().lower()
    return raw in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def get_webhook_config() -> dict[str, Any]:
    """Webhook configuration for outbound notifications."""
    urls_raw = os.environ.get("WEBHOOK_URLS", "").strip() or os.environ.get("WEBHOOK_URL", "").strip()
    urls = [u.strip() for u in urls_raw.split(",") if u.strip()] if urls_raw else []
    raw = os.environ.get("WEBHOOK_ENABLED", "true").strip().lower()
    enabled = raw in ("true", "1", "yes")
    return {
        "urls": urls,
        "secret": os.environ.get("WEBHOOK_SECRET", "").strip(),
        "max_retries": _int("WEBHOOK_MAX_RETRIES", 5),
        "enabled": enabled,
        "shop_url": os.environ.get("WEBHOOK_SHOP_URL", "").strip() or None,
        "dead_letter_path": os.environ.get("WEBHOOK_DEAD_LETTER_PATH", "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Claimant notifications (optional)
# ---------------------------------------------------------------------------

def get_notification_config() -> dict[str, Any]:
    """Claimant notification configuration (email/SMS). Stub for now."""
    raw_email = os.environ.get("NOTIFICATION_EMAIL_ENABLED", "false").strip().lower()
    raw_sms = os.environ.get("NOTIFICATION_SMS_ENABLED", "false").strip().lower()
    return {
        "email_enabled": raw_email in ("true", "1", "yes"),
        "sms_enabled": raw_sms in ("true", "1", "yes"),
    }


# ---------------------------------------------------------------------------
# Adapter backends
# ---------------------------------------------------------------------------

ADAPTER_ENV_KEYS: dict[str, str] = {
    "policy": "POLICY_ADAPTER",
    "valuation": "VALUATION_ADAPTER",
    "repair_shop": "REPAIR_SHOP_ADAPTER",
    "parts": "PARTS_ADAPTER",
    "siu": "SIU_ADAPTER",
}

VALID_ADAPTER_BACKENDS: frozenset[str] = frozenset({"mock", "stub"})


def get_adapter_backend(adapter_name: str) -> str:
    """Return the configured backend for *adapter_name* (default: ``mock``)."""
    env_key = ADAPTER_ENV_KEYS.get(adapter_name, f"{adapter_name.upper()}_ADAPTER")
    raw = os.environ.get(env_key)
    if raw is None:
        return "mock"
    backend = raw.strip().lower()
    return backend or "mock"
