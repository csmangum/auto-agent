"""Abstract storage adapter for claim attachments."""

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageAdapter(ABC):
    """Interface for storing and retrieving attachment files."""

    @abstractmethod
    def save(
        self,
        claim_id: str,
        filename: str,
        content: BinaryIO | bytes,
        content_type: str | None = None,
    ) -> str:
        """Save file and return URL/path for retrieval.

        Args:
            claim_id: Claim ID (used for organization).
            filename: Original filename.
            content: File content (file-like or bytes).
            content_type: Optional MIME type.

        Returns:
            A storage key or path used as input to `get_url()`.
        """
        ...

    @abstractmethod
    def get_url(self, claim_id: str, stored_path_or_key: str) -> str:
        """Return URL to access the stored file.

        Args:
            claim_id: Claim ID.
            stored_path_or_key: Path or key returned by save().

        Returns:
            URL string (file:// for local, https:// for S3).
        """
        ...

    @abstractmethod
    def exists(self, claim_id: str, stored_path_or_key: str) -> bool:
        """Check if file exists."""
        ...
