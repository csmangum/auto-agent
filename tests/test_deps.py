"""Unit tests for api/deps."""

from unittest.mock import MagicMock

import pytest

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import get_auth, require_role
from claim_agent.config import reload_settings


def _mock_request(auth: AuthContext | None = None):
    req = MagicMock()
    req.state = MagicMock()
    req.state.auth = auth
    return req


class TestGetAuth:
    def test_returns_none_when_auth_not_required(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        reload_settings()
        req = _mock_request(auth=None)
        assert get_auth(req) is None

    def test_returns_auth_when_set(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "key:admin")
        reload_settings()
        ctx = AuthContext(identity="key-abc", role="admin")
        req = _mock_request(auth=ctx)
        result = get_auth(req)
        assert result is ctx

    def test_raises_401_when_auth_required_but_missing(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "key:admin")
        reload_settings()
        req = _mock_request(auth=None)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            get_auth(req)
        assert exc_info.value.status_code == 401
        assert "API key" in str(exc_info.value.detail)


class TestRequireRole:
    def test_returns_admin_when_auth_not_required(self, monkeypatch):
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        reload_settings()
        dep = require_role("admin")
        req = _mock_request(auth=None)
        check_fn = dep.dependency
        result = check_fn(req)
        assert result.role == "admin"
        assert result.identity == "anonymous"

    def test_returns_auth_when_role_matches(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "key:adjuster")
        reload_settings()
        ctx = AuthContext(identity="key-abc", role="adjuster")
        req = _mock_request(auth=ctx)
        dep = require_role("adjuster", "supervisor")
        check_fn = dep.dependency
        result = check_fn(req)
        assert result is ctx

    def test_raises_403_when_role_insufficient(self, monkeypatch):
        monkeypatch.setenv("API_KEYS", "key:adjuster")
        reload_settings()
        ctx = AuthContext(identity="key-abc", role="adjuster")
        req = _mock_request(auth=ctx)
        dep = require_role("admin", "supervisor")
        check_fn = dep.dependency
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check_fn(req)
        assert exc_info.value.status_code == 403
        assert "Insufficient" in str(exc_info.value.detail)
