"""Local filesystem storage for claim attachments."""

import uuid
from pathlib import Path
from typing import BinaryIO

from claim_agent.storage.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """Store attachments on local filesystem."""

    def __init__(self, base_path: str | Path = "data/attachments"):
        self._base = Path(base_path)

    def save(
        self,
        claim_id: str,
        filename: str,
        content: BinaryIO | bytes,
        content_type: str | None = None,
    ) -> str:
        """Save file under data/attachments/{claim_id}/{unique}_{filename}."""
        safe_claim = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
        dir_path = self._base / safe_claim
        dir_path.mkdir(parents=True, exist_ok=True)

        # Sanitize filename and ensure uniqueness
        safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)
        if not safe_name:
            safe_name = "file"
        unique = uuid.uuid4().hex[:8]
        stored_name = f"{unique}_{safe_name}"
        file_path = dir_path / stored_name

        data = content.read() if hasattr(content, "read") else content
        file_path.write_bytes(data)

        return stored_name

    def get_url(self, claim_id: str, stored_path_or_key: str) -> str:
        """Return an opaque storage key for local storage.

        Returns a relative key (safe_claim_id/stored_name) instead of an
        absolute file:// URL to avoid leaking server filesystem layout.
        Callers can map this key to a download endpoint or resolve it to a
        local path using the configured ATTACHMENT_STORAGE_PATH.
        """
        safe_claim = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
        return f"{safe_claim}/{stored_path_or_key}"

    def exists(self, claim_id: str, stored_path_or_key: str) -> bool:
        """Check if file exists."""
        safe_claim = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
        return (self._base / safe_claim / stored_path_or_key).exists()

    def get_path(self, claim_id: str, stored_key: str) -> Path:
        """Return filesystem path for a stored file. Key is stored_name (from save) or last segment of get_url result."""
        # Handle "safe_claim/stored_name" format from get_url
        stored_name = stored_key.split("/")[-1] if "/" in stored_key else stored_key
        safe_claim = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
        return self._base / safe_claim / stored_name
