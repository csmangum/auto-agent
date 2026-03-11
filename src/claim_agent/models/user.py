"""User types and context for human-in-the-loop flows.

Defines formal user types (claimant, policyholder, adjuster, repair_shop, siu, other)
and a minimal UserContext model for structured interactions with external parties.
Used by the follow-up agent to know who to contact and how to tailor outreach.
"""

from enum import Enum

from pydantic import BaseModel, Field


class UserType(str, Enum):
    """Formal user types for structured human-in-the-loop interactions.

    | User Type     | Description                          | Example Use                                      |
    |---------------|--------------------------------------|--------------------------------------------------|
    | claimant      | Person who filed the claim           | Request photos, clarify damage, confirm details  |
    | policyholder  | Named insured on policy              | Verify coverage, confirm vehicle usage          |
    | adjuster      | Human reviewer                       | Escalation handback, approval/rejection          |
    | repair_shop   | Body shop / repair facility          | Confirm estimate, schedule repair, supplement    |
    | siu           | Special Investigations Unit           | Fraud referral, investigation updates            |
    | other         | Generic external party               | Attorneys, medical providers, etc.                |
    """

    CLAIMANT = "claimant"
    POLICYHOLDER = "policyholder"
    ADJUSTER = "adjuster"
    REPAIR_SHOP = "repair_shop"
    SIU = "siu"
    OTHER = "other"


class UserContext(BaseModel):
    """Minimal user model for follow-up and audit context.

    Combines user_type with an identifier (e.g., claim-specific contact ID,
    email, or adjuster ID). Contact channels (email, SMS, API, portal) may
    vary by user type and are handled by notification adapters.
    """

    user_type: UserType = Field(..., description="Formal user type")
    identifier: str = Field(..., description="User or contact identifier (email, ID, etc.)")
    email: str | None = Field(None, description="Email for outreach (when applicable)")
    phone: str | None = Field(None, description="Phone for SMS (when applicable)")

    def to_actor_id(self) -> str:
        """Return a string suitable for actor_id in audit logs."""
        return f"{self.user_type.value}:{self.identifier}"
