"""Configuration for claim agent."""

import threading

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

__all__ = [
    "ADAPTER_ENV_KEYS",
    "AuthConfig",
    "EscalationConfig",
    "FraudConfig",
    "LLMConfig",
    "LoggingConfig",
    "NotificationConfig",
    "PathsConfig",
    "PartialLossConfig",
    "RouterConfig",
    "Settings",
    "TracingConfig",
    "VALID_ADAPTER_BACKENDS",
    "ValuationConfig",
    "WebhookConfig",
    "get_settings",
    "reload_settings",
]

_settings: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """Return the cached Settings instance. Loads from env on first call."""
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment. For tests that need fresh config."""
    global _settings
    with _settings_lock:
        _settings = Settings()
    return _settings
