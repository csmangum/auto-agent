"""Pydantic models for claim parties (claimant, policyholder, attorney, etc.)."""

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PartyType(str, Enum):
    """Party types for claim identity management."""

    CLAIMANT = "claimant"
    POLICYHOLDER = "policyholder"
    WITNESS = "witness"
    ATTORNEY = "attorney"
    PROVIDER = "provider"
    LIENHOLDER = "lienholder"


class ConsentStatus(str, Enum):
    """Consent status for party communication."""

    PENDING = "pending"
    GRANTED = "granted"
    REVOKED = "revoked"


class AuthorizationStatus(str, Enum):
    """Authorization status for party actions."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"


class ClaimPartyInput(BaseModel):
    """Input for creating or updating a claim party."""

    party_type: Literal[
        "claimant", "policyholder", "witness", "attorney", "provider", "lienholder"
    ] = Field(..., description="Party type")
    name: Optional[str] = Field(default=None, description="Party name")
    email: Optional[str] = Field(default=None, description="Email for contact")
    phone: Optional[str] = Field(default=None, description="Phone for contact")
    address: Optional[str] = Field(default=None, description="Address (JSON or plain text)")
    role: Optional[str] = Field(
        default=None, description="Role within claim (e.g., driver, passenger)"
    )
    represented_by_id: Optional[int] = Field(
        default=None,
        description="ID of attorney party representing this party. Only valid when updating; "
        "at claim creation this is ignored (attorney IDs do not exist yet).",
    )
    consent_status: Optional[Literal["pending", "granted", "revoked"]] = Field(
        default="pending", description="Consent status"
    )
    authorization_status: Optional[Literal["pending", "authorized", "denied"]] = Field(
        default="pending", description="Authorization status"
    )


class ClaimParty(BaseModel):
    """Full claim party record from database."""

    id: int = Field(..., description="Party record ID")
    claim_id: str = Field(..., description="Claim ID")
    party_type: str = Field(..., description="Party type")
    name: Optional[str] = Field(default=None, description="Party name")
    email: Optional[str] = Field(default=None, description="Email")
    phone: Optional[str] = Field(default=None, description="Phone")
    address: Optional[str] = Field(default=None, description="Address")
    role: Optional[str] = Field(default=None, description="Role")
    represented_by_id: Optional[int] = Field(
        default=None, description="Attorney party ID representing this party"
    )
    consent_status: str = Field(default="pending", description="Consent status")
    authorization_status: str = Field(default="pending", description="Authorization status")
    created_at: Optional[str] = Field(default=None, description="Created timestamp")
    updated_at: Optional[str] = Field(default=None, description="Updated timestamp")

    @classmethod
    def from_row(cls, row: Any) -> "ClaimParty":
        """Build ClaimParty from sqlite3.Row or dict."""
        d = dict(row) if hasattr(row, "keys") else row
        return cls(
            id=d["id"],
            claim_id=d["claim_id"],
            party_type=d["party_type"],
            name=d.get("name"),
            email=d.get("email"),
            phone=d.get("phone"),
            address=d.get("address"),
            role=d.get("role"),
            represented_by_id=d.get("represented_by_id"),
            consent_status=d.get("consent_status", "pending"),
            authorization_status=d.get("authorization_status", "pending"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
