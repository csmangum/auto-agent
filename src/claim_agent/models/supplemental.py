"""Pydantic models for supplemental claim handling."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SupplementalInput(BaseModel):
    """Input payload for a supplemental damage report."""

    claim_id: str = Field(..., description="ID of the existing partial loss claim")
    supplemental_damage_description: str = Field(
        ...,
        max_length=2000,
        description="Description of the additional damage discovered during repair",
    )
    reported_by: Optional[Literal["shop", "adjuster", "policyholder"]] = Field(
        default=None,
        description="Who reported the supplemental damage",
    )
