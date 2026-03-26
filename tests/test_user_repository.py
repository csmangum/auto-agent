"""Tests for UserRepository and refresh token lifecycle."""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings
from claim_agent.db.user_repository import (
    UserRepository,
    hash_refresh_token,
    verify_password,
)
from claim_agent.api.server import app


@pytest.fixture
def user_db(temp_db):
    """temp_db with users + refresh_tokens tables (from SCHEMA_SQL)."""
    reload_settings()
    yield temp_db


def test_create_and_verify_password(user_db):
    repo = UserRepository()
    u = repo.create_user("alice@example.com", "password123", "adjuster")
    assert u["email"] == "alice@example.com"
    assert u["role"] == "adjuster"
    assert "password_hash" not in u
    row = repo.get_user_with_password_by_email("alice@example.com")
    assert row is not None
    assert verify_password("password123", row["password_hash"])


def test_duplicate_email_raises(user_db):
    repo = UserRepository()
    repo.create_user("dup@example.com", "password123", "adjuster")
    with pytest.raises(ValueError, match="already"):
        repo.create_user("dup@example.com", "password123", "adjuster")


def test_refresh_token_rotate(user_db):
    repo = UserRepository()
    u = repo.create_user("bob@example.com", "password123", "adjuster")
    uid = u["id"]
    raw, tid = repo.issue_refresh_token(uid, ttl_seconds=3600)
    assert len(raw) > 20
    row = repo.get_refresh_token_row_by_hash(hash_refresh_token(raw))
    assert row is not None
    assert row["id"] == tid
    raw2, tid2 = repo.rotate_refresh_token(tid, uid, ttl_seconds=3600)
    old = repo.get_refresh_token_row_by_hash(hash_refresh_token(raw))
    assert old is not None
    assert old.get("revoked_at")
    new_row = repo.get_refresh_token_row_by_hash(hash_refresh_token(raw2))
    assert new_row is not None
    assert new_row["id"] == tid2


def test_auth_login_and_refresh_http(user_db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    repo = UserRepository()
    repo.create_user("http@example.com", "password123", "adjuster")
    client = TestClient(app)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "http@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data and "refresh_token" in data
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r2.status_code == 200
    assert "access_token" in r2.json()
