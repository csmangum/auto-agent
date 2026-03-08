"""Pydantic Settings model for centralized configuration.

All configuration is loaded from environment variables (and .env) at startup.
Use get_settings() to access the singleton instance.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)


def _default_project_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------


class RouterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROUTER_", extra="ignore")

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
    model_config = SettingsConfigDict(env_prefix="ESCALATION_", extra="ignore")

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
    model_config = SettingsConfigDict(env_prefix="FRAUD_", extra="ignore")

    multiple_claims_days: int = 90
    multiple_claims_threshold: int = 2

    @field_validator("multiple_claims_days", mode="before")
    @classmethod
    def _coerce_multiple_claims_days(cls, v: Any) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            return 90
    fraud_keyword_score: int = 20
    multiple_claims_score: int = 25
    timing_anomaly_score: int = 15
    damage_mismatch_score: int = 20
    high_risk_threshold: int = 50
    medium_risk_threshold: int = 30
    critical_risk_threshold: int = 75
    critical_indicator_count: int = 5


class ValuationConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VALUATION_", extra="ignore")

    default_base_value: float = 12000
    depreciation_per_year: float = 500
    min_vehicle_value: float = 2000
    default_deductible: int = 500
    min_payout_vehicle_value: float = 100


class PartialLossConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARTIAL_LOSS_", extra="ignore")

    threshold: float = 0.75
    labor_hours_rni_per_part: float = 1.5
    labor_hours_paint_body: float = 2.0
    labor_hours_min: float = 2.0


class WebhookConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBHOOK_", extra="ignore")

    urls: list[str] = Field(default_factory=list)
    secret: str = ""
    max_retries: int = 5
    enabled: bool = True
    shop_url: str | None = None
    dead_letter_path: str | None = None

    @field_validator("urls", mode="before")
    @classmethod
    def _parse_urls(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [u.strip() for u in v if u and str(u).strip()]
        if isinstance(v, str):
            urls_raw = v.strip() or os.environ.get("WEBHOOK_URL", "").strip()
        else:
            urls_raw = os.environ.get("WEBHOOK_URLS", "").strip() or os.environ.get("WEBHOOK_URL", "").strip()
        if urls_raw:
            return [u.strip() for u in urls_raw.split(",") if u.strip()]
        return []


class NotificationConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOTIFICATION_", extra="ignore")

    email_enabled: bool = False
    sms_enabled: bool = False


class TracingConfig(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_prefix="",
        env_nested_delimiter="__",
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

    @field_validator(
        "langsmith_enabled", "trace_llm_calls", "trace_tool_calls", "log_prompts", "log_responses",
        mode="before",
    )
    @classmethod
    def _parse_bool_env(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")


class LoggingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAIM_AGENT_", extra="ignore")

    log_format: str = "human"
    log_level: str = "INFO"
    mask_pii: bool = True


class PathsConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    claims_db_path: str = "data/claims.db"
    mock_db_path: str = "data/mock_db.json"
    ca_compliance_path: str = "data/california_auto_compliance.json"
    attachment_storage_path: str = "data/attachments"

    @classmethod
    def model_construct(cls, **kwargs: Any) -> "PathsConfig":
        return cls(
            claims_db_path=os.environ.get("CLAIMS_DB_PATH", kwargs.get("claims_db_path", "data/claims.db")),
            mock_db_path=os.environ.get("MOCK_DB_PATH", kwargs.get("mock_db_path", "data/mock_db.json")),
            ca_compliance_path=os.environ.get("CA_COMPLIANCE_PATH", kwargs.get("ca_compliance_path", "data/california_auto_compliance.json")),
            attachment_storage_path=os.environ.get("ATTACHMENT_STORAGE_PATH", kwargs.get("attachment_storage_path", "data/attachments")),
        )


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key: str = ""
    api_base: str = ""
    model_name: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o"

    @classmethod
    def model_construct(cls, **kwargs: Any) -> "LLMConfig":
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", kwargs.get("api_key", "")),
            api_base=os.environ.get("OPENAI_API_BASE", kwargs.get("api_base", "")),
            model_name=os.environ.get("OPENAI_MODEL_NAME", kwargs.get("model_name", "gpt-4o-mini")),
            vision_model=os.environ.get("OPENAI_VISION_MODEL", kwargs.get("vision_model", "gpt-4o")),
        )


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_keys: dict[str, str] = Field(default_factory=dict)
    jwt_secret: str | None = None
    cors_origins: list[str] = Field(default_factory=list)

    @classmethod
    def model_construct(cls, **kwargs: Any) -> "AuthConfig":
        api_keys: dict[str, str] = {}
        api_keys_raw = os.environ.get("API_KEYS", "").strip()
        if api_keys_raw:
            for part in api_keys_raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" in part:
                    key, role = part.split(":", 1)
                    api_keys[key.strip()] = role.strip()
                else:
                    api_keys[part] = "admin"
        else:
            claims_key = os.environ.get("CLAIMS_API_KEY", "").strip()
            if claims_key:
                api_keys[claims_key] = "admin"

        jwt_raw = os.environ.get("JWT_SECRET", "").strip()
        jwt_secret = jwt_raw if jwt_raw else None

        cors_raw = os.environ.get("CORS_ORIGINS", "")
        if cors_raw.strip():
            cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        else:
            cors_origins = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ]

        return cls(api_keys=api_keys, jwt_secret=jwt_secret, cors_origins=cors_origins)


# ---------------------------------------------------------------------------
# Adapter backends (dynamic env keys)
# ---------------------------------------------------------------------------

ADAPTER_ENV_KEYS: dict[str, str] = {
    "policy": "POLICY_ADAPTER",
    "valuation": "VALUATION_ADAPTER",
    "repair_shop": "REPAIR_SHOP_ADAPTER",
    "parts": "PARTS_ADAPTER",
    "siu": "SIU_ADAPTER",
}
VALID_ADAPTER_BACKENDS: frozenset[str] = frozenset({"mock", "stub"})


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
    paths: PathsConfig = Field(default_factory=PathsConfig.model_construct)
    llm: LLMConfig = Field(default_factory=LLMConfig.model_construct)
    auth: AuthConfig = Field(default_factory=AuthConfig.model_construct)

    # Flat fields for compatibility (duplicate detection, high-value, etc.)
    duplicate_similarity_threshold: int = 40
    duplicate_similarity_threshold_high_value: int = 60
    duplicate_days_window: int = 3
    high_value_damage_threshold: int = 25_000
    high_value_vehicle_threshold: int = 50_000
    pre_routing_fraud_damage_ratio: float = 0.9
    max_tokens_per_claim: int = Field(default=100_000, validation_alias="CLAIM_AGENT_MAX_TOKENS_PER_CLAIM")
    max_llm_calls_per_claim: int = Field(default=50, validation_alias="CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM")
    crew_verbose: bool = Field(default=True, validation_alias="CREWAI_VERBOSE")
    retention_period_years: int = 5

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

    @model_validator(mode="before")
    @classmethod
    def _set_env_prefixes(cls, data: Any) -> Any:
        return data

    @model_validator(mode="after")
    def _resolve_retention(self) -> Self:
        raw = os.environ.get("RETENTION_PERIOD_YEARS", "").strip()
        if raw:
            try:
                v = int(raw)
                if v >= 1:
                    object.__setattr__(self, "retention_period_years", v)
                    return self
            except ValueError:
                pass
            _log.warning(
                "RETENTION_PERIOD_YEARS is set but invalid (%r); using compliance/default.",
                raw,
            )
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

    def get_adapter_backend(self, adapter_name: str) -> str:
        env_key = ADAPTER_ENV_KEYS.get(adapter_name, f"{adapter_name.upper()}_ADAPTER")
        raw = os.environ.get(env_key)
        if raw is None:
            return "mock"
        backend = raw.strip().lower()
        return backend or "mock"
