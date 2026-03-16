"""Pydantic models for claim payments and disbursement workflow."""

from enum import Enum
from typing import List, Optional

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
    check_number: Optional[str] = Field(default=None, max_length=100)
    payee_secondary: Optional[str] = Field(default=None, max_length=500)
    payee_secondary_type: Optional[PayeeType] = Field(default=None)


class ClaimPayment(BaseModel):
    """Full payment record (read model)."""

    id: int
    claim_id: str
    amount: float
    payee: str
    payee_type: PayeeType
    payment_method: PaymentMethod
    check_number: Optional[str] = None
    status: PaymentStatus
    authorized_by: str
    issued_at: Optional[str] = None
    cleared_at: Optional[str] = None
    voided_at: Optional[str] = None
    void_reason: Optional[str] = None
    payee_secondary: Optional[str] = None
    payee_secondary_type: Optional[PayeeType] = None
    created_at: str
    updated_at: str


class ClaimPaymentList(BaseModel):
    """Paginated list of payments."""

    payments: List[ClaimPayment]
    total: int
    limit: int
    offset: int
