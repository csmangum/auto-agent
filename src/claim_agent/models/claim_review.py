"""Pydantic models for claim review (supervisor/compliance audit)."""

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    """A single issue identified during claim process review."""

    category: str = Field(
        ...,
        description="Issue category: compliance, procedural, documentation, quality, or fraud",
    )
    severity: str = Field(
        ...,
        description="Severity level: low, medium, high, or critical",
    )
    description: str = Field(..., description="Description of the issue")
    compliance_ref: str | None = Field(
        default=None,
        description="Regulatory reference if applicable (e.g. FCSP-003)",
    )
    recommendation: str | None = Field(
        default=None,
        description="Recommended remediation",
    )


class ComplianceCheck(BaseModel):
    """Result of a single compliance provision check."""

    provision_id: str = Field(..., description="Provision identifier (e.g. FCSP-001)")
    passed: bool = Field(..., description="Whether the check passed")
    notes: str | None = Field(default=None, description="Additional notes")


class ClaimReviewReport(BaseModel):
    """Structured output from the Claim Review Crew."""

    claim_id: str = Field(..., description="Claim ID reviewed")
    overall_pass: bool = Field(
        ...,
        description="Whether the claim process passed review overall",
    )
    issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="Issues identified during review",
    )
    compliance_checks: list[ComplianceCheck] = Field(
        default_factory=list,
        description="Results of compliance provision checks",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Overall recommendations",
    )
