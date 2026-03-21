"""Typed policy lookup result from ``query_policy_db_impl``."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class PolicyLookupFailure(BaseModel):
    """Inactive policy or policy not found."""

    model_config = ConfigDict(extra="ignore")

    valid: Literal[False]
    message: str
    status: str | None = None
    error: str | None = None


class PolicyLookupSuccess(BaseModel):
    """Active policy with coverage summary for tools and verification."""

    model_config = ConfigDict(extra="ignore")

    valid: Literal[True]
    coverage: str
    deductible: float
    status: str
    physical_damage_covered: bool
    physical_damage_coverages: list[str]
    collision_deductible: float | None = None
    comprehensive_deductible: float | None = None
    gap_insurance: bool | None = None
    rental_reimbursement: dict[str, Any] | None = None
    territory: Any = None
    excluded_territories: Any = None
    named_insured: list[dict[str, Any]] | None = None
    drivers: list[dict[str, Any]] | None = None
    effective_date: str | None = None
    expiration_date: str | None = None


PolicyLookupResult = PolicyLookupSuccess | PolicyLookupFailure

_policy_lookup_adapter: TypeAdapter[PolicyLookupResult] = TypeAdapter(
    Annotated[
        Union[PolicyLookupSuccess, PolicyLookupFailure],
        Field(discriminator="valid"),
    ]
)


def policy_lookup_from_dict(data: dict[str, Any]) -> PolicyLookupResult:
    """Validate a policy lookup payload built by policy logic."""
    return _policy_lookup_adapter.validate_python(data)
