"""Unit tests for storage adapters."""

import tempfile
from io import BytesIO

import pytest

from claim_agent.storage.local import LocalStorageAdapter


class TestLocalStorageAdapter:
    """Tests for LocalStorageAdapter."""

    @pytest.fixture
    def storage(self):
        """Local storage adapter with temp directory."""
        with tempfile.TemporaryDirectory() as tmp:
            yield LocalStorageAdapter(base_path=tmp)

    def test_save_and_exists_bytes(self, storage):
        """Save with bytes content and verify exists."""
        key = storage.save("CLM-001", "photo.jpg", b"image data")
        assert key.endswith("photo.jpg")
        assert storage.exists("CLM-001", key)

    def test_save_and_exists_file_like(self, storage):
        """Save with file-like content and verify exists."""
        content = BytesIO(b"pdf content")
        key = storage.save("CLM-002", "report.pdf", content)
        assert storage.exists("CLM-002", key)
        path = storage.get_path("CLM-002", key)
        assert path.read_bytes() == b"pdf content"

    def test_get_path_returns_correct_path(self, storage):
        """get_path returns filesystem path for stored file."""
        key = storage.save("CLM-003", "doc.pdf", b"data")
        path = storage.get_path("CLM-003", key)
        assert path.exists()
        assert path.read_bytes() == b"data"

    def test_get_path_handles_url_format_key(self, storage):
        """get_path handles key in safe_claim/stored_name format."""
        key = storage.save("CLM-004", "file.txt", b"x")
        url_key = storage.get_url("CLM-004", key)
        assert "/" in url_key
        path = storage.get_path("CLM-004", url_key)
        assert path.exists()
        assert path.read_bytes() == b"x"

    def test_exists_false_for_nonexistent(self, storage):
        """exists returns False for nonexistent file."""
        assert storage.exists("CLM-005", "nonexistent_key") is False

    def test_get_url_format(self, storage):
        """get_url returns safe_claim/stored_name format."""
        key = storage.save("CLM-006", "a.jpg", b"x")
        url = storage.get_url("CLM-006", key)
        assert url == f"CLM-006/{key}"

    def test_claim_id_sanitization(self, storage):
        """Special chars in claim_id are sanitized to underscore."""
        key = storage.save("CLM/../evil", "f.jpg", b"x")
        assert storage.exists("CLM/../evil", key)
        path = storage.get_path("CLM/../evil", key)
        assert ".." not in str(path)
        assert path.exists()

    def test_filename_sanitization(self, storage):
        """Special chars in filename are sanitized (slashes become underscore)."""
        key = storage.save("CLM-007", "path/to/file.jpg", b"x")
        assert "/" not in key
        assert "file" in key
        path = storage.get_path("CLM-007", key)
        assert path.exists()

    def test_empty_filename_becomes_file(self, storage):
        """Empty filename results in 'file' as stored name."""
        key = storage.save("CLM-008", "", b"x")
        assert "file" in key
        assert storage.exists("CLM-008", key)

    def test_get_path_rejects_parent_segment(self, storage):
        """Reject .. and other traversal keys before touching the filesystem."""
        with pytest.raises(ValueError, match="Invalid attachment key"):
            storage.get_path("CLM-009", "..")

    def test_exists_false_for_invalid_key(self, storage):
        assert storage.exists("CLM-010", "..") is False
