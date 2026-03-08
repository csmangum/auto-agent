"""Factory for storage adapters based on configuration."""

import os
import threading

from claim_agent.config import get_settings
from claim_agent.storage.base import StorageAdapter
from claim_agent.storage.local import LocalStorageAdapter

_storage_instance: StorageAdapter | None = None
_storage_lock = threading.Lock()


def get_storage_adapter() -> StorageAdapter:
    """Return configured storage adapter (local or S3)."""
    global _storage_instance
    # Fast path without locking if the instance is already initialized.
    if _storage_instance is not None:
        return _storage_instance

    # Ensure thread-safe lazy initialization.
    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance

        backend = os.environ.get("ATTACHMENT_STORAGE_BACKEND", "local").strip().lower()

        if backend == "s3":
            try:
                from claim_agent.storage.s3 import S3StorageAdapter

                bucket = os.environ.get("ATTACHMENT_S3_BUCKET", "")
                if not bucket:
                    raise RuntimeError(
                        "ATTACHMENT_S3_BUCKET environment variable must be set when using S3 storage."
                    )
                prefix = os.environ.get("ATTACHMENT_S3_PREFIX", "attachments")
                endpoint = os.environ.get("ATTACHMENT_S3_ENDPOINT")
                _storage_instance = S3StorageAdapter(
                    bucket=bucket,
                    prefix=prefix,
                    endpoint_url=endpoint or None,
                )
            except ImportError as e:
                raise RuntimeError(
                    "S3 storage requires the optional S3 dependencies. Install with: pip install 'claim-agent[s3]'"
                ) from e
        else:
            base_path = get_settings().paths.attachment_storage_path
            _storage_instance = LocalStorageAdapter(base_path=base_path)

        return _storage_instance
