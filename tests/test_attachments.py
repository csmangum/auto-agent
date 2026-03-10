"""Tests for attachment utility functions."""


from claim_agent.models.claim import AttachmentType
from claim_agent.utils.attachments import infer_attachment_type


class TestInferAttachmentType:
    """Tests for infer_attachment_type."""

    def test_photo_extensions(self):
        """Photo extensions return PHOTO."""
        for ext in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
            assert infer_attachment_type(f"damage.{ext}") == AttachmentType.PHOTO
            assert infer_attachment_type(f"file.{ext.upper()}") == AttachmentType.PHOTO

    def test_estimate_extensions(self):
        """Doc/xls extensions return ESTIMATE."""
        for ext in ("doc", "docx", "xls", "xlsx"):
            assert infer_attachment_type(f"document.{ext}") == AttachmentType.ESTIMATE

    def test_estimate_in_filename(self):
        """Filename containing 'estimate' returns ESTIMATE."""
        assert infer_attachment_type("repair_estimate.pdf") == AttachmentType.ESTIMATE
        assert infer_attachment_type("ESTIMATE_2024.xlsx") == AttachmentType.ESTIMATE
        assert infer_attachment_type("my-estimate.docx") == AttachmentType.ESTIMATE

    def test_pdf(self):
        """PDF extension returns PDF."""
        assert infer_attachment_type("report.pdf") == AttachmentType.PDF
        assert infer_attachment_type("doc.PDF") == AttachmentType.PDF

    def test_unknown_extension_returns_other(self):
        """Unknown extensions return OTHER."""
        assert infer_attachment_type("file.txt") == AttachmentType.OTHER
        assert infer_attachment_type("data.json") == AttachmentType.OTHER
        assert infer_attachment_type("archive.zip") == AttachmentType.OTHER

    def test_no_extension_returns_other(self):
        """Filename with no extension returns OTHER."""
        assert infer_attachment_type("noextension") == AttachmentType.OTHER

    def test_empty_filename_returns_other(self):
        """Empty filename returns OTHER."""
        assert infer_attachment_type("") == AttachmentType.OTHER

    def test_dot_only_returns_other(self):
        """Filename that is just a dot returns OTHER."""
        assert infer_attachment_type(".") == AttachmentType.OTHER

    def test_double_extension_uses_last(self):
        """Uses last extension when multiple dots present."""
        assert infer_attachment_type("photo.jpg.pdf") == AttachmentType.PDF
        assert infer_attachment_type("file.tar.gz") == AttachmentType.OTHER
