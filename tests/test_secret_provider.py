"""Tests for the pluggable secret provider (claim_agent.config.secret_provider)."""

from __future__ import annotations

import json
import os
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
        """inject() sets keys that are absent from os.environ."""
        monkeypatch.delenv("CLAIM_AGENT_NEW_SECRET", raising=False)
        provider = _FixedProvider({"CLAIM_AGENT_NEW_SECRET": "supersecret"})
        provider.inject()
        assert os.environ.get("CLAIM_AGENT_NEW_SECRET") == "supersecret"

    def test_does_not_overwrite_existing_keys(self, monkeypatch):
        """inject() never overwrites env vars that are already set."""
        monkeypatch.setenv("CLAIM_AGENT_EXISTING", "original")
        provider = _FixedProvider({"CLAIM_AGENT_EXISTING": "from_store"})
        provider.inject()
        assert os.environ["CLAIM_AGENT_EXISTING"] == "original"

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
        monkeypatch.delenv("CLAIM_AGENT_INJECT_TEST", raising=False)
        with patch(
            "claim_agent.config.secret_provider.get_secret_provider",
            return_value=_FixedProvider({"CLAIM_AGENT_INJECT_TEST": "value123"}),
        ):
            load_secrets_into_env()
        assert os.environ.get("CLAIM_AGENT_INJECT_TEST") == "value123"


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

        with patch("boto3.client", return_value=mock_client):
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

        with patch("boto3.client", return_value=mock_client):
            provider = AwsSecretsManagerProvider()
            with pytest.raises(ValueError, match="not valid JSON"):
                provider.get_secrets()

    def test_empty_secret_string_raises(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": ""}

        with patch("boto3.client", return_value=mock_client):
            provider = AwsSecretsManagerProvider()
            with pytest.raises(ValueError, match="no SecretString"):
                provider.get_secrets()

    def test_client_error_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        try:
            from botocore.exceptions import ClientError
        except ImportError:
            pytest.skip("botocore not installed")

        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
            "GetSecretValue",
        )

        with patch("boto3.client", return_value=mock_client):
            provider = AwsSecretsManagerProvider()
            with pytest.raises(RuntimeError, match="Failed to retrieve secret"):
                provider.get_secrets()

    def test_optional_version_id_passed_to_client(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("AWS_SECRET_VERSION_ID", "abc-123")

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"KEY": "val"})
        }

        with patch("boto3.client", return_value=mock_client):
            provider = AwsSecretsManagerProvider()
            provider.get_secrets()
            call_kwargs = mock_client.get_secret_value.call_args[1]
            assert call_kwargs.get("VersionId") == "abc-123"


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
        with pytest.raises(RuntimeError, match="Failed to read Vault secret"):
            provider.get_secrets()
