"""FNOL coverage verification: gate before routing.

Deterministic verification (no LLM) using policy adapter. Denies or escalates
claims that lack coverage before the router runs.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from claim_agent.config.settings import get_coverage_config
from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.models.stage_outputs import CoverageVerificationResult
from claim_agent.tools.policy_logic import query_policy_db_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

# Policy result keys from query_policy_db_impl
_POLICY_VALID = "valid"
_POLICY_STATUS = "status"
_POLICY_MESSAGE = "message"
_POLICY_PHYSICAL_DAMAGE_COVERED = "physical_damage_covered"
_POLICY_PHYSICAL_DAMAGE_COVERAGES = "physical_damage_coverages"
_POLICY_DEDUCTIBLE = "deductible"

logger = logging.getLogger(__name__)

# US state codes and names for territory normalization
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
}

_US_STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming"
}


def _normalize_location(location: str) -> str:
    """Normalize location string for territory comparison.
    
    Handles case-insensitive matching, state codes, and common variations.
    Returns uppercase normalized location.
    """
    if not location:
        return ""
    loc = location.strip().upper()
    # Handle common variations
    if loc in ("USA", "UNITED STATES", "UNITED STATES OF AMERICA"):
        return "US"
    return loc


def _is_location_in_territory(
    incident_location: str,
    policy_territory: str | list[str] | None,
    excluded_territories: list[str] | None = None,
) -> tuple[bool, str]:
    """Check if incident location is within policy territory.
    
    Args:
        incident_location: Where the incident occurred (e.g., "California", "TX", "Canada")
        policy_territory: Policy coverage area (e.g., "US", "USA_Canada", ["CA", "NV"])
        excluded_territories: Explicitly excluded territories
    
    Returns:
        Tuple of (is_covered: bool, reason: str)
    """
    if not incident_location:
        return False, "Incident location not provided"
    
    if policy_territory is None:
        return True, "No territory restrictions on policy"
    
    incident_loc = _normalize_location(incident_location)
    
    # Check excluded territories first
    if excluded_territories:
        for excluded in excluded_territories:
            excluded_norm = _normalize_location(excluded)
            if incident_loc == excluded_norm:
                return False, f"Incident location '{incident_location}' is in excluded territory"
            # Check if incident state name matches excluded state
            if incident_location.title() in _US_STATE_NAMES and excluded.title() == incident_location.title():
                return False, f"Incident location '{incident_location}' is in excluded territory"
    
    # Handle string territory
    if isinstance(policy_territory, str):
        territory_norm = _normalize_location(policy_territory)
        
        # Special cases: US or USA_Canada
        if territory_norm == "US":
            if incident_loc in _US_STATE_CODES or incident_location.title() in _US_STATE_NAMES:
                return True, "Incident in US territory"
            if incident_loc in ("US", "USA"):
                return True, "Incident in US territory"
            return False, f"Incident location '{incident_location}' is outside US territory"
        
        if territory_norm == "USA_CANADA":
            if incident_loc in _US_STATE_CODES or incident_location.title() in _US_STATE_NAMES:
                return True, "Incident in US territory (USA_Canada policy)"
            if incident_loc in ("US", "USA", "CANADA", "CA"):
                return True, "Incident in USA/Canada territory"
            return False, f"Incident location '{incident_location}' is outside USA/Canada territory"
        
        # Direct match
        if incident_loc == territory_norm:
            return True, f"Incident in policy territory ({policy_territory})"
        
        # Check if it's a state within a country territory
        if incident_location.title() in _US_STATE_NAMES and territory_norm == "US":
            return True, "Incident in US territory"
        
        return False, f"Incident location '{incident_location}' is outside policy territory ({policy_territory})"
    
    # Handle list of territories
    if isinstance(policy_territory, list):
        for territory in policy_territory:
            territory_norm = _normalize_location(territory)
            if incident_loc == territory_norm:
                return True, f"Incident in policy territory ({territory})"
            # Check state name match
            if incident_location.title() in _US_STATE_NAMES and territory.title() == incident_location.title():
                return True, f"Incident in policy territory ({territory})"
        
        territories_str = ", ".join(policy_territory)
        return False, f"Incident location '{incident_location}' is outside policy territories ({territories_str})"
    
    return False, f"Invalid policy territory configuration: {policy_territory}"


def verify_coverage_impl(
    claim_data: dict,
    *,
    ctx: ClaimContext | None = None,
    config: dict | None = None,
) -> CoverageVerificationResult:
    """Verify policy coverage for the claim before routing.

    Checks: policy active, coverage type matches loss type, deductible vs damage.

    Returns:
        CoverageVerificationResult with passed, denied, or under_investigation.
    """
    config = config if config is not None else get_coverage_config()
    if not config.get("enabled", True):
        return CoverageVerificationResult(
            passed=True,
            reason="Coverage verification disabled",
            details={"enabled": False},
        )

    policy_number = claim_data.get("policy_number") or ""
    damage_description = claim_data.get("damage_description") or ""
    estimated_damage = claim_data.get("estimated_damage")

    if not policy_number or not isinstance(policy_number, str):
        return CoverageVerificationResult(
            denied=True,
            reason="Missing or invalid policy number",
            details={"policy_number": str(policy_number)[:20]},
        )

    policy_number = str(policy_number).strip()
    if not policy_number:
        return CoverageVerificationResult(
            denied=True,
            reason="Empty policy number",
            details={},
        )

    try:
        policy_json = query_policy_db_impl(
            policy_number,
            damage_description=damage_description,
            ctx=ctx,
        )
    except DomainValidationError as e:
        return CoverageVerificationResult(
            denied=True,
            reason=str(e),
            details={"error": "validation"},
        )
    except AdapterError as e:
        logger.warning("Policy lookup failed for coverage verification: %s", e)
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Policy lookup failed; requires manual review",
            details={"error": "adapter_error", "message": str(e)},
        )
    except Exception as e:
        logger.exception("Unexpected error during coverage verification")
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Coverage verification error; requires manual review",
            details={"error": "unexpected", "message": str(e)},
        )

    try:
        policy_result = json.loads(policy_json)
    except (json.JSONDecodeError, TypeError):
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Invalid policy response; requires manual review",
            details={"error": "parse_error"},
        )

    valid = policy_result.get(_POLICY_VALID, False)
    if not valid:
        status = policy_result.get(_POLICY_STATUS, "unknown")
        message = policy_result.get(_POLICY_MESSAGE, "Policy not found or inactive")
        return CoverageVerificationResult(
            denied=True,
            reason=message,
            details={
                "policy_status": status,
                "message": message,
            },
        )

    physical_damage_covered = policy_result.get(_POLICY_PHYSICAL_DAMAGE_COVERED, False)
    if not physical_damage_covered:
        coverages = policy_result.get(_POLICY_PHYSICAL_DAMAGE_COVERAGES, [])
        return CoverageVerificationResult(
            denied=True,
            reason="Loss type not covered under policy (no collision/comprehensive)",
            details={
                "physical_damage_covered": False,
                "policy_coverages": coverages,
            },
        )

    # Verify policy territory restrictions
    incident_location = claim_data.get("incident_location") or claim_data.get("loss_state")
    if incident_location:
        policy_territory = policy_result.get("territory")
        excluded_territories = policy_result.get("excluded_territories")
        
        is_covered, territory_reason = _is_location_in_territory(
            incident_location,
            policy_territory,
            excluded_territories,
        )
        
        if not is_covered:
            return CoverageVerificationResult(
                denied=True,
                reason=territory_reason,
                details={
                    "incident_location": incident_location,
                    "policy_territory": policy_territory,
                    "excluded_territories": excluded_territories,
                    "territory_verification": "denied",
                },
            )
    elif config.get("require_incident_location", False):
        # Optional: require incident location when territory restrictions exist
        policy_territory = policy_result.get("territory")
        if policy_territory is not None:
            return CoverageVerificationResult(
                under_investigation=True,
                reason="Incident location required for territory verification",
                details={
                    "policy_territory": policy_territory,
                    "territory_verification": "location_missing",
                },
            )

    # When deny_when_deductible_exceeds_damage: deny only when deductible strictly
    # exceeds estimated damage. est == ded or est == 0: claim passes (coverage exists;
    # payout may be $0). Change to ded >= est if business wants to deny when payout
    # would be zero.
    if config.get("deny_when_deductible_exceeds_damage") and estimated_damage is not None:
        deductible = policy_result.get(_POLICY_DEDUCTIBLE)
        if deductible is not None:
            try:
                ded = float(deductible)
                est = float(estimated_damage)
                if est > 0 and ded > est:
                    return CoverageVerificationResult(
                        denied=True,
                        reason=f"Deductible (${ded:,.0f}) exceeds estimated damage (${est:,.0f})",
                        details={
                            "deductible": ded,
                            "estimated_damage": est,
                        },
                    )
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Deductible/damage parse failed: deductible=%r estimated_damage=%r: %s",
                    deductible,
                    estimated_damage,
                    e,
                    extra={"claim_data_keys": list(claim_data.keys())},
                )
                return CoverageVerificationResult(
                    under_investigation=True,
                    reason="Unable to compare deductible to damage; requires manual review",
                    details={
                        "error": "parse_error",
                        "deductible": str(deductible)[:50],
                        "estimated_damage": str(estimated_damage)[:50],
                    },
                )

    details_dict = {
        "policy_status": policy_result.get(_POLICY_STATUS, "active"),
        "physical_damage_covered": True,
        "deductible": policy_result.get(_POLICY_DEDUCTIBLE),
    }
    
    # Include territory verification in success details
    incident_location = claim_data.get("incident_location") or claim_data.get("loss_state")
    if incident_location and policy_result.get("territory") is not None:
        details_dict["territory_verified"] = True
        details_dict["incident_location"] = incident_location
    
    return CoverageVerificationResult(
        passed=True,
        reason="Coverage verified",
        details=details_dict,
    )
