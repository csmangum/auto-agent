"""Storage adapters for claim attachments (local filesystem or S3-compatible)."""

from claim_agent.storage.base import StorageAdapter
from claim_agent.storage.factory import get_storage_adapter

__all__ = ["StorageAdapter", "get_storage_adapter"]
