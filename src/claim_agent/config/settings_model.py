"""Pydantic Settings model for centralized configuration.

All configuration is loaded from environment variables (and .env) at startup.
Use get_settings() to access the singleton instance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)


def _default_project_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------


class RouterConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROUTER_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    confidence_threshold: float = 0.7
    validation_enabled: bool = False

    @field_validator("confidence_threshold", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.7


class CoverageConfig(BaseSettings):
    """FNOL coverage verification: gate before routing."""

    model_config = SettingsConfigDict(
        env_prefix="COVERAGE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = True
    deny_when_deductible_exceeds_damage: bool = False
    require_incident_location: bool = False


def _parse_similarity_range_str(s: str) -> tuple[float, float]:
    """Parse '50,80' or '40,90' format to tuple."""
    parts = s.replace(" ", "").split(",")
    if len(parts) == 2:
        try:
            return (float(parts[0]), float(parts[1]))
        except (ValueError, TypeError):
            pass
    return (50.0, 80.0)


class EscalationConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESCALATION_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    confidence_threshold: float = 0.7
    high_value_threshold: float = 10000.0
    similarity_ambiguous_range_raw: str = Field(
        default="50,80",
        validation_alias="ESCALATION_SIMILARITY_AMBIGUOUS_RANGE",
    )
    fraud_damage_vs_value_ratio: float = 0.9
    vin_claims_days: int = 90
    confidence_decrement_per_pattern: float = 0.15
    description_overlap_threshold: float = 0.1
    use_agent: bool = True
    sla_hours_critical: int = 24
    sla_hours_high: int = 24
    sla_hours_medium: int = 48
    sla_hours_low: int = 72

    @field_validator("confidence_threshold", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.7

    @property
    def similarity_ambiguous_range(self) -> tuple[float, float]:
        return _parse_similarity_range_str(self.similarity_ambiguous_range_raw)


class FraudConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRAUD_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    multiple_claims_days: int = 90
    multiple_claims_threshold: int = 2
    fraud_keyword_score: int = 20
    multiple_claims_score: int = 25
    timing_anomaly_score: int = 15
    damage_mismatch_score: int = 20
    high_risk_threshold: int = 50
    medium_risk_threshold: int = 30
    critical_risk_threshold: int = 75
    critical_indicator_count: int = 5
    velocity_window_days: int = 30
    velocity_claim_threshold: int = 2
    velocity_score: int = 20
    geographic_anomaly_score: int = 15
    provider_ring_threshold: int = 2
    provider_ring_score: int = 20
    graph_max_depth: int = 2
    graph_max_nodes: int = 100
    graph_cluster_score: int = 25
    graph_high_risk_link_threshold: int = 2
    graph_high_risk_score: int = 20
    staged_pattern_score: int = 20
    claimsearch_match_threshold: int = 2
    claimsearch_match_score: int = 25
    photo_exif_anomaly_score: int = 10

    @field_validator("multiple_claims_days", mode="before")
    @classmethod
    def _coerce_multiple_claims_days(cls, v: Any) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            return 90

    @field_validator(
        "velocity_window_days",
        "velocity_claim_threshold",
        "velocity_score",
        "geographic_anomaly_score",
        "provider_ring_threshold",
        "provider_ring_score",
        "graph_max_depth",
        "graph_max_nodes",
        "graph_cluster_score",
        "graph_high_risk_link_threshold",
        "graph_high_risk_score",
        "staged_pattern_score",
        "claimsearch_match_threshold",
        "claimsearch_match_score",
        "photo_exif_anomaly_score",
        mode="before",
    )
    @classmethod
    def _coerce_positive_int(cls, v: Any, info: ValidationInfo) -> int:
        defaults = {
            "velocity_window_days": 30,
            "velocity_claim_threshold": 2,
            "velocity_score": 20,
            "geographic_anomaly_score": 15,
            "provider_ring_threshold": 2,
            "provider_ring_score": 20,
            "graph_max_depth": 2,
            "graph_max_nodes": 100,
            "graph_cluster_score": 25,
            "graph_high_risk_link_threshold": 2,
            "graph_high_risk_score": 20,
            "staged_pattern_score": 20,
            "claimsearch_match_threshold": 2,
            "claimsearch_match_score": 25,
            "photo_exif_anomaly_score": 10,
        }
        fallback = defaults.get(info.field_name or "", 1)
        try:
            value = int(v)
            return value if value > 0 else fallback
        except (ValueError, TypeError):
            return fallback


class ValuationConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VALUATION_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    default_base_value: float = 12000
    depreciation_per_year: float = 500
    min_vehicle_value: float = 2000
    default_deductible: int = 500
    min_payout_vehicle_value: float = 100


class ReserveConfig(BaseSettings):
    """Reserve management: authority limits and FNOL behavior."""

    model_config = SettingsConfigDict(
        env_prefix="RESERVE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    adjuster_limit: float = 10000.0
    supervisor_limit: float = 50000.0
    #: Max reserve for executive role; 0 or negative means no cap (unlimited).
    executive_limit: float = 0.0
    initial_reserve_from_estimated_damage: bool = True
    #: off | block | warn — gate on transitions to closed/settled (see state_machine)
    close_settle_adequacy_gate: str = "warn"

    @field_validator("adjuster_limit", mode="before")
    @classmethod
    def _coerce_adjuster_limit(cls, v: Any) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return 10000.0

    @field_validator("supervisor_limit", mode="before")
    @classmethod
    def _coerce_supervisor_limit(cls, v: Any) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return 50000.0

    @field_validator("executive_limit", mode="before")
    @classmethod
    def _coerce_executive_limit(cls, v: Any) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    @field_validator("initial_reserve_from_estimated_damage", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("close_settle_adequacy_gate", mode="before")
    @classmethod
    def _norm_close_settle_gate(cls, v: Any) -> str:
        s = str(v).strip().lower() if v is not None else "warn"
        if s in ("off", "block", "warn"):
            return s
        return "warn"


class PaymentConfig(BaseSettings):
    """Payment authority limits: adjuster, supervisor, executive."""

    model_config = SettingsConfigDict(
        env_prefix="PAYMENT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    adjuster_limit: float = 5000.0
    supervisor_limit: float = 25000.0
    executive_limit: float = 100000.0
    auto_record_from_settlement: bool = False

    @field_validator("auto_record_from_settlement", mode="before")
    @classmethod
    def _parse_payment_auto_record(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator(
        "adjuster_limit", "supervisor_limit", "executive_limit", mode="before"
    )
    @classmethod
    def _coerce_limit(cls, v: Any, info: ValidationInfo) -> float:
        defaults = {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 25000.0,
            "executive_limit": 100000.0,
        }
        try:
            return float(v)
        except (ValueError, TypeError):
            return defaults.get(info.field_name or "adjuster_limit", 5000.0)


class PartialLossConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PARTIAL_LOSS_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    threshold: float = 0.75
    labor_hours_rni_per_part: float = 1.5
    labor_hours_paint_body: float = 2.0
    labor_hours_min: float = 2.0
    betterment_enabled: bool = False
    betterment_min_vehicle_age_years: int = 5
    betterment_depreciation_rate_per_year: float = 0.005


class WebhookConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    urls_raw: str = Field(default="", validation_alias="WEBHOOK_URLS")
    url: str = Field(default="", validation_alias="WEBHOOK_URL")
    secret: str = ""
    max_retries: int = 5
    enabled: bool = True
    shop_url: str | None = None
    dead_letter_path: str | None = None

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_enabled(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @property
    def urls(self) -> list[str]:
        """Parsed URL list from WEBHOOK_URLS, falling back to WEBHOOK_URL."""
        raw = self.urls_raw or self.url
        if not raw or not raw.strip():
            return []
        return [u.strip() for u in raw.split(",") if u.strip()]


class NotificationConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTIFICATION_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    email_enabled: bool = False
    sms_enabled: bool = False

    @field_validator("email_enabled", "sms_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class DiaryConfig(BaseSettings):
    """Calendar/diary system: escalation and auto-create."""

    model_config = SettingsConfigDict(
        env_prefix="DIARY_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    auto_create_on_status_change: bool = True
    escalation_hours_before_supervisor: int = Field(
        default=24,
        ge=0,
        description="Hours after overdue notification before escalating to supervisor",
    )


class TracingConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_prefix="",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    langsmith_enabled: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="claim-agent", validation_alias="LANGSMITH_PROJECT")
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com", validation_alias="LANGSMITH_ENDPOINT"
    )
    trace_llm_calls: bool = Field(default=True, validation_alias="CLAIM_AGENT_TRACE_LLM")
    trace_tool_calls: bool = Field(default=True, validation_alias="CLAIM_AGENT_TRACE_TOOLS")
    log_prompts: bool = Field(default=False, validation_alias="CLAIM_AGENT_LOG_PROMPTS")
    log_responses: bool = Field(default=False, validation_alias="CLAIM_AGENT_LOG_RESPONSES")

    # OpenTelemetry (alongside LangSmith)
    otel_enabled: bool = Field(default=False, validation_alias="OTEL_TRACING")
    otel_service_name: str = Field(default="claim-agent", validation_alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    @field_validator(
        "langsmith_enabled", "trace_llm_calls", "trace_tool_calls", "log_prompts", "log_responses",
        "otel_enabled",
        mode="before",
    )
    @classmethod
    def _parse_bool_env(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class LoggingConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLAIM_AGENT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    log_format: str = "human"
    log_level: str = "INFO"
    mask_pii: bool = True


class PathsConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    claims_db_path: str = Field(
        default="data/claims.db", validation_alias="CLAIMS_DB_PATH"
    )
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description="PostgreSQL URL. If set, use PostgreSQL; else use SQLite at claims_db_path.",
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias="REDIS_URL",
        description="Redis URL for rate limiting. If set, use Redis backend; else in-memory.",
    )

    @field_validator("database_url", "redis_url", mode="before")
    @classmethod
    def _normalize_url(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None
    fresh_claims_db_on_startup: bool = Field(
        default=False,
        validation_alias="FRESH_CLAIMS_DB_ON_STARTUP",
    )
    run_migrations_on_startup: bool = Field(
        default=True,
        validation_alias="RUN_MIGRATIONS_ON_STARTUP",
        description="Run alembic upgrade head on API startup when using PostgreSQL. Set to false to run migrations as a separate deploy step.",
    )

    @field_validator("fresh_claims_db_on_startup", "run_migrations_on_startup", mode="before")
    @classmethod
    def _parse_bool_env(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")
    mock_db_path: str = Field(
        default="data/mock_db.json", validation_alias="MOCK_DB_PATH"
    )
    ca_compliance_path: str = Field(
        default="data/california_auto_compliance.json",
        validation_alias="CA_COMPLIANCE_PATH",
    )
    state_retention_path: str = Field(
        default="data/state_retention_periods.json",
        validation_alias="STATE_RETENTION_PATH",
        description="Path to state-specific retention periods JSON",
    )
    attachment_storage_path: str = Field(
        default="data/attachments", validation_alias="ATTACHMENT_STORAGE_PATH"
    )


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    api_base: str = Field(default="", validation_alias="OPENAI_API_BASE")
    model_name: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL_NAME")
    vision_model: str = Field(default="gpt-4o", validation_alias="OPENAI_VISION_MODEL")
    fallback_models: str = Field(
        default="",
        validation_alias="OPENAI_FALLBACK_MODELS",
        description="Comma-separated fallback models when primary is down or over budget",
    )

    def get_fallback_chain(self) -> list[str]:
        """Return [primary, fallback1, fallback2, ...] for model fallback strategy."""
        primary = (self.model_name or "gpt-4o-mini").strip()
        if not self.fallback_models.strip():
            return [primary]
        fallbacks = [m.strip() for m in self.fallback_models.split(",") if m.strip()]
        return [primary] + fallbacks


_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    api_keys_raw: str = Field(default="", validation_alias="API_KEYS")
    claims_api_key: str = Field(default="", validation_alias="CLAIMS_API_KEY")
    jwt_secret_raw: str = Field(default="", validation_alias="JWT_SECRET")
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")
    trust_forwarded_for: bool = Field(default=False, validation_alias="TRUST_FORWARDED_FOR")

    @field_validator("jwt_secret_raw", mode="after")
    @classmethod
    def _validate_jwt_key_length(cls, v: str) -> str:
        min_len = 32
        stripped = v.strip()
        if stripped and len(stripped) < min_len:
            raise ValueError(
                f"JWT_SECRET must be at least {min_len} characters "
                f"for HS256 (RFC 7518 Section 3.2). Got {len(stripped)} characters."
            )
        return v

    @property
    def api_keys(self) -> dict[str, str]:
        raw = self.api_keys_raw.strip()
        if raw:
            result: dict[str, str] = {}
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" in part:
                    key, role = part.split(":", 1)
                    result[key.strip()] = role.strip()
                else:
                    result[part] = "admin"
            return result
        key = self.claims_api_key.strip()
        if key:
            return {key: "admin"}
        return {}

    @property
    def jwt_secret(self) -> str | None:
        raw = self.jwt_secret_raw.strip()
        return raw if raw else None

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw.strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return list(_DEFAULT_CORS_ORIGINS)


# ---------------------------------------------------------------------------
# Mock Crew configuration
# ---------------------------------------------------------------------------


class MockCrewConfig(BaseSettings):
    """Mock Crew: simulate external interactions for testing."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_CREW_ENABLED")
    seed: int | None = Field(default=None, validation_alias="MOCK_CREW_SEED")

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("seed", mode="before")
    @classmethod
    def _parse_seed(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None


class PortalConfig(BaseSettings):
    """Claimant self-service portal configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CLAIMANT_PORTAL_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="CLAIMANT_PORTAL_ENABLED",
        description="Enable claimant portal routes.",
    )
    verification_mode: str = Field(
        default="token",
        validation_alias="CLAIMANT_VERIFICATION_MODE",
        description="Verification mode: token, policy_vin, or email.",
    )
    token_expiry_days: int = Field(
        default=90,
        ge=1,
        le=365,
        validation_alias="CLAIM_ACCESS_TOKEN_EXPIRY_DAYS",
        description="Token validity in days.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_enabled(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("verification_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, v: Any) -> str:
        s = str(v or "token").strip().lower()
        if s in ("token", "policy_vin", "email"):
            return s
        return "token"


class PrivacyConfig(BaseSettings):
    """Privacy and data protection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PRIVACY_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    llm_data_minimization: bool = Field(
        default=True,
        validation_alias="LLM_DATA_MINIMIZATION",
        description="When true, minimize claim data sent to LLM prompts (allowlists, PII masking).",
    )
    dsar_verification_required: bool = Field(
        default=True,
        validation_alias="DSAR_VERIFICATION_REQUIRED",
        description="When true, DSAR requests require claim_id or policy_number+vin verification.",
    )
    litigation_hold_blocks_deletion: bool = Field(
        default=True,
        validation_alias="LITIGATION_HOLD_BLOCKS_DELETION",
        description="When true, claims with litigation_hold are skipped during DSAR deletion.",
    )

    @field_validator("llm_data_minimization", "dsar_verification_required", "litigation_hold_blocks_deletion", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class ChatConfig(BaseSettings):
    """Chat agent configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CHAT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    max_tool_rounds: int = Field(default=5, ge=1, le=20, description="Max tool-call loops per turn")
    max_message_history: int = Field(default=50, ge=1, le=200, description="Max messages to send to LLM")
    system_prompt_override: str = Field(default="", description="Custom system prompt (empty = use default)")


class MockImageConfig(BaseSettings):
    """Mock image generator: OpenRouter image gen + mock vision analysis."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    generator_enabled: bool = Field(
        default=False, validation_alias="MOCK_IMAGE_GENERATOR_ENABLED"
    )
    model: str = Field(
        default="google/gemini-2.0-flash-exp", validation_alias="MOCK_IMAGE_MODEL"
    )
    vision_analysis_source: str = Field(
        default="claim_context",
        validation_alias="MOCK_IMAGE_VISION_ANALYSIS_SOURCE",
    )

    @field_validator("generator_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Adapter backends (dynamic env keys)
# ---------------------------------------------------------------------------

ADAPTER_ENV_KEYS: dict[str, str] = {
    "policy": "POLICY_ADAPTER",
    "valuation": "VALUATION_ADAPTER",
    "repair_shop": "REPAIR_SHOP_ADAPTER",
    "parts": "PARTS_ADAPTER",
    "siu": "SIU_ADAPTER",
    "claim_search": "CLAIM_SEARCH_ADAPTER",
    "nmvtis": "NMVTIS_ADAPTER",
    "vision": "VISION_ADAPTER",
    "ocr": "OCR_ADAPTER",
}
VALID_ADAPTER_BACKENDS: frozenset[str] = frozenset({"mock", "stub", "rest"})
VALID_VISION_ADAPTER_BACKENDS: frozenset[str] = frozenset({"real", "mock"})
# Adapters that have a REST implementation; "rest" is invalid for all others
REST_CAPABLE_ADAPTERS: frozenset[str] = frozenset({"policy"})
# Valuation PAS-style HTTP providers (VALUATION_ADAPTER + VALUATION_REST_*)
VALUATION_PROVIDER_BACKENDS: frozenset[str] = frozenset({"ccc", "mitchell", "audatex"})


class PolicyRestConfig(BaseSettings):
    """REST policy adapter configuration (POLICY_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="POLICY_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="PAS API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    path_template: str = Field(
        default="/policies/{policy_number}",
        description="Path template; {policy_number} placeholder",
    )
    response_key: str = Field(default="", description="JSON key for policy (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class ValuationRestConfig(BaseSettings):
    """REST valuation gateway (VALUATION_ADAPTER=ccc|mitchell|audatex)."""

    model_config = SettingsConfigDict(
        env_prefix="VALUATION_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Valuation gateway base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    path_template: str = Field(
        default="",
        description="Path with {vin},{year},{make},{model} placeholders; empty = provider default",
    )
    response_key: str = Field(
        default="",
        description="Optional JSON envelope key (e.g. data) before normalization",
    )
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


# ---------------------------------------------------------------------------
# Root Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    router: RouterConfig = Field(default_factory=RouterConfig)
    coverage: CoverageConfig = Field(default_factory=CoverageConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    fraud: FraudConfig = Field(default_factory=FraudConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    reserve: ReserveConfig = Field(default_factory=ReserveConfig)
    payment: PaymentConfig = Field(default_factory=PaymentConfig)
    partial_loss: PartialLossConfig = Field(default_factory=PartialLossConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    diary: DiaryConfig = Field(default_factory=DiaryConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mock_crew: MockCrewConfig = Field(default_factory=MockCrewConfig)
    mock_image: MockImageConfig = Field(default_factory=MockImageConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    policy_rest: PolicyRestConfig = Field(default_factory=PolicyRestConfig)
    valuation_rest: ValuationRestConfig = Field(default_factory=ValuationRestConfig)
    portal: PortalConfig = Field(default_factory=PortalConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)

    # Flat fields for compatibility (duplicate detection, high-value, etc.)
    duplicate_similarity_threshold: int = 40
    duplicate_similarity_threshold_high_value: int = 60
    duplicate_days_window: int = 3
    high_value_damage_threshold: int = 25_000
    high_value_vehicle_threshold: int = 50_000
    pre_routing_fraud_damage_ratio: float = 0.9
    max_tokens_per_claim: int = Field(default=150_000, validation_alias="CLAIM_AGENT_MAX_TOKENS_PER_CLAIM")
    max_llm_calls_per_claim: int = Field(default=50, validation_alias="CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM")
    after_action_note_max_tokens: int = Field(
        default=1024,
        ge=1,
        validation_alias="AFTER_ACTION_NOTE_MAX_TOKENS",
    )
    max_concurrent_background_tasks: int = Field(
        default=10, validation_alias="CLAIM_AGENT_MAX_CONCURRENT_BACKGROUND_TASKS"
    )
    idempotency_ttl_seconds: int = Field(
        default=86400,
        validation_alias="IDEMPOTENCY_TTL_SECONDS",
        description="TTL in seconds for idempotency keys (default 24h)",
    )
    crew_verbose: bool = Field(default=True, validation_alias="CREWAI_VERBOSE")
    retention_period_years: int = 5
    retention_purge_after_archive_years: int = Field(
        default=2,
        validation_alias="RETENTION_PURGE_AFTER_ARCHIVE_YEARS",
        description="Years after archived_at before retention purge (anonymize + purged status)",
    )
    policy_adapter: str = Field(default="mock", validation_alias="POLICY_ADAPTER")
    valuation_adapter: str = Field(default="mock", validation_alias="VALUATION_ADAPTER")
    repair_shop_adapter: str = Field(default="mock", validation_alias="REPAIR_SHOP_ADAPTER")
    parts_adapter: str = Field(default="mock", validation_alias="PARTS_ADAPTER")
    siu_adapter: str = Field(default="mock", validation_alias="SIU_ADAPTER")
    claim_search_adapter: str = Field(default="mock", validation_alias="CLAIM_SEARCH_ADAPTER")
    nmvtis_adapter: str = Field(default="mock", validation_alias="NMVTIS_ADAPTER")
    siu_default_state: str = Field(
        default="California",
        validation_alias="SIU_DEFAULT_STATE",
        description="Fallback state for SIU reporting when claim/policy state is missing",
    )
    vision_adapter: str = Field(default="real", validation_alias="VISION_ADAPTER")
    ocr_adapter: str = Field(default="mock", validation_alias="OCR_ADAPTER")

    @field_validator("siu_default_state", mode="before")
    @classmethod
    def _coerce_siu_default_state(cls, v: Any) -> str:
        s = (v or "").strip()
        return s if s else "California"

    @field_validator("retention_period_years", mode="before")
    @classmethod
    def _coerce_retention(cls, v: Any) -> int:
        if isinstance(v, int) and v >= 1:
            return v
        if isinstance(v, str):
            try:
                n = int(v)
                if n >= 1:
                    return n
            except ValueError:
                pass
        return 5  # fallback, model_validator will override from compliance if needed

    @field_validator("retention_purge_after_archive_years", mode="before")
    @classmethod
    def _coerce_purge_retention(cls, v: Any) -> int:
        if isinstance(v, int) and v >= 1:
            return v
        if isinstance(v, str):
            try:
                n = int(v)
                if n >= 1:
                    return n
            except ValueError:
                pass
        return 2

    @model_validator(mode="after")
    def _resolve_retention(self) -> "Settings":
        if self.retention_period_years != 5:
            return self
        years = self._load_compliance_retention()
        if years is not None:
            object.__setattr__(self, "retention_period_years", years)
        return self

    def _load_compliance_retention(self) -> int | None:
        path = Path(self.paths.ca_compliance_path)
        if not path.is_absolute():
            project_root = _default_project_data_dir().parent
            path = project_root / path
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        ecr = data.get("electronic_claims_requirements", {})
        for p in ecr.get("provisions", []):
            if p.get("id") == "ECR-003" and "retention_period_years" in p:
                try:
                    value = int(p["retention_period_years"])
                except (ValueError, TypeError):
                    return None
                return value if value >= 1 else None
        return None

    def get_retention_by_state(self) -> dict[str, int]:
        """Return state-specific retention periods (years). Empty dict = use default only."""
        path = Path(self.paths.state_retention_path)
        if not path.is_absolute():
            project_root = _default_project_data_dir().parent
            path = project_root / path
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        raw = data.get("retention_by_state", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, int] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, (int, float)):
                y = int(v)
                if y >= 1:
                    result[k.strip()] = y
        return result

    def get_attachment_storage_base_path(self) -> Path:
        """Return absolute path for attachment storage. Resolves relative paths against project root."""
        base = Path(self.paths.attachment_storage_path)
        if base.is_absolute():
            return base
        return _default_project_data_dir().parent / self.paths.attachment_storage_path

    def get_adapter_backend(self, adapter_name: str) -> str:
        adapter_field = f"{adapter_name}_adapter"
        raw = getattr(self, adapter_field, None)
        if raw is None:
            return "mock" if adapter_name != "vision" else "real"
        backend = raw.strip().lower()
        if adapter_name == "vision":
            return backend if backend in VALID_VISION_ADAPTER_BACKENDS else "real"
        return backend or "mock"
