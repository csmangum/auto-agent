"""Pydantic Settings model for centralized configuration.

All configuration is loaded from environment variables (and .env) at startup.
Use get_settings() to access the singleton instance.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationInfo, field_validator, model_validator
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
    #: Fraud score for ``photo_gps_far_from_incident`` (other EXIF anomalies use ``photo_exif_anomaly_score``).
    photo_gps_far_from_incident_score: int = 10
    photo_gps_incident_max_distance: float = 50.0
    photo_gps_incident_distance_unit: Literal["miles", "km"] = "miles"

    @field_validator("photo_gps_incident_max_distance", mode="before")
    @classmethod
    def _coerce_photo_gps_max_distance(cls, v: Any) -> float:
        try:
            x = float(v)
            return x if x > 0 else 50.0
        except (TypeError, ValueError):
            return 50.0

    @field_validator("photo_gps_incident_distance_unit", mode="before")
    @classmethod
    def _normalize_photo_gps_distance_unit(cls, v: Any) -> str:
        if v is None:
            return "miles"
        s = str(v).strip().lower()
        if s in ("km", "kilometer", "kilometers", "kms"):
            return "km"
        return "miles"

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
        "photo_gps_far_from_incident_score",
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
            "photo_gps_far_from_incident_score": 10,
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

    @field_validator("adjuster_limit", "supervisor_limit", "executive_limit", mode="before")
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
    secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
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
    sendgrid_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias="SENDGRID_API_KEY",
    )
    sendgrid_from_email: str = Field(default="", validation_alias="SENDGRID_FROM_EMAIL")
    twilio_account_sid: str = Field(default="", validation_alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias="TWILIO_AUTH_TOKEN",
    )
    twilio_from_phone: str = Field(default="", validation_alias="TWILIO_FROM_PHONE")

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


class LlmCostAlertConfig(BaseSettings):
    """Optional process-local LLM cost alerting configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_COST_ALERT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    threshold_usd: float | None = None
    webhook_url: str | None = None

    @field_validator("threshold_usd", mode="before")
    @classmethod
    def _coerce_threshold_usd(cls, v: Any) -> float | None:
        if v is None or str(v).strip() == "":
            return None
        try:
            parsed = float(v)
        except (ValueError, TypeError):
            return None
        return parsed if parsed > 0 else None

    @field_validator("webhook_url", mode="before")
    @classmethod
    def _empty_url_to_none(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()


class SchedulerConfig(BaseSettings):
    """Optional in-process scheduler for periodic operational jobs."""

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = False
    timezone: str = "UTC"
    ucspa_deadline_check_cron: str = "0 9 * * *"
    diary_escalate_cron: str = "0 * * * *"
    erp_poll_cron: str = Field(
        default="*/15 * * * *",
        validation_alias="SCHEDULER_ERP_POLL_CRON",
        description="Cron schedule for ERP inbound-event polling (default: every 15 minutes)",
    )
    ucspa_days_ahead: int = Field(
        default=3,
        ge=1,
        description="Days ahead for UCSPA deadline approaching alerts",
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
    langsmith_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="LANGSMITH_API_KEY"
    )
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
        "langsmith_enabled",
        "trace_llm_calls",
        "trace_tool_calls",
        "log_prompts",
        "log_responses",
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

    claims_db_path: str = Field(default="data/claims.db", validation_alias="CLAIMS_DB_PATH")
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description="PostgreSQL URL. If set, use PostgreSQL; else use SQLite at claims_db_path.",
    )
    read_replica_database_url: str | None = Field(
        default=None,
        validation_alias="READ_REPLICA_DATABASE_URL",
        description=(
            "Optional PostgreSQL read-replica URL. When set, read-heavy queries are routed "
            "to this replica; writes always go to the primary (DATABASE_URL). "
            "Only used when DATABASE_URL is also set. "
            "Example: postgresql://user:pass@replica-host:5432/claims"
        ),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias="REDIS_URL",
        description="Redis URL for rate limiting. If set, use Redis backend; else in-memory.",
    )

    @field_validator("database_url", "read_replica_database_url", "redis_url", mode="before")
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
    db_pool_size: int = Field(
        default=5,
        ge=1,
        validation_alias="DB_POOL_SIZE",
        description="SQLAlchemy connection pool size when using PostgreSQL.",
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        validation_alias="DB_MAX_OVERFLOW",
        description="SQLAlchemy max overflow connections beyond pool_size when using PostgreSQL.",
    )

    @field_validator("fresh_claims_db_on_startup", "run_migrations_on_startup", mode="before")
    @classmethod
    def _parse_bool_env(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    mock_db_path: str = Field(default="data/mock_db.json", validation_alias="MOCK_DB_PATH")
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

    api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias="OPENAI_API_KEY",
    )
    api_base: str = Field(default="", validation_alias="OPENAI_API_BASE")
    model_name: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL_NAME")
    vision_model: str = Field(default="gpt-4o", validation_alias="OPENAI_VISION_MODEL")
    fallback_models: str = Field(
        default="",
        validation_alias="OPENAI_FALLBACK_MODELS",
        description="Comma-separated fallback models when primary is down or over budget",
    )
    budget_fallback_enabled: bool = Field(
        default=False,
        validation_alias="LLM_BUDGET_FALLBACK_ENABLED",
        description=(
            "When true, proactively switch to the next cheaper model in OPENAI_FALLBACK_MODELS "
            "before hitting a hard TokenBudgetExceeded error, once token or call usage reaches "
            "LLM_BUDGET_FALLBACK_THRESHOLD of the cap. Requires OPENAI_FALLBACK_MODELS to be set."
        ),
    )
    budget_fallback_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        validation_alias="LLM_BUDGET_FALLBACK_THRESHOLD",
        description=(
            "Fraction of MAX_TOKENS_PER_CLAIM or MAX_LLM_CALLS_PER_CLAIM at which "
            "budget-driven fallback engages (0.0–1.0). Requires LLM_BUDGET_FALLBACK_ENABLED=true."
        ),
    )
    # Prompt cache settings
    cache_enabled: bool = Field(
        default=False,
        validation_alias="LLM_CACHE_ENABLED",
        description=(
            "Enable LiteLLM in-memory prompt cache. Useful when the same system prompt or "
            "RAG context is reused across multiple LLM calls. Disabled by default. "
            "Caveat: responses are cached in-process only (no cross-worker sharing); "
            "do not cache calls whose prompts contain user-specific PII."
        ),
    )
    cache_seed: int | None = Field(
        default=None,
        validation_alias="LLM_CACHE_SEED",
        description=(
            "Optional integer seed for deterministic LiteLLM cache keys. "
            "When set, identical prompts with the same seed always hit the same cache entry. "
            "Leave unset (default) for provider-assigned cache keys."
        ),
    )
    anthropic_prompt_cache: bool = Field(
        default=False,
        validation_alias="LLM_ANTHROPIC_PROMPT_CACHE",
        description=(
            "Enable the Anthropic server-side prompt-caching beta "
            "(anthropic-beta: prompt-caching-2024-07-31). "
            "Only effective when using an Anthropic model directly or via OpenRouter. "
            "Reduces cost and latency on repeated identical system prompts (≥1 024 tokens) "
            "and large RAG context blocks. Cached prefixes count toward output token usage. "
            "Caveat: cache TTL is ~5 minutes; do not include user-specific PII in "
            "cached prompt sections."
        ),
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

_DEFAULT_CORS_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]

_DEFAULT_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "X-API-Key",
    "X-Claim-Access-Token",
    "X-Claim-Id",
    "X-Email",
    "X-Policy-Number",
    "X-Portal-Token",
    "X-Repair-Shop-Access-Token",
    "X-Third-Party-Access-Token",
    "X-Vin",
    "X-Webhook-Signature",
]


@dataclass(frozen=True)
class ApiKeyEntry:
    """Parsed API_KEYS entry: role and optional identity override (claims.assignee / JWT sub)."""

    role: str
    identity: str | None = None


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("CLAIM_AGENT_ENVIRONMENT", "ENVIRONMENT"),
        description=(
            "Deployment environment. Set to 'production' to enforce authentication at startup. "
            "Use 'development' (default) or 'dev' to allow unauthenticated local runs. "
            "Prefer CLAIM_AGENT_ENVIRONMENT; ENVIRONMENT is accepted for backward compatibility."
        ),
    )
    api_keys_raw: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="API_KEYS"
    )
    claims_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="CLAIMS_API_KEY"
    )
    jwt_secret_raw: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="JWT_SECRET"
    )
    jwt_access_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=86400,
        validation_alias="JWT_ACCESS_TTL_SECONDS",
        description="Access JWT lifetime in seconds (default 15 minutes).",
    )
    jwt_refresh_ttl_seconds: int = Field(
        default=604800,
        ge=300,
        le=31536000,
        validation_alias="JWT_REFRESH_TTL_SECONDS",
        description="Opaque refresh token lifetime in seconds (default 7 days).",
    )
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")
    cors_methods_raw: str = Field(default="", validation_alias="CORS_METHODS")
    cors_headers_raw: str = Field(default="", validation_alias="CORS_HEADERS")
    trust_forwarded_for: bool = Field(default=False, validation_alias="TRUST_FORWARDED_FOR")
    enforce_https: bool = Field(
        default=False,
        validation_alias="ENFORCE_HTTPS",
        description=(
            "When true, add Strict-Transport-Security (HSTS) headers and redirect "
            "HTTP requests to HTTPS based on the X-Forwarded-Proto header. "
            "Requires TRUST_FORWARDED_FOR=true (trusted proxy) or the redirect logic is disabled. "
            "Enable only when deployed behind a TLS-terminating reverse proxy."
        ),
    )
    hsts_max_age: int = Field(
        default=31536000,
        ge=0,
        validation_alias="HSTS_MAX_AGE",
        description="HSTS max-age in seconds (default: 31536000 = 1 year).",
    )
    hsts_include_subdomains: bool = Field(
        default=True,
        validation_alias="HSTS_INCLUDE_SUBDOMAINS",
        description="Append 'includeSubDomains' to the HSTS header (default: true).",
    )
    hsts_preload: bool = Field(
        default=False,
        validation_alias="HSTS_PRELOAD",
        description=(
            "When true, append the HSTS preload directive (submit via hstspreload.org). "
            "Irreversible for months once in browser preload lists; default false."
        ),
    )

    @field_validator("jwt_secret_raw", mode="after")
    @classmethod
    def _validate_jwt_key_length(cls, v: SecretStr) -> SecretStr:
        min_len = 32
        stripped = v.get_secret_value().strip()
        if stripped and len(stripped) < min_len:
            raise ValueError(
                f"JWT_SECRET must be at least {min_len} characters "
                f"for HS256 (RFC 7518 Section 3.2). Got {len(stripped)} characters."
            )
        return v

    @property
    def api_key_entries(self) -> dict[str, ApiKeyEntry]:
        """API_KEYS / CLAIMS_API_KEY: key -> role and optional identity (``key:role`` or ``key:role:user_id``)."""
        raw = self.api_keys_raw.get_secret_value().strip()
        if raw:
            result: dict[str, ApiKeyEntry] = {}
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" in part:
                    segments = part.split(":", 2)
                    if len(segments) == 3:
                        key, role, uid = segments
                        result[key.strip()] = ApiKeyEntry(
                            role=role.strip(),
                            identity=uid.strip() or None,
                        )
                    else:
                        key, role = part.split(":", 1)
                        result[key.strip()] = ApiKeyEntry(role=role.strip(), identity=None)
                else:
                    result[part] = ApiKeyEntry(role="admin", identity=None)
            return result
        key = self.claims_api_key.get_secret_value().strip()
        if key:
            return {key: ApiKeyEntry(role="admin", identity=None)}
        return {}

    @property
    def api_keys(self) -> dict[str, str]:
        """Backward-compatible key -> role mapping."""
        return {k: v.role for k, v in self.api_key_entries.items()}

    @property
    def jwt_secret(self) -> str | None:
        raw = self.jwt_secret_raw.get_secret_value().strip()
        return raw if raw else None

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw.strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return list(_DEFAULT_CORS_ORIGINS)

    @property
    def cors_methods(self) -> list[str]:
        raw = self.cors_methods_raw.strip()
        if raw:
            return [m.strip().upper() for m in raw.split(",") if m.strip()]
        return list(_DEFAULT_CORS_METHODS)

    @property
    def cors_headers(self) -> list[str]:
        raw = self.cors_headers_raw.strip()
        if raw:
            return [h.strip() for h in raw.split(",") if h.strip()]
        return list(_DEFAULT_CORS_HEADERS)


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


class ResponseStrategy(str, Enum):
    """Mock claimant response strategies."""

    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    REFUSE = "refuse"
    PARTIAL = "partial"


class MockClaimantConfig(BaseSettings):
    """Mock Claimant: rule/template-based claimant simulation for testing."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_CLAIMANT_ENABLED")
    response_strategy: ResponseStrategy = Field(
        default=ResponseStrategy.IMMEDIATE,
        validation_alias="MOCK_CLAIMANT_RESPONSE_STRATEGY",
        description="Response strategy: immediate | delayed | refuse | partial",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("response_strategy", mode="before")
    @classmethod
    def _parse_strategy(cls, v: Any) -> str:
        if isinstance(v, ResponseStrategy):
            return v.value
        valid = {s.value for s in ResponseStrategy}
        val = str(v).strip().lower() if v else ResponseStrategy.IMMEDIATE.value
        return val if val in valid else ResponseStrategy.IMMEDIATE.value


class MockNotifierConfig(BaseSettings):
    """Mock Notifier: intercept outbound notifications for testing.

    Only active when ``MOCK_CREW_ENABLED=true``.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_NOTIFIER_ENABLED")
    auto_respond: bool = Field(default=False, validation_alias="MOCK_NOTIFIER_AUTO_RESPOND")

    @field_validator("enabled", "auto_respond", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class MockRepairShopConfig(BaseSettings):
    """Mock Repair Shop: intercept repair-shop follow-up notifications for testing.

    Only active when ``MOCK_CREW_ENABLED=true``.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_REPAIR_SHOP_ENABLED")
    response_template: str = Field(
        default="Repair shop acknowledged receipt of request. Appointment will be scheduled.",
        validation_alias="MOCK_REPAIR_SHOP_RESPONSE_TEMPLATE",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class ThirdPartyOutcome(str, Enum):
    """Possible outcomes when a mock third party receives a demand letter."""

    ACCEPT = "accept"
    REJECT = "reject"
    NEGOTIATE = "negotiate"


class MockThirdPartyConfig(BaseSettings):
    """Mock Third Party: intercept demand-letter dispatch for testing.

    Only active when ``MOCK_CREW_ENABLED=true``.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_THIRD_PARTY_ENABLED")
    outcome: ThirdPartyOutcome = Field(
        default=ThirdPartyOutcome.ACCEPT,
        validation_alias="MOCK_THIRD_PARTY_OUTCOME",
        description="Third-party response outcome: accept | reject | negotiate",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("outcome", mode="before")
    @classmethod
    def _parse_outcome(cls, v: Any) -> str:
        valid = {o.value for o in ThirdPartyOutcome}
        if isinstance(v, ThirdPartyOutcome):
            return v.value
        val = str(v).strip().lower() if v else ThirdPartyOutcome.ACCEPT.value
        return val if val in valid else ThirdPartyOutcome.ACCEPT.value


class MockWebhookConfig(BaseSettings):
    """Mock Webhook: capture outbound webhook payloads in-memory for testing.

    Only active when ``MOCK_CREW_ENABLED=true``.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    capture_enabled: bool = Field(default=False, validation_alias="MOCK_WEBHOOK_CAPTURE_ENABLED")

    @field_validator("capture_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class MockERPCaptureConfig(BaseSettings):
    """Mock ERP capture: record outbound ERP pushes in-memory for testing.

    Only active when ``MOCK_CREW_ENABLED=true``.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    capture_enabled: bool = Field(default=False, validation_alias="MOCK_ERP_CAPTURE_ENABLED")

    @field_validator("capture_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


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


class RepairShopPortalConfig(BaseSettings):
    """Repair shop self-service portal (per-claim magic tokens)."""

    model_config = SettingsConfigDict(
        env_prefix="REPAIR_SHOP_PORTAL_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(
        default=False,
        description="Enable /api/repair-portal routes and token minting.",
    )
    token_expiry_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Repair shop access token validity in days.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_enabled(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class ThirdPartyPortalConfig(BaseSettings):
    """Third-party self-service portal (counterparty / lienholder magic links)."""

    model_config = SettingsConfigDict(
        env_prefix="THIRD_PARTY_PORTAL_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(
        default=False,
        description="Enable /api/third-party-portal routes and token minting.",
    )
    token_expiry_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Third-party access token validity in days.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_enabled(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


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
    data_region: str = Field(
        default="us",
        validation_alias="DATA_REGION",
        description=(
            "Primary data region for this deployment: 'us', 'eu', or 'other'. "
            "Controls how cross-border transfer checks classify the data source."
        ),
    )
    cross_border_policy: str = Field(
        default="audit",
        validation_alias="CROSS_BORDER_POLICY",
        description=(
            "Policy for cross-border data transfers: "
            "'allow' (permit, log), 'audit' (permit with warning), "
            "or 'restrict' (block transfers lacking a documented mechanism)."
        ),
    )
    llm_transfer_mechanism: str = Field(
        default="scc",
        validation_alias="LLM_TRANSFER_MECHANISM",
        description=(
            "Transfer mechanism documenting the legal basis for sending claim data "
            "to the LLM provider: 'scc', 'adequacy_decision', 'explicit_consent', "
            "'bcr', 'legitimate_interests', or 'none'."
        ),
    )
    otp_enabled: bool = Field(
        default=False,
        validation_alias="OTP_ENABLED",
        description="When true, OTP verification is available for self-service DSAR submissions.",
    )
    otp_ttl_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        validation_alias="OTP_TTL_MINUTES",
        description="Minutes until a DSAR OTP token expires.",
    )
    otp_max_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias="OTP_MAX_ATTEMPTS",
        description="Maximum failed OTP verification attempts before the token is locked.",
    )
    otp_rate_limit_window_minutes: int = Field(
        default=60,
        ge=1,
        validation_alias="OTP_RATE_LIMIT_WINDOW_MINUTES",
        description="Rolling window (minutes) for OTP request rate limiting per identifier.",
    )
    otp_rate_limit_max_requests: int = Field(
        default=5,
        ge=1,
        validation_alias="OTP_RATE_LIMIT_MAX_REQUESTS",
        description="Maximum OTP requests per identifier within the rate-limit window.",
    )
    otp_code_length: int = Field(
        default=6,
        ge=4,
        le=10,
        validation_alias="OTP_CODE_LENGTH",
        description="Length of the numeric OTP code.",
    )
    otp_pepper: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias="OTP_PEPPER",
        description=(
            "Server-side secret (pepper) used as the HMAC key when hashing OTP codes. "
            "Should be a long random string. If empty, the JWT_SECRET is used as a fallback. "
            "Set this to a unique secret in production to prevent offline brute-force attacks."
        ),
    )
    audit_log_state_redaction_enabled: bool = Field(
        default=False,
        validation_alias="AUDIT_LOG_STATE_REDACTION_ENABLED",
        description=(
            "When true, claim_audit_log JSON fields (details, before_state, after_state) "
            "are scrubbed during retention purge (via anonymize_claim_pii). DSAR deletion "
            "uses DSAR_AUDIT_LOG_POLICY instead. Requires migration 049. Default false."
        ),
    )
    dsar_audit_log_policy: str = Field(
        default="preserve",
        validation_alias="DSAR_AUDIT_LOG_POLICY",
        description=(
            "Policy for claim_audit_log entries during DSAR deletion. "
            "'preserve' (default): keep audit rows unchanged for legal/regulatory compliance. "
            "'redact': scrub PII values from details/before_state/after_state JSON fields "
            "while retaining action metadata and timestamps. "
            "'delete': remove all audit rows for the claim (irreversible; requires "
            "compliance sign-off and should be used only in jurisdictions that mandate it)."
        ),
    )

    @field_validator(
        "llm_data_minimization",
        "dsar_verification_required",
        "litigation_hold_blocks_deletion",
        "otp_enabled",
        "audit_log_state_redaction_enabled",
        mode="before",
    )
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("dsar_audit_log_policy", mode="before")
    @classmethod
    def _normalize_audit_log_policy(cls, v: Any) -> str:
        s = str(v or "preserve").strip().lower()
        if s in ("preserve", "redact", "delete"):
            return s
        return "preserve"


class ChatConfig(BaseSettings):
    """Chat agent configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CHAT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    max_tool_rounds: int = Field(default=5, ge=1, le=20, description="Max tool-call loops per turn")
    max_message_history: int = Field(
        default=50, ge=1, le=200, description="Max messages to send to LLM"
    )
    system_prompt_override: str = Field(
        default="", description="Custom system prompt (empty = use default)"
    )


class MockImageConfig(BaseSettings):
    """Mock image generator: OpenRouter image gen + mock vision analysis."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    generator_enabled: bool = Field(default=False, validation_alias="MOCK_IMAGE_GENERATOR_ENABLED")
    model: str = Field(default="google/gemini-2.0-flash-exp", validation_alias="MOCK_IMAGE_MODEL")
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


class MockDocumentGeneratorConfig(BaseSettings):
    """Mock document generator: repair estimates and damage photo URLs."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=False, validation_alias="MOCK_DOCUMENT_GENERATOR_ENABLED")

    @field_validator("enabled", mode="before")
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
    "state_bureau": "STATE_BUREAU_ADAPTER",
    "claim_search": "CLAIM_SEARCH_ADAPTER",
    "nmvtis": "NMVTIS_ADAPTER",
    "gap_insurance": "GAP_INSURANCE_ADAPTER",
    "vision": "VISION_ADAPTER",
    "ocr": "OCR_ADAPTER",
    "cms": "CMS_ADAPTER",
    "fraud_reporting": "FRAUD_REPORTING_ADAPTER",
    "reverse_image": "REVERSE_IMAGE_ADAPTER",
    "erp": "ERP_ADAPTER",
    "medical_records": "MEDICAL_RECORDS_ADAPTER",
}
VALID_ADAPTER_BACKENDS: frozenset[str] = frozenset({"mock", "stub", "rest"})
VALID_VISION_ADAPTER_BACKENDS: frozenset[str] = frozenset({"real", "mock"})
# Adapters that have a REST implementation; "rest" is invalid for all others
REST_CAPABLE_ADAPTERS: frozenset[str] = frozenset(
    {
        "policy",
        "fraud_reporting",
        "state_bureau",
        "claim_search",
        "erp",
        "repair_shop",
        "parts",
        "siu",
        "nmvtis",
        "gap_insurance",
        "ocr",
        "cms",
        "reverse_image",
        "medical_records",
    }
)
# Valuation PAS-style HTTP providers (VALUATION_ADAPTER + VALUATION_REST_*)
VALUATION_PROVIDER_BACKENDS: frozenset[str] = frozenset({"ccc", "mitchell", "audatex"})
STATE_BUREAU_SUPPORTED_CODES: tuple[str, ...] = ("CA", "TX", "FL", "NY", "GA")


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


class FraudReportingRestConfig(BaseSettings):
    """REST fraud reporting adapter configuration (FRAUD_REPORTING_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="FRAUD_REPORTING_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Fraud filing gateway base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    state_bureau_path: str = Field(default="/fraud/state-bureau")
    nicb_path: str = Field(default="/fraud/nicb")
    niss_path: str = Field(default="/fraud/niss")
    response_key: str = Field(default="", description="Optional envelope JSON key")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class StateBureauConfig(BaseSettings):
    """Per-state bureau REST adapter configuration (STATE_BUREAU_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="STATE_BUREAU_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")
    supported_state_codes: tuple[str, ...] = Field(
        default=STATE_BUREAU_SUPPORTED_CODES,
        description="Supported state bureau endpoint codes for configuration mapping.",
    )
    ca_endpoint: str = Field(default="", description="California DOI fraud endpoint base URL")
    tx_endpoint: str = Field(default="", description="Texas DOI fraud endpoint base URL")
    fl_endpoint: str = Field(default="", description="Florida DOI fraud endpoint base URL")
    ny_endpoint: str = Field(default="", description="New York DOI fraud endpoint base URL")
    ga_endpoint: str = Field(default="", description="Georgia DOI fraud endpoint base URL")

    def get_state_endpoints(self) -> dict[str, str]:
        endpoints: dict[str, str] = {}
        for code in self.supported_state_codes:
            attr = f"{code.lower()}_endpoint"
            value = getattr(self, attr, "")
            endpoints[code] = (value or "").strip()
        return endpoints


class ClaimSearchRestConfig(BaseSettings):
    """REST ClaimSearch adapter configuration (CLAIM_SEARCH_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="CLAIM_SEARCH_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="ClaimSearch API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    search_path: str = Field(
        default="/claims/search",
        description="Search endpoint path on the ClaimSearch API",
    )
    response_key: str = Field(
        default="",
        description="Optional JSON envelope key containing the results list (e.g. 'results')",
    )
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class ERPRestConfig(BaseSettings):
    """REST ERP adapter configuration (ERP_ADAPTER=rest).

    Connects to an external repair/shop management system (e.g. Mitchell
    RepairCenter, CCC ONE, Solera) for bi-directional repair workflow sync.
    """

    model_config = SettingsConfigDict(
        env_prefix="ERP_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="ERP API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")
    assignment_path: str = Field(
        default="/repairs/assignment",
        description="API path for repair assignment notifications",
    )
    estimate_path: str = Field(
        default="/repairs/estimate",
        description="API path for estimate / supplement updates",
    )
    status_path: str = Field(
        default="/repairs/status",
        description="API path for repair status sync",
    )
    events_path: str = Field(
        default="/repairs/events",
        description="API path for polling inbound ERP events",
    )
    shop_id_map_raw: str = Field(
        default="",
        validation_alias="ERP_REST_SHOP_ID_MAP",
        description=(
            "Comma-separated internal_id=erp_id pairs for shop identity mapping "
            "(e.g. 'SHOP-1=42,SHOP-2=99'). Leave empty to use internal IDs as-is."
        ),
    )

    @property
    def shop_id_map(self) -> dict[str, str]:
        """Parse the raw shop-ID mapping string into a dict."""
        result: dict[str, str] = {}
        for pair in (self.shop_id_map_raw or "").split(","):
            pair = pair.strip()
            if "=" in pair:
                k, _, v = pair.partition("=")
                k, v = k.strip(), v.strip()
                if k and v:
                    result[k] = v
        return result


class RepairShopRestConfig(BaseSettings):
    """REST repair-shop adapter configuration (REPAIR_SHOP_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="REPAIR_SHOP_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Shop management API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    shops_path: str = Field(default="/shops", description="Path for listing all shops")
    shop_path_template: str = Field(
        default="/shops/{shop_id}",
        description="Path template for a single shop; {shop_id} placeholder",
    )
    labor_path: str = Field(
        default="/shops/labor-operations",
        description="Path for labor operations catalog",
    )
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class PartsRestConfig(BaseSettings):
    """REST parts-catalog adapter configuration (PARTS_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="PARTS_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Parts management API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    catalog_path: str = Field(default="/parts/catalog", description="Path for the parts catalog")
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class SIURestConfig(BaseSettings):
    """REST SIU case-management adapter configuration (SIU_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="SIU_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="SIU case management API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    cases_path: str = Field(default="/siu/cases", description="Path for creating/getting cases")
    notes_path_template: str = Field(
        default="/siu/cases/{case_id}/notes",
        description="Path template for adding notes; {case_id} placeholder",
    )
    status_path_template: str = Field(
        default="/siu/cases/{case_id}/status",
        description="Path template for updating status; {case_id} placeholder",
    )
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class NMVTISRestConfig(BaseSettings):
    """REST NMVTIS reporting gateway adapter configuration (NMVTIS_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="NMVTIS_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="NMVTIS gateway API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    report_path: str = Field(
        default="/nmvtis/reports",
        description="Path for submitting total-loss / salvage reports",
    )
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class GapInsuranceRestConfig(BaseSettings):
    """REST gap-insurance carrier adapter configuration (GAP_INSURANCE_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="GAP_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Gap carrier API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    submit_path: str = Field(
        default="/gap/claims",
        description="Path for submitting shortfall claims",
    )
    status_path_template: str = Field(
        default="/gap/claims/{gap_claim_id}",
        description="Path template for polling claim status; {gap_claim_id} placeholder",
    )
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class OCRRestConfig(BaseSettings):
    """REST OCR extraction adapter configuration (OCR_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="OCR_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="OCR API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    extract_path: str = Field(
        default="/ocr/extract",
        description="Path for document extraction endpoint",
    )
    response_key: str = Field(
        default="",
        description="Optional JSON envelope key wrapping the structured data (e.g. data)",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout seconds (larger for OCR processing)",
    )


class MedicalRecordsRestConfig(BaseSettings):
    """REST medical records adapter configuration (MEDICAL_RECORDS_ADAPTER=rest).

    Connects to an HIE, provider portal, or equivalent medical records system.
    All returned data is PHI; handle per HIPAA minimum-necessary standards.
    """

    model_config = SettingsConfigDict(
        env_prefix="MEDICAL_RECORDS_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="HIE or provider portal base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    query_path: str = Field(
        default="/medical-records/query",
        description="Path for the records query endpoint",
    )
    response_key: str = Field(
        default="",
        description="Optional JSON envelope key wrapping the records data (e.g. data)",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout seconds",
    )


class CMSRestConfig(BaseSettings):
    """REST CMS/Medicare reporting adapter configuration (CMS_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="CMS_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="CMS reporting gateway base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    evaluate_path: str = Field(
        default="/cms/evaluate",
        description="Path for settlement reporting evaluation endpoint",
    )
    response_key: str = Field(default="", description="Optional JSON envelope key (e.g. data)")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Request timeout seconds")


class ReverseImageRestConfig(BaseSettings):
    """REST reverse-image search adapter configuration (REVERSE_IMAGE_ADAPTER=rest)."""

    model_config = SettingsConfigDict(
        env_prefix="REVERSE_IMAGE_REST_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    base_url: str = Field(default="", description="Reverse-image provider API base URL")
    auth_header: str = Field(default="Authorization", description="Auth header name")
    auth_value: str = Field(default="", description="Bearer token or API key")
    match_path: str = Field(
        default="/images/match",
        description="Path for image matching endpoint",
    )
    response_key: str = Field(
        default="",
        description="Optional JSON envelope key wrapping the matches list (e.g. matches)",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout seconds (larger for image upload and processing)",
    )


# ---------------------------------------------------------------------------
# Backup configuration
# ---------------------------------------------------------------------------


class BackupConfig(BaseSettings):
    """PostgreSQL backup configuration.

    Documents paths, retention, and S3 options shared with ``scripts/backup_postgres.py``.
    Schedulers or operators use ``enabled`` as a convention; nothing in the app triggers
    backups automatically from this flag alone.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="BACKUP_ENABLED",
        description=(
            "Whether scheduled/ops workflows should run PostgreSQL backups (convention for "
            "cron, systemd, or external orchestration). Does not start backups by itself; "
            "invoke ``scripts/backup_postgres.py`` explicitly. No effect on SQLite "
            "(CLAIMS_DB_PATH) deployments."
        ),
    )
    backup_dir: str = Field(
        default="data/backups",
        validation_alias="BACKUP_DIR",
        description="Local directory where pg_dump files are written.",
    )
    retention_days: int = Field(
        default=14,
        ge=1,
        validation_alias="BACKUP_RETENTION_DAYS",
        description="Number of days to retain local backup files before rotation.",
    )
    s3_bucket: str = Field(
        default="",
        validation_alias="BACKUP_S3_BUCKET",
        description=(
            "S3 bucket to upload backups to. Leave empty to keep backups local only."
        ),
    )
    s3_prefix: str = Field(
        default="postgres-backups",
        validation_alias="BACKUP_S3_PREFIX",
        description="Key prefix for S3 backup objects.",
    )
    s3_endpoint: str | None = Field(
        default=None,
        validation_alias="BACKUP_S3_ENDPOINT",
        description="Optional S3-compatible endpoint URL (e.g. MinIO).",
    )
    compress: bool = Field(
        default=True,
        validation_alias="BACKUP_COMPRESS",
        description=(
            "When true, pg_dump uses custom compressed format (-Fc). "
            "When false, plain SQL (-Fp, larger files, human-readable)."
        ),
    )
    pg_dump_path: str = Field(
        default="pg_dump",
        validation_alias="BACKUP_PG_DUMP_PATH",
        description="Path to the pg_dump binary. Defaults to searching PATH.",
    )
    pg_restore_path: str = Field(
        default="pg_restore",
        validation_alias="BACKUP_PG_RESTORE_PATH",
        description="Path to the pg_restore binary. Defaults to searching PATH.",
    )
    pg_psql_path: str = Field(
        default="psql",
        validation_alias="BACKUP_PG_PSQL_PATH",
        description="Path to the psql binary used by the restore script. Defaults to searching PATH.",
    )

    @field_validator("enabled", "compress", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("s3_bucket", mode="before")
    @classmethod
    def _normalize_s3_bucket(cls, v: Any) -> str:
        return str(v).strip() if v else ""

    @field_validator("s3_endpoint", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()


# ---------------------------------------------------------------------------
# Root Settings
# ---------------------------------------------------------------------------


class RetentionExportConfig(BaseSettings):
    """S3/Glacier cold-storage export configuration for retention pipeline."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="RETENTION_EXPORT_ENABLED",
        description="Enable cold-storage export pipeline (requires S3 bucket).",
    )
    s3_bucket: str = Field(
        default="",
        validation_alias="RETENTION_EXPORT_S3_BUCKET",
        description="S3 bucket for cold-storage exports.",
    )
    s3_prefix: str = Field(
        default="retention-exports",
        validation_alias="RETENTION_EXPORT_S3_PREFIX",
        description="Key prefix inside the export bucket.",
    )
    s3_endpoint: str | None = Field(
        default=None,
        validation_alias="RETENTION_EXPORT_S3_ENDPOINT",
        description="Optional endpoint URL (MinIO or S3-compatible).",
    )
    s3_storage_class: str = Field(
        default="GLACIER_IR",
        validation_alias="RETENTION_EXPORT_S3_STORAGE_CLASS",
        description=(
            "S3 storage class applied to uploaded objects "
            "(e.g. GLACIER_IR, GLACIER, STANDARD_IA)."
        ),
    )
    encryption: str = Field(
        default="AES256",
        validation_alias="RETENTION_EXPORT_ENCRYPTION",
        description="Server-side encryption: AES256 or aws:kms.",
    )
    kms_key_id: str | None = Field(
        default=None,
        validation_alias="RETENTION_EXPORT_KMS_KEY_ID",
        description="KMS key ARN/ID when encryption=aws:kms.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    @field_validator("s3_endpoint", "kms_key_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()

    @field_validator("encryption", mode="before")
    @classmethod
    def _normalize_encryption(cls, v: Any) -> str:
        s = str(v or "AES256").strip()
        return s if s else "AES256"


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
    llm_cost_alert: LlmCostAlertConfig = Field(default_factory=LlmCostAlertConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    diary: DiaryConfig = Field(default_factory=DiaryConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mock_crew: MockCrewConfig = Field(default_factory=MockCrewConfig)
    mock_claimant: MockClaimantConfig = Field(default_factory=MockClaimantConfig)
    mock_notifier: MockNotifierConfig = Field(default_factory=MockNotifierConfig)
    mock_repair_shop: MockRepairShopConfig = Field(default_factory=MockRepairShopConfig)
    mock_third_party: MockThirdPartyConfig = Field(default_factory=MockThirdPartyConfig)
    mock_webhook: MockWebhookConfig = Field(default_factory=MockWebhookConfig)
    mock_erp_capture: MockERPCaptureConfig = Field(default_factory=MockERPCaptureConfig)
    mock_image: MockImageConfig = Field(default_factory=MockImageConfig)
    mock_document: MockDocumentGeneratorConfig = Field(default_factory=MockDocumentGeneratorConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    policy_rest: PolicyRestConfig = Field(default_factory=PolicyRestConfig)
    valuation_rest: ValuationRestConfig = Field(default_factory=ValuationRestConfig)
    fraud_reporting_rest: FraudReportingRestConfig = Field(default_factory=FraudReportingRestConfig)
    state_bureau: StateBureauConfig = Field(default_factory=StateBureauConfig)
    claim_search_rest: ClaimSearchRestConfig = Field(default_factory=ClaimSearchRestConfig)
    erp_rest: ERPRestConfig = Field(default_factory=ERPRestConfig)
    repair_shop_rest: RepairShopRestConfig = Field(default_factory=RepairShopRestConfig)
    parts_rest: PartsRestConfig = Field(default_factory=PartsRestConfig)
    siu_rest: SIURestConfig = Field(default_factory=SIURestConfig)
    nmvtis_rest: NMVTISRestConfig = Field(default_factory=NMVTISRestConfig)
    gap_insurance_rest: GapInsuranceRestConfig = Field(default_factory=GapInsuranceRestConfig)
    ocr_rest: OCRRestConfig = Field(default_factory=OCRRestConfig)
    medical_records_rest: MedicalRecordsRestConfig = Field(default_factory=MedicalRecordsRestConfig)
    cms_rest: CMSRestConfig = Field(default_factory=CMSRestConfig)
    reverse_image_rest: ReverseImageRestConfig = Field(default_factory=ReverseImageRestConfig)
    portal: PortalConfig = Field(default_factory=PortalConfig)
    repair_shop_portal: RepairShopPortalConfig = Field(default_factory=RepairShopPortalConfig)
    third_party_portal: ThirdPartyPortalConfig = Field(default_factory=ThirdPartyPortalConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    retention_export: RetentionExportConfig = Field(default_factory=RetentionExportConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)

    # Flat fields for compatibility (duplicate detection, high-value, etc.)
    duplicate_similarity_threshold: int = 40
    duplicate_similarity_threshold_high_value: int = 60
    duplicate_days_window: int = 3
    high_value_damage_threshold: int = 25_000
    high_value_vehicle_threshold: int = 50_000
    pre_routing_fraud_damage_ratio: float = 0.9
    max_tokens_per_claim: int = Field(
        default=150_000, validation_alias="CLAIM_AGENT_MAX_TOKENS_PER_CLAIM"
    )
    max_llm_calls_per_claim: int = Field(
        default=50, validation_alias="CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM"
    )
    claim_workflow_timeout_seconds: int = Field(
        default=600,
        ge=30,
        validation_alias="CLAIM_WORKFLOW_TIMEOUT_SECONDS",
        description=(
            "Wall-clock timeout (seconds) for run_claim_workflow(). "
            "Checked only between workflow stages (not mid-stage); a single slow stage can "
            "exceed this until it finishes. Use LLM_CALL_TIMEOUT_SECONDS to cap individual LLM "
            "calls. When exceeded, the claim is marked failed and a claim.timeout webhook fires. "
            "Default 600 (10 minutes). Minimum 30."
        ),
    )
    llm_call_timeout_seconds: int = Field(
        default=120,
        ge=10,
        validation_alias="LLM_CALL_TIMEOUT_SECONDS",
        description=(
            "Per-LLM-call timeout (seconds) passed to the CrewAI LLM instance. "
            "Prevents individual LLM calls from hanging indefinitely. "
            "Default 120 (2 minutes). Minimum 10."
        ),
    )
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
    max_request_body_size_mb: int = Field(
        default=10,
        ge=1,
        validation_alias="MAX_REQUEST_BODY_SIZE_MB",
        description=(
            "Maximum allowed request body size in megabytes for non-file-upload endpoints "
            "(default 10 MB). POST/PUT/PATCH under /api/ must send Content-Length (not "
            "chunked without a length); larger advertised lengths return HTTP 413 before "
            "reading the body."
        ),
    )
    max_upload_body_size_mb: int = Field(
        default=100,
        ge=1,
        validation_alias="MAX_UPLOAD_BODY_SIZE_MB",
        description=(
            "Maximum allowed request body size in megabytes for multipart/form-data "
            "file-upload endpoints (default 100 MB). Supplements the per-file limit "
            "enforced by individual route handlers."
        ),
    )
    max_upload_file_size_mb: int = Field(
        default=50,
        ge=1,
        validation_alias="MAX_UPLOAD_FILE_SIZE_MB",
        description=(
            "Maximum size in megabytes for a single uploaded file in claims routes "
            "(default 50 MB). The full multipart request is still capped by "
            "MAX_UPLOAD_BODY_SIZE_MB."
        ),
    )
    crew_verbose: bool = Field(default=True, validation_alias="CREWAI_VERBOSE")
    retention_period_years: int = 5
    retention_purge_after_archive_years: int = Field(
        default=2,
        validation_alias="RETENTION_PURGE_AFTER_ARCHIVE_YEARS",
        description="Years after archived_at before retention purge (anonymize + purged status)",
    )
    audit_log_retention_years_after_purge: int | None = Field(
        default=None,
        validation_alias="AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE",
        description=(
            "Calendar years after claim purged_at before audit rows are eligible for "
            "export/purge tooling; None disables eligibility reporting"
        ),
    )
    audit_log_purge_enabled: bool = Field(
        default=False,
        validation_alias="AUDIT_LOG_PURGE_ENABLED",
        description="When true, allow claim-agent audit-log-purge to delete audit rows",
    )
    policy_adapter: str = Field(default="mock", validation_alias="POLICY_ADAPTER")
    valuation_adapter: str = Field(default="mock", validation_alias="VALUATION_ADAPTER")
    repair_shop_adapter: str = Field(default="mock", validation_alias="REPAIR_SHOP_ADAPTER")
    parts_adapter: str = Field(default="mock", validation_alias="PARTS_ADAPTER")
    siu_adapter: str = Field(default="mock", validation_alias="SIU_ADAPTER")
    state_bureau_adapter: str = Field(default="mock", validation_alias="STATE_BUREAU_ADAPTER")
    claim_search_adapter: str = Field(default="mock", validation_alias="CLAIM_SEARCH_ADAPTER")
    nmvtis_adapter: str = Field(default="mock", validation_alias="NMVTIS_ADAPTER")
    gap_insurance_adapter: str = Field(default="mock", validation_alias="GAP_INSURANCE_ADAPTER")
    siu_default_state: str = Field(
        default="California",
        validation_alias="SIU_DEFAULT_STATE",
        description="Fallback state for SIU reporting when claim/policy state is missing",
    )
    vision_adapter: str = Field(default="real", validation_alias="VISION_ADAPTER")
    ocr_adapter: str = Field(default="mock", validation_alias="OCR_ADAPTER")
    cms_adapter: str = Field(default="mock", validation_alias="CMS_ADAPTER")
    fraud_reporting_adapter: str = Field(default="mock", validation_alias="FRAUD_REPORTING_ADAPTER")
    reverse_image_adapter: str = Field(default="mock", validation_alias="REVERSE_IMAGE_ADAPTER")
    erp_adapter: str = Field(default="mock", validation_alias="ERP_ADAPTER")
    medical_records_adapter: str = Field(default="mock", validation_alias="MEDICAL_RECORDS_ADAPTER")

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

    @field_validator("audit_log_retention_years_after_purge", mode="before")
    @classmethod
    def _coerce_audit_log_retention_years(cls, v: Any) -> int | None:
        msg = (
            "AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE must be unset, empty, or a non-negative integer"
        )
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            raise ValueError(msg)
        if isinstance(v, int):
            if v < 0:
                raise ValueError(msg)
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                n = int(s)
            except ValueError as e:
                raise ValueError(msg) from e
            if n < 0:
                raise ValueError(msg)
            return n
        raise ValueError(msg)

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

    def _read_state_retention_json_root(self) -> dict[str, Any] | None:
        """Load ``state_retention_path`` as a JSON object, or None if missing/unreadable."""
        path = Path(self.paths.state_retention_path)
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
        return data if isinstance(data, dict) else None

    @cached_property
    def _cached_state_retention_json_root(self) -> dict[str, Any] | None:
        """Parse ``state_retention_path`` once per Settings instance (see ``reload_settings()``)."""
        return self._read_state_retention_json_root()

    @staticmethod
    def _parse_state_int_map(raw: dict[str, Any]) -> dict[str, int]:
        """Parse state code -> years entries; only integers >= 1 are kept."""
        result: dict[str, int] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, (int, float)):
                y = int(v)
                if y >= 1:
                    result[k.strip()] = y
        return result

    @staticmethod
    def _parse_purge_after_archive_state_int_map(raw: dict[str, Any]) -> dict[str, int]:
        """Parse state -> purge-after-archive years; integers >= 0 kept (0 = eligible from archive date)."""
        result: dict[str, int] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, (int, float)):
                y = int(v)
                if y >= 0:
                    result[k.strip()] = y
        return result

    def get_retention_by_state(self) -> dict[str, int]:
        """Return state-specific retention periods (years). Empty dict = use default only."""
        data = self._cached_state_retention_json_root
        if data is None:
            return {}
        raw = data.get("retention_by_state", data)
        if not isinstance(raw, dict):
            return {}
        return self._parse_state_int_map(raw)

    def get_purge_after_archive_by_state(self) -> dict[str, int]:
        """Return per-state purge-after-archive periods (years). Empty dict = use global only.

        Values may be ``0`` (purge eligible immediately after archive, same calendar-day cutoff).
        """
        data = self._cached_state_retention_json_root
        if data is None:
            return {}
        raw = data.get("purge_after_archive_by_state", {})
        if not isinstance(raw, dict):
            return {}
        return self._parse_purge_after_archive_state_int_map(raw)

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
