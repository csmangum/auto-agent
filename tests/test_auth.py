"""Unit tests for api/auth."""

import pytest

from claim_agent.api.auth import AuthContext, is_auth_required, verify_token
from claim_agent.config import reload_settings


class TestAuthContext:
    def test_dataclass_fields(self):
        ctx = AuthContext(identity="key-abc123", role="adjuster")
        assert ctx.identity == "key-abc123"
        assert ctx.role == "adjuster"


class TestVerifyToken:
    def test_empty_token_returns_none(self):
        assert verify_token("") is None
        assert verify_token("   ") is None

    def test_api_key_lookup(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "secret-key-123:adjuster")
        reload_settings()
        ctx = verify_token("secret-key-123")
        assert ctx is not None
        assert ctx.role == "adjuster"
        assert ctx.identity.startswith("key-")

    def test_api_key_with_role(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "admin-key:admin,super-key:supervisor")
        reload_settings()
        ctx = verify_token("admin-key")
        assert ctx is not None
        assert ctx.role == "admin"
        ctx2 = verify_token("super-key")
        assert ctx2 is not None
        assert ctx2.role == "supervisor"

    def test_claims_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.setenv("CLAIMS_API_KEY", "legacy-key")
        reload_settings()
        ctx = verify_token("legacy-key")
        assert ctx is not None
        assert ctx.role == "admin"

    def test_unknown_api_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "valid-key:adjuster")
        reload_settings()
        assert verify_token("wrong-key") is None

    def test_jwt_verification_requires_pyjwt(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        reload_settings()
        # Without PyJWT installed, JWT path returns None (or we'd need to mock)
        # With PyJWT: we could test valid JWT. Skip JWT tests if not installed.
        try:
            import jwt as _  # noqa: F401
        except ImportError:
            ctx = verify_token("Bearer.eyJzdWIiOiJ0ZXN0In0.x")
            assert ctx is None
            return
        # If PyJWT is installed, we need a valid JWT. Create one.
        import jwt as pyjwt

        payload = {"sub": "user-123", "role": "adjuster"}
        token = pyjwt.encode(
            payload, "a" * 32, algorithm="HS256"
        )
        ctx = verify_token(token)
        assert ctx is not None
        assert ctx.identity == "user-123"
        assert ctx.role == "adjuster"

    def test_jwt_invalid_role_returns_none(self, monkeypatch):
        try:
            import jwt as pyjwt
        except ImportError:
            pytest.skip("PyJWT not installed")
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        reload_settings()
        payload = {"sub": "user-123", "role": "unknown_role"}
        token = pyjwt.encode(payload, "a" * 32, algorithm="HS256")
        assert verify_token(token) is None

    def test_jwt_refresh_token_use_rejected_for_api(self, monkeypatch):
        try:
            import jwt as pyjwt
        except ImportError:
            pytest.skip("PyJWT not installed")
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        reload_settings()
        payload = {"sub": "user-123", "role": "adjuster", "token_use": "refresh"}
        token = pyjwt.encode(payload, "a" * 32, algorithm="HS256")
        assert verify_token(token) is None

    def test_api_key_three_segment_identity(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-a:adjuster:user-42")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        reload_settings()
        ctx = verify_token("sk-a")
        assert ctx is not None
        assert ctx.identity == "user-42"
        assert ctx.role == "adjuster"


class TestIsAuthRequired:
    def test_false_when_no_config(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        reload_settings()
        assert is_auth_required() is False

    def test_true_when_api_keys_set(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "key:admin")
        reload_settings()
        assert is_auth_required() is True

    def test_true_when_jwt_secret_set(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        reload_settings()
        assert is_auth_required() is True


class TestCheckAuthConfiguration:
    """Tests for the server startup auth guard."""

    def _check(self):
        from claim_agent.api.server import _check_auth_configuration

        _check_auth_configuration()

    def test_passes_in_dev_environment_without_auth(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "development")
        reload_settings()
        self._check()  # should not raise

    def test_passes_in_dev_shorthand_without_auth(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "dev")
        reload_settings()
        self._check()  # should not raise

    def test_passes_in_test_environment_without_auth(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "test")
        reload_settings()
        self._check()  # should not raise

    def test_raises_in_production_without_auth(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        with pytest.raises(RuntimeError, match="Authentication is not configured"):
            self._check()

    def test_raises_in_staging_without_auth(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "staging")
        reload_settings()
        with pytest.raises(RuntimeError, match="Authentication is not configured"):
            self._check()

    def test_passes_in_production_with_api_keys(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-prod:admin")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        self._check()  # should not raise

    def test_passes_in_production_with_jwt_secret(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        self._check()  # should not raise

    def test_environment_check_is_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "Development")
        reload_settings()
        self._check()  # should not raise

    def test_legacy_environment_env_var_still_works(self, monkeypatch):
        monkeypatch.delenv("CLAIM_AGENT_ENVIRONMENT", raising=False)
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        reload_settings()
        with pytest.raises(RuntimeError, match="Authentication is not configured"):
            self._check()
