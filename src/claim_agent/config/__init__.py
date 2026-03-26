"""Configuration for claim agent."""

import threading

from claim_agent.config.secret_provider import load_secrets_into_env
from claim_agent.config.settings_model import (
    ADAPTER_ENV_KEYS,
    VALID_ADAPTER_BACKENDS,
    Settings,
    StateBureauConfig,
)
from claim_agent.config.settings_model import (
    AuthConfig,
    CoverageConfig,
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
    "CoverageConfig",
    "EscalationConfig",
    "FraudConfig",
    "LLMConfig",
    "LoggingConfig",
    "NotificationConfig",
    "PathsConfig",
    "PartialLossConfig",
    "RouterConfig",
    "Settings",
    "StateBureauConfig",
    "TracingConfig",
    "VALID_ADAPTER_BACKENDS",
    "ValuationConfig",
    "WebhookConfig",
    "get_settings",
    "reload_settings",
]

_settings: Settings | None = None
_settings_lock = threading.Lock()
# Track whether secrets have been loaded so we don't call the external provider
# on every get_settings() call (only once per process, or after reload_settings()).
_secrets_loaded: bool = False


def get_settings() -> Settings:
    """Return the cached Settings instance. Loads from env on first call."""
    global _settings, _secrets_loaded
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                if not _secrets_loaded:
                    load_secrets_into_env()
                    _secrets_loaded = True
                _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment. For tests that need fresh config.

    Calls :func:`load_secrets_into_env` on every reload. With
    ``SECRET_PROVIDER=aws_secrets_manager`` or ``hashicorp_vault``, that
    re-fetches from the external store each time (intentional for picking up
    rotated secrets in long-lived processes). Tests typically use the default
    ``env`` provider, which performs no network I/O.
    """
    global _settings, _secrets_loaded
    with _settings_lock:
        load_secrets_into_env()
        _secrets_loaded = True
        _settings = Settings()
    # Keep API CSP / security headers aligned with reloaded settings (tests, secret rotation).
    try:
        from claim_agent.api.server import _refresh_cached_base_security_headers

        _refresh_cached_base_security_headers()
    except Exception:
        pass
    return _settings
