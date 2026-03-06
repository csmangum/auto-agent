"""Attachment utility functions."""

from claim_agent.models.claim import AttachmentType


def infer_attachment_type(filename: str) -> AttachmentType:
    """Infer attachment type from filename extension."""
    ext = (filename.rsplit(".", 1)[-1] or "").lower()
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
        return AttachmentType.PHOTO
    if ext in ("doc", "docx", "xls", "xlsx") or "estimate" in filename.lower():
        return AttachmentType.ESTIMATE
    if ext == "pdf":
        return AttachmentType.PDF
    return AttachmentType.OTHER
