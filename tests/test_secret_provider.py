"""Tests for the pluggable secret provider (claim_agent.config.secret_provider)."""

from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.config.secret_provider import (
    AwsSecretsManagerProvider,
    EnvSecretProvider,
    HashiCorpVaultProvider,
    SecretProvider,
    get_secret_provider,
    load_secrets_into_env,
)


def _install_fake_boto3_stack(monkeypatch: pytest.MonkeyPatch, mock_client: MagicMock) -> None:
    """Stub boto3/botocore so AWS provider tests run without optional ``boto3`` installed."""
    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "boto3", boto3_mod)

    exc_mod = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        """Minimal stub matching ``botocore.exceptions.ClientError`` shape."""

        def __init__(self, error_response: object, operation_name: str) -> None:
            self.response = error_response
            self.operation_name = operation_name
            super().__init__(str(error_response))

    exc_mod.ClientError = ClientError
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exc_mod)
    botocore_pkg = types.ModuleType("botocore")
    botocore_pkg.exceptions = exc_mod
    monkeypatch.setitem(sys.modules, "botocore", botocore_pkg)


# ---------------------------------------------------------------------------
# EnvSecretProvider
# ---------------------------------------------------------------------------


class TestEnvSecretProvider:
    def test_returns_empty_dict(self):
        """EnvSecretProvider.get_secrets() is a no-op — secrets already in env."""
        provider = EnvSecretProvider()
        assert provider.get_secrets() == {}

    def test_inject_does_not_modify_env(self, monkeypatch):
        """inject() with no secrets returned leaves os.environ unchanged."""
        sentinel_key = "CLAIM_AGENT_TEST_SENTINEL"
        monkeypatch.setenv(sentinel_key, "original")
        provider = EnvSecretProvider()
        provider.inject()
        assert os.environ[sentinel_key] == "original"

    def test_is_secret_provider_subclass(self):
        assert isinstance(EnvSecretProvider(), SecretProvider)


# ---------------------------------------------------------------------------
# SecretProvider.inject() base behaviour
# ---------------------------------------------------------------------------


class _FixedProvider(SecretProvider):
    """Test double: always returns a fixed dict."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def get_secrets(self) -> dict[str, str]:
        return self._secrets


class TestProviderInject:
    def test_injects_missing_keys(self, monkeypatch):
        """inject() sets allowlisted keys that are absent from os.environ."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        try:
            provider = _FixedProvider({"JWT_SECRET": "supersecret"})
            provider.inject()
            assert os.environ.get("JWT_SECRET") == "supersecret"
        finally:
            os.environ.pop("JWT_SECRET", None)

    def test_does_not_overwrite_existing_keys(self, monkeypatch):
        """inject() never overwrites env vars that are already set."""
        monkeypatch.setenv("JWT_SECRET", "original")
        provider = _FixedProvider({"JWT_SECRET": "from_store"})
        provider.inject()
        assert os.environ["JWT_SECRET"] == "original"

    def test_skips_keys_not_in_allowlist(self, monkeypatch, caplog):
        """inject() ignores unknown keys from the secret store."""
        import logging

        monkeypatch.delenv("CLAIM_AGENT_UNKNOWN_FROM_STORE", raising=False)
        provider = _FixedProvider({"CLAIM_AGENT_UNKNOWN_FROM_STORE": "x"})
        with caplog.at_level(logging.WARNING, logger="claim_agent.config.secret_provider"):
            provider.inject()
        assert os.environ.get("CLAIM_AGENT_UNKNOWN_FROM_STORE") is None
        assert any("Skipping secret key" in r.message for r in caplog.records)

    def test_raises_runtime_error_on_provider_failure(self):
        """inject() wraps provider exceptions in RuntimeError."""

        class _BrokenProvider(SecretProvider):
            def get_secrets(self):
                raise ConnectionError("network failure")

        with pytest.raises(RuntimeError, match="Failed to load secrets"):
            _BrokenProvider().inject()


# ---------------------------------------------------------------------------
# get_secret_provider factory
# ---------------------------------------------------------------------------


class TestGetSecretProvider:
    def test_default_is_env_provider(self, monkeypatch):
        monkeypatch.delenv("SECRET_PROVIDER", raising=False)
        provider = get_secret_provider()
        assert isinstance(provider, EnvSecretProvider)

    def test_env_explicit(self, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "env")
        assert isinstance(get_secret_provider(), EnvSecretProvider)

    def test_aws_provider_selected(self, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "aws_secrets_manager")
        monkeypatch.setenv("AWS_SECRET_NAME", "test-secret")
        provider = get_secret_provider()
        assert isinstance(provider, AwsSecretsManagerProvider)

    def test_vault_provider_selected(self, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "hashicorp_vault")
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "secret/claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        provider = get_secret_provider()
        assert isinstance(provider, HashiCorpVaultProvider)

    def test_invalid_provider_raises(self, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "unsupported_backend")
        with pytest.raises(ValueError, match="Unknown SECRET_PROVIDER"):
            get_secret_provider()

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "ENV")
        assert isinstance(get_secret_provider(), EnvSecretProvider)


# ---------------------------------------------------------------------------
# load_secrets_into_env integration
# ---------------------------------------------------------------------------


class TestLoadSecretsIntoEnv:
    def test_env_provider_is_noop(self, monkeypatch):
        """load_secrets_into_env() with env backend does not raise."""
        monkeypatch.delenv("SECRET_PROVIDER", raising=False)
        load_secrets_into_env()  # should not raise

    def test_injects_via_fixed_provider(self, monkeypatch):
        """load_secrets_into_env() delegates to the configured provider."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        try:
            with patch(
                "claim_agent.config.secret_provider.get_secret_provider",
                return_value=_FixedProvider({"OPENAI_API_KEY": "value123"}),
            ):
                load_secrets_into_env()
            assert os.environ.get("OPENAI_API_KEY") == "value123"
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# AwsSecretsManagerProvider
# ---------------------------------------------------------------------------


class TestAwsSecretsManagerProvider:
    def test_missing_aws_secret_name_raises(self, monkeypatch):
        monkeypatch.delenv("AWS_SECRET_NAME", raising=False)
        with pytest.raises(ValueError, match="AWS_SECRET_NAME"):
            AwsSecretsManagerProvider()

    def test_get_secrets_returns_parsed_json(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        secret_data = {"JWT_SECRET": "abc123", "OPENAI_API_KEY": "sk-test"}
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(secret_data)
        }

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        result = provider.get_secrets()

        assert result == secret_data

    def test_missing_boto3_raises_import_error(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        provider = AwsSecretsManagerProvider()

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="boto3 is required"):
                provider.get_secrets()

    def test_non_json_secret_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "not-json"}

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        with pytest.raises(ValueError, match="not valid JSON"):
            provider.get_secrets()

    def test_empty_secret_string_raises(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": ""}

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        with pytest.raises(ValueError, match="no SecretString"):
            provider.get_secrets()

    def test_client_error_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        mock_client = MagicMock()
        _install_fake_boto3_stack(monkeypatch, mock_client)
        client_err = sys.modules["botocore.exceptions"].ClientError
        mock_client.get_secret_value.side_effect = client_err(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
            "GetSecretValue",
        )

        provider = AwsSecretsManagerProvider()
        with pytest.raises(RuntimeError, match="Failed to retrieve secret"):
            provider.get_secrets()

    def test_optional_version_id_passed_to_client(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("AWS_SECRET_VERSION_ID", "abc-123")

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"JWT_SECRET": "val"})
        }

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        provider.get_secrets()
        call_kwargs = mock_client.get_secret_value.call_args[1]
        assert call_kwargs.get("VersionId") == "abc-123"

    def test_non_object_json_raises(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps([1, 2])}

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        with pytest.raises(ValueError, match="must be a JSON object"):
            provider.get_secrets()

    def test_boolean_values_skipped_with_warning(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        secret_data = {"JWT_SECRET": "ok", "FEATURE_X": True}
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(secret_data)
        }

        _install_fake_boto3_stack(monkeypatch, mock_client)
        provider = AwsSecretsManagerProvider()
        with caplog.at_level(logging.WARNING, logger="claim_agent.config.secret_provider"):
            result = provider.get_secrets()
        assert result == {"JWT_SECRET": "ok"}
        assert any("FEATURE_X" in r.message and "bool" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# HashiCorpVaultProvider
# ---------------------------------------------------------------------------


class TestHashiCorpVaultProvider:
    def test_missing_vault_addr_raises(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.setenv("VAULT_PATH", "secret/claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        with pytest.raises(ValueError, match="VAULT_ADDR"):
            HashiCorpVaultProvider()

    def test_missing_vault_path_raises(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.delenv("VAULT_PATH", raising=False)
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        with pytest.raises(ValueError, match="VAULT_PATH"):
            HashiCorpVaultProvider()

    def test_missing_auth_raises(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "secret/claim-agent")
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
        monkeypatch.delenv("VAULT_SECRET_ID", raising=False)
        with pytest.raises(ValueError, match="VAULT_TOKEN"):
            HashiCorpVaultProvider()

    @staticmethod
    def _mock_hvac(monkeypatch, mock_client: MagicMock) -> None:
        """Inject a fake hvac module into sys.modules."""
        import sys

        fake_hvac = MagicMock()
        fake_hvac.Client.return_value = mock_client
        monkeypatch.setitem(sys.modules, "hvac", fake_hvac)

    def test_get_secrets_kv2(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "2")

        secret_data = {"JWT_SECRET": "vault-jwt", "WEBHOOK_SECRET": "wh-sig"}

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": secret_data}
        }
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        result = provider.get_secrets()

        assert result == secret_data

    def test_get_secrets_kv1(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "1")

        secret_data = {"OPENAI_API_KEY": "sk-vault"}

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v1.read_secret.return_value = {"data": secret_data}
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        result = provider.get_secrets()

        assert result == secret_data

    def test_missing_hvac_raises_import_error(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")

        provider = HashiCorpVaultProvider()

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "hvac":
                raise ImportError("No module named 'hvac'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="hvac is required"):
                provider._build_client()

    def test_unauthenticated_raises(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.bad")

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = False
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        with pytest.raises(RuntimeError, match="Vault authentication failed"):
            provider._build_client()

    def test_read_error_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "2")

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.side_effect = Exception(
            "permission denied"
        )
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        with pytest.raises(RuntimeError, match="Failed to read Vault secret at mount"):
            provider.get_secrets()

    def test_invalid_kv_version_raises(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "v2")
        with pytest.raises(ValueError, match="VAULT_KV_VERSION"):
            HashiCorpVaultProvider()

    def test_kv_version_three_raises(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "3")
        with pytest.raises(ValueError, match="VAULT_KV_VERSION"):
            HashiCorpVaultProvider()

    def test_mount_point_passed_to_kv2_read(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent/prod")
        monkeypatch.setenv("VAULT_TOKEN", "s.test")
        monkeypatch.setenv("VAULT_KV_VERSION", "2")
        monkeypatch.setenv("VAULT_MOUNT_POINT", "kv")

        secret_data = {"JWT_SECRET": "vault-jwt"}

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": secret_data}
        }
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        result = provider.get_secrets()

        assert result == secret_data
        mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="claim-agent/prod",
            mount_point="kv",
        )

    def test_get_secrets_kv2_approle(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com:8200")
        monkeypatch.setenv("VAULT_PATH", "claim-agent")
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        monkeypatch.setenv("VAULT_ROLE_ID", "role-id-1")
        monkeypatch.setenv("VAULT_SECRET_ID", "secret-id-1")
        monkeypatch.setenv("VAULT_KV_VERSION", "2")

        secret_data = {"JWT_SECRET": "from-approle"}

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": secret_data}
        }
        self._mock_hvac(monkeypatch, mock_client)

        provider = HashiCorpVaultProvider()
        assert provider.get_secrets() == secret_data
        mock_client.auth.approle.login.assert_called_once_with(
            role_id="role-id-1",
            secret_id="secret-id-1",
        )
