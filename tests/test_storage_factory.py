"""Unit tests for storage/factory."""

import pytest

from claim_agent.storage.factory import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter


def _reset_storage_factory():
    import claim_agent.storage.factory as mod
    mod._storage_instance = None


class TestGetStorageAdapter:
    def test_returns_local_by_default(self, monkeypatch):
        monkeypatch.delenv("ATTACHMENT_STORAGE_BACKEND", raising=False)
        _reset_storage_factory()
        adapter = get_storage_adapter()
        assert isinstance(adapter, LocalStorageAdapter)

    def test_returns_local_when_explicit(self, monkeypatch):
        monkeypatch.setenv("ATTACHMENT_STORAGE_BACKEND", "local")
        _reset_storage_factory()
        adapter = get_storage_adapter()
        assert isinstance(adapter, LocalStorageAdapter)

    def test_s3_requires_bucket(self, monkeypatch):
        monkeypatch.setenv("ATTACHMENT_STORAGE_BACKEND", "s3")
        monkeypatch.delenv("ATTACHMENT_S3_BUCKET", raising=False)
        _reset_storage_factory()
        with pytest.raises(RuntimeError) as exc_info:
            get_storage_adapter()
        assert "ATTACHMENT_S3_BUCKET" in str(exc_info.value)
