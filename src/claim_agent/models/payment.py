"""Pydantic models for claim payments and disbursement workflow."""

from enum import Enum

from pydantic import BaseModel, Field


class PayeeType(str, Enum):
    """Type of payment recipient."""

    CLAIMANT = "claimant"
    REPAIR_SHOP = "repair_shop"
    RENTAL_COMPANY = "rental_company"
    MEDICAL_PROVIDER = "medical_provider"
    LIENHOLDER = "lienholder"
    ATTORNEY = "attorney"
    OTHER = "other"


class PaymentMethod(str, Enum):
    """Method of payment disbursement."""

    CHECK = "check"
    ACH = "ach"
    WIRE = "wire"
    CARD = "card"
    OTHER = "other"


class PaymentStatus(str, Enum):
    """Payment lifecycle status."""

    AUTHORIZED = "authorized"
    ISSUED = "issued"
    CLEARED = "cleared"
    VOIDED = "voided"


class ClaimPaymentCreate(BaseModel):
    """Input for creating a new payment."""

    claim_id: str = Field(..., description="Claim ID")
    amount: float = Field(..., gt=0, description="Payment amount in dollars")
    payee: str = Field(..., min_length=1, max_length=500, description="Primary payee name")
    payee_type: PayeeType = Field(..., description="Type of payee")
    payment_method: PaymentMethod = Field(..., description="Disbursement method")
    check_number: str | None = Field(default=None, max_length=100)
    payee_secondary: str | None = Field(default=None, max_length=500)
    payee_secondary_type: PayeeType | None = Field(default=None)


class IssuePaymentBody(BaseModel):
    """Request body for issuing a payment."""

    check_number: str | None = Field(default=None, max_length=100)


class VoidPaymentBody(BaseModel):
    """Request body for voiding a payment."""

    reason: str | None = Field(default=None, max_length=500)


class ClaimPayment(BaseModel):
    """Full payment record (read model)."""

    id: int
    claim_id: str
    amount: float
    payee: str
    payee_type: PayeeType
    payment_method: PaymentMethod
    check_number: str | None = None
    status: PaymentStatus
    authorized_by: str
    issued_at: str | None = None
    cleared_at: str | None = None
    voided_at: str | None = None
    void_reason: str | None = None
    payee_secondary: str | None = None
    payee_secondary_type: PayeeType | None = None
    created_at: str
    updated_at: str


class ClaimPaymentList(BaseModel):
    """Paginated list of payments."""

    payments: list[ClaimPayment]
    total: int
    limit: int
    offset: int
