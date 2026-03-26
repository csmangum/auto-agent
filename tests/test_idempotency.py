"""Tests for idempotency key support."""

import json
from unittest.mock import MagicMock

from claim_agent.api.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    _MAX_KEY_LENGTH,
    _build_scoped_idempotency_key,
    check_idempotency,
    cleanup_expired,
    get_idempotency_key_and_cached,
    store_idempotency,
    store_response_if_idempotent,
)


def _fake_request(
    idempotency_key: str | None = None,
    method: str = "POST",
    path: str = "/api/v1/claims",
):
    """Build a minimal mock request with method and path for scoped idempotency keys."""
    request = MagicMock()
    request.method = method
    request.url = MagicMock()
    request.url.path = path
    request.client = MagicMock(host="127.0.0.1")
    request.headers.get = lambda key, default=None: (
        idempotency_key if key == IDEMPOTENCY_KEY_HEADER else default
    )
    return request


class TestIdempotencyStorage:
    def test_check_returns_none_when_empty(self, tmp_path):
        assert check_idempotency("", db_path=str(tmp_path / "test.db")) is None
        assert check_idempotency("  ", db_path=str(tmp_path / "test.db")) is None

    def test_store_and_check_roundtrip(self, tmp_path):
        db = str(tmp_path / "idem.db")
        key = "test-key-123"
        body = {"claim_id": "CLM-001"}
        store_idempotency(key, 200, body, ttl_seconds=3600, db_path=db)
        cached = check_idempotency(key, db_path=db)
        assert cached is not None
        status, stored_body = cached
        assert status == 200
        assert stored_body == body

    def test_check_returns_none_for_unknown_key(self, tmp_path):
        db = str(tmp_path / "idem.db")
        store_idempotency("known", 200, {"x": 1}, ttl_seconds=3600, db_path=db)
        assert check_idempotency("unknown", db_path=db) is None

    def test_store_response_if_idempotent_noop_when_no_key(self, tmp_path):
        store_response_if_idempotent(None, 200, {"a": 1}, db_path=str(tmp_path / "x.db"))
        # No exception, no storage

    def test_store_response_if_idempotent_only_caches_200_releases_on_non_200(self, tmp_path):
        """Non-200 responses release the claim so client can retry; only 200 is cached."""
        from claim_agent.api.idempotency import _try_claim_key

        db = str(tmp_path / "idem.db")
        key = "release-on-error"
        result, _, _ = _try_claim_key(key, db_path=db)
        assert result == "owned"
        store_response_if_idempotent(key, 500, {"error": "server error"}, db_path=db)
        # Key should be released; second request can claim
        result2, _, _ = _try_claim_key(key, db_path=db)
        assert result2 == "owned"

        # 200 is cached
        _try_claim_key(key, db_path=db)
        store_response_if_idempotent(key, 200, {"claim_id": "CLM-1"}, db_path=db)
        cached = check_idempotency(key, db_path=db)
        assert cached == (200, {"claim_id": "CLM-1"})

    def test_get_idempotency_key_and_cached_returns_none_when_no_header(self):
        req = _fake_request(idempotency_key=None)
        key, cached = get_idempotency_key_and_cached(req)
        assert key is None
        assert cached is None

    def test_get_idempotency_key_and_cached_returns_cached_when_hit(self, tmp_path):
        db = str(tmp_path / "idem.db")
        req = _fake_request(idempotency_key="my-key")
        scoped_key = _build_scoped_idempotency_key(req, "my-key")
        store_idempotency(scoped_key, 200, {"claim_id": "CLM-X"}, ttl_seconds=3600, db_path=db)
        key, cached = get_idempotency_key_and_cached(req, db_path=db)
        assert key == scoped_key
        assert cached is not None
        assert cached.status_code == 200
        content = json.loads(cached.body.decode())
        assert content == {"claim_id": "CLM-X"}


class TestIdempotencyKeyValidation:
    """Test rejection of invalid idempotency keys."""

    def test_invalid_key_returns_400(self):
        req = _fake_request(idempotency_key="invalid key!")
        key, cached = get_idempotency_key_and_cached(req)
        assert key is None
        assert cached is not None
        assert cached.status_code == 400

    def test_oversized_key_returns_400(self):
        req = _fake_request(idempotency_key="x" * (_MAX_KEY_LENGTH + 1))
        key, cached = get_idempotency_key_and_cached(req)
        assert key is None
        assert cached is not None
        assert cached.status_code == 400

    def test_valid_key_accepted(self):
        req = _fake_request(idempotency_key="valid-key_123")
        key, cached = get_idempotency_key_and_cached(req)
        assert key == _build_scoped_idempotency_key(req, "valid-key_123")
        assert cached is None


class TestIdempotencyExpiredKey:
    """Test expired key behavior."""

    def test_expired_key_returns_none(self, tmp_path):
        db = str(tmp_path / "idem.db")
        store_idempotency("expired-key", 200, {"x": 1}, ttl_seconds=-3600, db_path=db)
        assert check_idempotency("expired-key", db_path=db) is None

    def test_cleanup_expired_removes_keys(self, tmp_path):
        db = str(tmp_path / "idem.db")
        store_idempotency("expired-key", 200, {"x": 1}, ttl_seconds=-3600, db_path=db)
        deleted = cleanup_expired(db_path=db)
        assert deleted >= 1
        assert check_idempotency("expired-key", db_path=db) is None


class TestIdempotencyConcurrent:
    """Test claim-before-process prevents duplicate processing."""

    def test_second_request_gets_in_progress(self, tmp_path):
        """First _try_claim_key gets owned; second gets in_progress."""
        from claim_agent.api.idempotency import _try_claim_key

        db = str(tmp_path / "idem.db")
        key = "concurrent-key"
        result1, _, _ = _try_claim_key(key, db_path=db)
        result2, _, _ = _try_claim_key(key, db_path=db)
        assert result1 == "owned"
        assert result2 == "in_progress"
