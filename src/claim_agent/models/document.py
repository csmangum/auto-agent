"""Pydantic models for claim documents and document requests."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Classified document type."""

    POLICE_REPORT = "police_report"
    ESTIMATE = "estimate"
    MEDICAL_RECORD = "medical_record"
    PHOTO = "photo"
    PDF = "pdf"
    OTHER = "other"


class ReviewStatus(str, Enum):
    """Document review lifecycle."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class DocumentRequestStatus(str, Enum):
    """Document request lifecycle."""

    REQUESTED = "requested"
    RECEIVED = "received"
    PARTIAL = "partial"
    OVERDUE = "overdue"


class ClaimDocument(BaseModel):
    """Structured document metadata for a claim."""

    id: Optional[int] = None
    claim_id: str = Field(..., description="Claim ID")
    storage_key: str = Field(..., description="Key in StorageAdapter")
    document_type: Optional[DocumentType] = Field(
        default=None, description="Classified type (null if unclassified)"
    )
    received_date: Optional[str] = Field(default=None, description="ISO date when received")
    received_from: Optional[str] = Field(
        default=None, description="Source (claimant, repair_shop, police, provider, etc.)"
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.PENDING, description="Review lifecycle status"
    )
    privileged: bool = Field(
        default=False, description="Attorney-client privilege, work product"
    )
    retention_date: Optional[str] = Field(
        default=None, description="ISO date for retention policy"
    )
    retention_enforced_at: Optional[str] = Field(
        default=None,
        description="When document-level retention was applied (soft archive); set by document-retention-enforce",
    )
    version: int = Field(default=1, description="Document version")
    extracted_data: Optional[dict[str, Any]] = Field(
        default=None, description="OCR/extracted structured data"
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ClaimDocumentCreate(BaseModel):
    """Input for creating a document record."""

    claim_id: str
    storage_key: str
    document_type: Optional[DocumentType] = None
    received_date: Optional[str] = None
    received_from: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    privileged: bool = False
    retention_date: Optional[str] = None
    version: int = 1


class ClaimDocumentUpdate(BaseModel):
    """Input for updating document metadata."""

    document_type: Optional[DocumentType] = None
    review_status: Optional[ReviewStatus] = None
    privileged: Optional[bool] = None
    retention_date: Optional[str] = None


class DocumentRequest(BaseModel):
    """Document request (requested -> received tracking)."""

    id: Optional[int] = None
    claim_id: str = Field(..., description="Claim ID")
    document_type: str = Field(..., description="Type requested")
    requested_at: Optional[str] = Field(default=None, description="When request was sent")
    requested_from: Optional[str] = Field(default=None, description="Party requested from")
    status: DocumentRequestStatus = Field(
        default=DocumentRequestStatus.REQUESTED, description="Request status"
    )
    received_at: Optional[str] = Field(default=None, description="When document(s) received")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DocumentRequestCreate(BaseModel):
    """Input for creating a document request."""

    claim_id: str
    document_type: str
    requested_from: Optional[str] = None


class DocumentRequestUpdate(BaseModel):
    """Input for updating a document request."""

    status: Optional[DocumentRequestStatus] = None
    received_at: Optional[str] = None
