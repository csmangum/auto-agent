"""Tests for idempotency key support."""

import json
from unittest.mock import MagicMock


from claim_agent.api.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    check_idempotency,
    get_idempotency_key_and_cached,
    store_idempotency,
    store_response_if_idempotent,
)


def _fake_request(idempotency_key: str | None = None):
    """Build a minimal mock request."""
    request = MagicMock()
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

    def test_get_idempotency_key_and_cached_returns_none_when_no_header(self):
        req = _fake_request(idempotency_key=None)
        key, cached = get_idempotency_key_and_cached(req)
        assert key is None
        assert cached is None

    def test_get_idempotency_key_and_cached_returns_cached_when_hit(self, tmp_path):
        db = str(tmp_path / "idem.db")
        store_idempotency("my-key", 200, {"claim_id": "CLM-X"}, ttl_seconds=3600, db_path=db)
        req = _fake_request(idempotency_key="my-key")
        key, cached = get_idempotency_key_and_cached(req, db_path=db)
        assert key == "my-key"
        assert cached is not None
        assert cached.status_code == 200
        content = json.loads(cached.body.decode())
        assert content == {"claim_id": "CLM-X"}
