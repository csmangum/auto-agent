"""Pydantic Settings model for centralized configuration.

All configuration is loaded from environment variables (and .env) at startup.
Use get_settings() to access the singleton instance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
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

    @field_validator("multiple_claims_days", mode="before")
    @classmethod
    def _coerce_multiple_claims_days(cls, v: Any) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            return 90


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


class WebhookConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    urls_raw: str = Field(default="", validation_alias="WEBHOOK_URLS")
    url: str = ""
    secret: str = ""
    max_retries: int = 5
    enabled: bool = True
    shop_url: str | None = None
    dead_letter_path: str | None = None

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
    fresh_claims_db_on_startup: bool = Field(
        default=False,
        validation_alias="FRESH_CLAIMS_DB_ON_STARTUP",
    )

    @field_validator("fresh_claims_db_on_startup", mode="before")
    @classmethod
    def _parse_fresh_db(cls, v: Any) -> bool:
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
    "vision": "VISION_ADAPTER",
}
VALID_ADAPTER_BACKENDS: frozenset[str] = frozenset({"mock", "stub"})
VALID_VISION_ADAPTER_BACKENDS: frozenset[str] = frozenset({"real", "mock"})


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
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    fraud: FraudConfig = Field(default_factory=FraudConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    partial_loss: PartialLossConfig = Field(default_factory=PartialLossConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mock_crew: MockCrewConfig = Field(default_factory=MockCrewConfig)
    mock_image: MockImageConfig = Field(default_factory=MockImageConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)

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
    crew_verbose: bool = Field(default=True, validation_alias="CREWAI_VERBOSE")
    retention_period_years: int = 5
    policy_adapter: str = Field(default="mock", validation_alias="POLICY_ADAPTER")
    valuation_adapter: str = Field(default="mock", validation_alias="VALUATION_ADAPTER")
    repair_shop_adapter: str = Field(default="mock", validation_alias="REPAIR_SHOP_ADAPTER")
    parts_adapter: str = Field(default="mock", validation_alias="PARTS_ADAPTER")
    siu_adapter: str = Field(default="mock", validation_alias="SIU_ADAPTER")
    siu_default_state: str = Field(
        default="California",
        validation_alias="SIU_DEFAULT_STATE",
        description="Fallback state for SIU reporting when claim/policy state is missing",
    )
    vision_adapter: str = Field(default="real", validation_alias="VISION_ADAPTER")

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
