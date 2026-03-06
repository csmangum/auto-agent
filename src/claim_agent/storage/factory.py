"""Factory for storage adapters based on configuration."""

import os

from claim_agent.storage.base import StorageAdapter
from claim_agent.storage.local import LocalStorageAdapter

_storage_instance: StorageAdapter | None = None


def get_storage_adapter() -> StorageAdapter:
    """Return configured storage adapter (local or S3)."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    backend = os.environ.get("ATTACHMENT_STORAGE_BACKEND", "local").strip().lower()

    if backend == "s3":
        try:
            from claim_agent.storage.s3 import S3StorageAdapter

            bucket = os.environ.get("ATTACHMENT_S3_BUCKET", "")
            prefix = os.environ.get("ATTACHMENT_S3_PREFIX", "attachments")
            endpoint = os.environ.get("ATTACHMENT_S3_ENDPOINT")
            _storage_instance = S3StorageAdapter(
                bucket=bucket,
                prefix=prefix,
                endpoint_url=endpoint or None,
            )
        except ImportError as e:
            raise RuntimeError(
                "S3 storage requires boto3. Install with: pip install boto3"
            ) from e
    else:
        base_path = os.environ.get("ATTACHMENT_STORAGE_PATH", "data/attachments")
        _storage_instance = LocalStorageAdapter(base_path=base_path)

    return _storage_instance
