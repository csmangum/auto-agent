"""Configuration for claim agent."""

from claim_agent.config.settings_model import (
    ADAPTER_ENV_KEYS,
    VALID_ADAPTER_BACKENDS,
    Settings,
)
from claim_agent.config.settings_model import (
    AuthConfig,
    EscalationConfig,
    FraudConfig,
    LoggingConfig,
    LLMConfig,
    NotificationConfig,
    PathsConfig,
    PartialLossConfig,
    RouterConfig,
    TracingConfig,
    ValuationConfig,
    WebhookConfig,
)

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings instance. Loads from env on first call."""
    global _settings
    if _settings is None:
        from dotenv import load_dotenv

        load_dotenv()
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment. For tests that need fresh config."""
    global _settings
    from dotenv import load_dotenv

    load_dotenv()
    _settings = Settings()
    return _settings
