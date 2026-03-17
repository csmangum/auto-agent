"""Attachment utility functions."""

from claim_agent.models.claim import AttachmentType
from claim_agent.models.document import DocumentType


def attachment_type_to_document_type(atype: AttachmentType) -> DocumentType:
    """Map AttachmentType to DocumentType."""
    mapping = {
        AttachmentType.PHOTO: DocumentType.PHOTO,
        AttachmentType.PDF: DocumentType.PDF,
        AttachmentType.ESTIMATE: DocumentType.ESTIMATE,
        AttachmentType.OTHER: DocumentType.OTHER,
    }
    return mapping.get(atype, DocumentType.OTHER)


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
