"""Pluggable secret provider for loading secrets at startup.

Supports three backends, selected by the ``SECRET_PROVIDER`` environment variable:

``env`` (default)
    Read secrets from environment variables / ``.env`` file — the current
    behaviour; no external calls made.

``aws_secrets_manager``
    Fetch a single JSON secret from **AWS Secrets Manager** and merge its
    key/value pairs into the process environment before Pydantic Settings
    instantiates.  Requires the ``boto3`` package (``pip install -e '.[s3]'``).

``hashicorp_vault``
    Fetch secrets from **HashiCorp Vault** (KV v2 or KV v1) and merge them
    into the process environment.  Requires the ``hvac`` package
    (``pip install hvac``).

Merging behaviour
-----------------
Only keys listed in the internal allowlist (well-known application env-var
names such as ``JWT_SECRET``, ``OPENAI_API_KEY``, etc.) are injected.  Other
keys in the JSON or Vault payload are ignored with a warning.  Values are
injected into ``os.environ`` *only when the key is not already present*.  This
means a hard-coded env var always wins, which lets developers override
individual secrets during testing without touching the secret store.

Provider configuration variables
---------------------------------
See `.env.example` (``# Secret management`` section) and
`docs/configuration.md` for the full list of supported variables.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist: only these keys may be copied from an external store into
# ``os.environ``.  Prevents arbitrary keys in the secret JSON from polluting
# the process environment.
# ---------------------------------------------------------------------------
_SECRET_ENV_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "JWT_SECRET",
    "API_KEYS",
    "CLAIMS_API_KEY",
    "WEBHOOK_SECRET",
    "SENDGRID_API_KEY",
    "TWILIO_AUTH_TOKEN",
    "LANGSMITH_API_KEY",
    "OTP_PEPPER",
    "DATABASE_URL",
    "READ_REPLICA_DATABASE_URL",
)

_SECRET_ENV_KEYS_FROZEN: frozenset[str] = frozenset(_SECRET_ENV_KEYS)


def _scalar_entries_from_mapping(data: dict[str, Any]) -> dict[str, str]:
    """Keep only string/numeric secret values; log a warning for unsupported types."""
    out: dict[str, str] = {}
    for key, value in data.items():
        # ``bool`` is a subclass of ``int`` — exclude it explicitly.
        if isinstance(value, bool):
            logger.warning(
                "[secret_provider] Skipping secret key %r (unsupported type bool); "
                "store strings, integers, or floats only.",
                key,
            )
        elif isinstance(value, (str, int, float)):
            out[key] = str(value)
        else:
            logger.warning(
                "[secret_provider] Skipping secret key %r (unsupported type %s); "
                "store strings, integers, or floats only.",
                key,
                type(value).__name__,
            )
    return out


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class SecretProvider(ABC):
    """Abstract base class for secret backends."""

    @abstractmethod
    def get_secrets(self) -> dict[str, str]:
        """Return a mapping of env-var name → secret value.

        Keys that are absent from the returned dict are left unchanged in the
        process environment.
        """

    def inject(self) -> None:
        """Fetch secrets and inject missing ones into ``os.environ``."""
        try:
            secrets = self.get_secrets()
        except Exception as exc:
            # Surface the error clearly; the application will fail fast when
            # required env vars are absent (Pydantic validation).
            raise RuntimeError(
                f"[secret_provider] Failed to load secrets from "
                f"{self.__class__.__name__}: {exc}"
            ) from exc

        injected: list[str] = []
        for key, value in secrets.items():
            if key not in _SECRET_ENV_KEYS_FROZEN:
                logger.warning(
                    "[secret_provider] Skipping secret key %r: not in the application "
                    "secret allowlist (see docs/configuration.md — Secret Management).",
                    key,
                )
                continue
            if key not in os.environ:
                os.environ[key] = value
                injected.append(key)

        if injected:
            logger.debug(
                "[secret_provider] Injected %d secret(s) from %s: %s",
                len(injected),
                self.__class__.__name__,
                ", ".join(injected),
            )


# ---------------------------------------------------------------------------
# Environment / .env provider (default — no-op, Pydantic handles it)
# ---------------------------------------------------------------------------


class EnvSecretProvider(SecretProvider):
    """No-op provider: secrets already come from the environment / .env file."""

    def get_secrets(self) -> dict[str, str]:
        return {}


# ---------------------------------------------------------------------------
# AWS Secrets Manager provider
# ---------------------------------------------------------------------------


class AwsSecretsManagerProvider(SecretProvider):
    """Load secrets from a single AWS Secrets Manager JSON secret.

    Required variables
    ------------------
    ``AWS_SECRET_NAME``
        ARN or friendly name of the Secrets Manager secret.  The secret value
        must be a JSON object whose keys match the application env-var names
        (e.g. ``{"JWT_SECRET": "...", "OPENAI_API_KEY": "..."}``) .

    Optional variables
    ------------------
    ``AWS_REGION``
        AWS region (e.g. ``us-east-1``).  Falls back to the SDK default
        region resolution chain (``AWS_DEFAULT_REGION``, ``~/.aws/config``,
        instance metadata).
    ``AWS_SECRET_VERSION_ID`` / ``AWS_SECRET_VERSION_STAGE``
        Pin to a specific version or staging label.  Omit to use the current
        ``AWSCURRENT`` value.
    """

    def __init__(self) -> None:
        self.secret_name: str = os.environ.get("AWS_SECRET_NAME", "").strip()
        self.region: str | None = os.environ.get("AWS_REGION", "").strip() or None
        self.version_id: str | None = (
            os.environ.get("AWS_SECRET_VERSION_ID", "").strip() or None
        )
        self.version_stage: str | None = (
            os.environ.get("AWS_SECRET_VERSION_STAGE", "").strip() or None
        )

        if not self.secret_name:
            raise ValueError(
                "AWS_SECRET_NAME must be set when SECRET_PROVIDER=aws_secrets_manager"
            )

    def get_secrets(self) -> dict[str, str]:
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for SECRET_PROVIDER=aws_secrets_manager. "
                "Install it with: pip install -e '.[s3]'"
            ) from exc

        import json

        kwargs: dict[str, Any] = {"SecretId": self.secret_name}
        if self.region:
            client = boto3.client("secretsmanager", region_name=self.region)
        else:
            client = boto3.client("secretsmanager")

        if self.version_id:
            kwargs["VersionId"] = self.version_id
        if self.version_stage:
            kwargs["VersionStage"] = self.version_stage

        try:
            response = client.get_secret_value(**kwargs)
        except ClientError as exc:
            raise RuntimeError(
                f"Failed to retrieve secret '{self.secret_name}' from AWS Secrets Manager: {exc}"
            ) from exc

        secret_string = response.get("SecretString")
        if not secret_string:
            raise ValueError(
                f"AWS Secrets Manager secret '{self.secret_name}' has no SecretString value. "
                "Binary secrets are not supported; store secrets as a JSON object."
            )

        try:
            parsed: Any = json.loads(secret_string)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"AWS Secrets Manager secret '{self.secret_name}' is not valid JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                f"AWS Secrets Manager secret '{self.secret_name}' must be a JSON object, "
                f"not {type(parsed).__name__}."
            )

        return _scalar_entries_from_mapping(parsed)


# ---------------------------------------------------------------------------
# HashiCorp Vault provider
# ---------------------------------------------------------------------------


class HashiCorpVaultProvider(SecretProvider):
    """Load secrets from a HashiCorp Vault KV secret.

    Required variables
    ------------------
    ``VAULT_ADDR``
        Vault server address, e.g. ``https://vault.example.com:8200``.
    ``VAULT_PATH``
        Secret path **relative to the KV mount** (not the full API path).  For
        example with the default mount ``secret`` and KV v2, use
        ``claim-agent/production`` — *not* ``secret/data/claim-agent``.

    Authentication (one of)
    -----------------------
    ``VAULT_TOKEN``
        Static token — suitable for short-lived CI environments or testing.
    ``VAULT_ROLE_ID`` + ``VAULT_SECRET_ID``
        AppRole auth method — recommended for production deployments.

    Optional variables
    ------------------
    ``VAULT_MOUNT_POINT``
        KV engine mount name (default: ``secret``).  Use when secrets live under
        a non-default mount such as ``kv``.
    ``VAULT_KV_VERSION``
        ``2`` (default) or ``1``.
    ``VAULT_NAMESPACE``
        Vault Enterprise namespace (e.g. ``admin/``).
    ``VAULT_CA_CERT``
        Path to a PEM CA bundle for TLS verification.  Set ``VAULT_SKIP_VERIFY=true``
        to disable certificate verification (not recommended in production).
    """

    def __init__(self) -> None:
        self.addr: str = os.environ.get("VAULT_ADDR", "").strip()
        self.path: str = os.environ.get("VAULT_PATH", "").strip()
        self.mount_point: str = (
            os.environ.get("VAULT_MOUNT_POINT", "secret").strip() or "secret"
        )
        self.token: str | None = os.environ.get("VAULT_TOKEN", "").strip() or None
        self.role_id: str | None = os.environ.get("VAULT_ROLE_ID", "").strip() or None
        self.secret_id: str | None = (
            os.environ.get("VAULT_SECRET_ID", "").strip() or None
        )
        raw_kv = os.environ.get("VAULT_KV_VERSION", "2").strip()
        try:
            kv_parsed = int(raw_kv)
        except ValueError as exc:
            raise ValueError(
                f"VAULT_KV_VERSION must be the integer 1 or 2, got {raw_kv!r}"
            ) from exc
        if kv_parsed not in (1, 2):
            raise ValueError(f"VAULT_KV_VERSION must be 1 or 2, got {kv_parsed}")
        self.kv_version: int = kv_parsed
        self.namespace: str | None = (
            os.environ.get("VAULT_NAMESPACE", "").strip() or None
        )
        self.ca_cert: str | None = os.environ.get("VAULT_CA_CERT", "").strip() or None
        self.skip_verify: bool = (
            os.environ.get("VAULT_SKIP_VERIFY", "false").strip().lower() == "true"
        )

        if not self.addr:
            raise ValueError("VAULT_ADDR must be set when SECRET_PROVIDER=hashicorp_vault")
        if not self.path:
            raise ValueError("VAULT_PATH must be set when SECRET_PROVIDER=hashicorp_vault")
        if not self.token and not (self.role_id and self.secret_id):
            raise ValueError(
                "Either VAULT_TOKEN or both VAULT_ROLE_ID and VAULT_SECRET_ID "
                "must be set when SECRET_PROVIDER=hashicorp_vault"
            )

    def _build_client(self) -> Any:  # hvac.Client; hvac has no bundled type stubs
        """Return an authenticated hvac client."""
        try:
            import hvac
        except ImportError as exc:
            raise ImportError(
                "hvac is required for SECRET_PROVIDER=hashicorp_vault. "
                "Install it with: pip install hvac"
            ) from exc

        tls_config: dict[str, Any] = {}
        if self.ca_cert:
            tls_config["verify"] = self.ca_cert
        elif self.skip_verify:
            tls_config["verify"] = False

        client = hvac.Client(
            url=self.addr,
            namespace=self.namespace,
            **tls_config,
        )

        if self.token:
            client.token = self.token
        else:
            # AppRole auth
            client.auth.approle.login(
                role_id=self.role_id,
                secret_id=self.secret_id,
            )

        if not client.is_authenticated():
            raise RuntimeError(
                "Vault authentication failed — check VAULT_TOKEN or AppRole credentials."
            )

        return client

    def get_secrets(self) -> dict[str, str]:
        client = self._build_client()

        try:
            if self.kv_version == 2:
                response = client.secrets.kv.v2.read_secret_version(
                    path=self.path,
                    mount_point=self.mount_point,
                )
                data: dict[str, Any] = response["data"]["data"]
            else:
                response = client.secrets.kv.v1.read_secret(
                    path=self.path,
                    mount_point=self.mount_point,
                )
                data = response["data"]
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read Vault secret at mount={self.mount_point!r} path="
                f"{self.path!r}: {exc}"
            ) from exc

        return _scalar_entries_from_mapping(data)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[str, type[SecretProvider]] = {
    "env": EnvSecretProvider,
    "aws_secrets_manager": AwsSecretsManagerProvider,
    "hashicorp_vault": HashiCorpVaultProvider,
}


def get_secret_provider() -> SecretProvider:
    """Return the configured SecretProvider instance.

    The backend is selected by the ``SECRET_PROVIDER`` environment variable
    (default: ``env``).
    """
    provider_name = os.environ.get("SECRET_PROVIDER", "env").strip().lower()
    provider_cls = _PROVIDER_MAP.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown SECRET_PROVIDER '{provider_name}'. "
            f"Valid values: {', '.join(_PROVIDER_MAP)}"
        )
    return provider_cls()


def load_secrets_into_env() -> None:
    """Fetch secrets from the configured provider and inject them into ``os.environ``.

    This function is called once at application startup, before Pydantic
    Settings initialises.  It is safe to call multiple times (idempotent
    because ``inject()`` never overwrites existing env vars).
    """
    provider = get_secret_provider()
    provider.inject()
