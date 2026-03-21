"""FNOL coverage verification: gate before routing.

Deterministic verification (no LLM) using policy adapter. Denies or escalates
claims that lack coverage before the router runs. When the policy exposes
named insureds/drivers, verifies the claimant name against those lists
(case-insensitive, whitespace-normalized).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, cast

from claim_agent.config.settings import get_coverage_config
from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.models.stage_outputs import CoverageVerificationResult
from claim_agent.tools.policy_logic import query_policy_db_impl
from claim_agent.utils.policy_party_name import get_policy_party_display_name

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

# Policy result keys from query_policy_db_impl
_POLICY_VALID = "valid"
_POLICY_STATUS = "status"
_POLICY_MESSAGE = "message"
_POLICY_PHYSICAL_DAMAGE_COVERED = "physical_damage_covered"
_POLICY_PHYSICAL_DAMAGE_COVERAGES = "physical_damage_coverages"
_POLICY_DEDUCTIBLE = "deductible"
_POLICY_NAMED_INSURED = "named_insured"
_POLICY_DRIVERS = "drivers"
_POLICY_EFFECTIVE_DATE = "effective_date"
_POLICY_EXPIRATION_DATE = "expiration_date"

logger = logging.getLogger(__name__)

# US state codes and names for territory normalization
_US_STATE_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}

_STATE_CODE_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}

# Full state names (incl. DC) -> canonical title form; keyed by casefold for robust matching.
_STATE_NAME_BY_CASEFOLD: dict[str, str] = {
    name.casefold(): name for name in _STATE_CODE_TO_NAME.values()
}

# US insular areas (policy "US" territory typically includes these; ISO-style codes).
_US_INSULAR_CODE_TO_NAME: dict[str, str] = {
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
    "GU": "Guam",
    "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_US_INSULAR_CODES = frozenset(_US_INSULAR_CODE_TO_NAME.keys())

_US_INSULAR_NAME_BY_CASEFOLD: dict[str, str] = {
    "puerto rico": "Puerto Rico",
    "u.s. virgin islands": "U.S. Virgin Islands",
    "us virgin islands": "U.S. Virgin Islands",
    "united states virgin islands": "U.S. Virgin Islands",
    "virgin islands": "U.S. Virgin Islands",
    "guam": "Guam",
    "american samoa": "American Samoa",
    "northern mariana islands": "Northern Mariana Islands",
}

# Canadian provinces and territories (ISO 3166-2:CA codes).
_CANADA_PROVINCE_CODE_TO_NAME: dict[str, str] = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}
_CANADA_PROVINCE_CODES = frozenset(_CANADA_PROVINCE_CODE_TO_NAME.keys())
_CANADA_NAME_BY_CASEFOLD: dict[str, str] = {
    name.casefold(): name for name in _CANADA_PROVINCE_CODE_TO_NAME.values()
}


class TerritoryConfigurationError(ValueError):
    """Policy adapter returned territory data we cannot interpret safely."""


def _ensure_str_list(value: object | None, *, label: str) -> list[str] | None:
    """Validate list-of-strings from policy JSON; raise if schema is wrong."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise TerritoryConfigurationError(f"{label} must be a list when provided")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TerritoryConfigurationError(
                f"{label} must contain only strings (invalid entry at index {i})"
            )
        out.append(item)
    return out


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


def _canonical_us_state(location: str) -> str | None:
    """Return the canonical (title-case full name) for a US state, or None.

    Handles both state codes (CA, TX) and full names (California, Texas),
    enabling bidirectional code/name equivalence for territory comparisons.
    """
    loc = location.strip()
    if not loc:
        return None
    # Try as 2-letter state code (incl. DC)
    name = _STATE_CODE_TO_NAME.get(loc.upper())
    if name:
        return name
    # Full state name: casefold lookup preserves "of" in District of Columbia, etc.
    return _STATE_NAME_BY_CASEFOLD.get(loc.casefold())


def _canonical_us_insular_area(location: str) -> str | None:
    """Canonical name for a US insular area (code or English name), or None."""
    loc = location.strip()
    if not loc:
        return None
    code = loc.upper()
    if code in _US_INSULAR_CODE_TO_NAME:
        return _US_INSULAR_CODE_TO_NAME[code]
    return _US_INSULAR_NAME_BY_CASEFOLD.get(loc.casefold())


def _canonical_us_region(location: str) -> str | None:
    """US state, DC, or US insular area canonical name."""
    s = _canonical_us_state(location)
    if s:
        return s
    return _canonical_us_insular_area(location)


def _canonical_canada_region(location: str) -> str | None:
    """Canadian province or territory canonical name (code or English name), or None."""
    loc = location.strip()
    if not loc:
        return None
    code = loc.upper()
    if code in _CANADA_PROVINCE_CODE_TO_NAME:
        return _CANADA_PROVINCE_CODE_TO_NAME[code]
    return _CANADA_NAME_BY_CASEFOLD.get(loc.casefold())


def _incident_in_us_policy_geography(incident_location: str, incident_loc_norm: str) -> bool:
    """True if the incident resolves to a US state, DC, or US insular area."""
    if incident_loc_norm in _US_STATE_CODES or incident_loc_norm in _US_INSULAR_CODES:
        return True
    return _canonical_us_region(incident_location) is not None


def _incident_in_canada_geography(incident_location: str, incident_loc_norm: str) -> bool:
    """True if the incident is Canada-wide or a province/territory (code or name)."""
    if incident_loc_norm == "CANADA":
        return True
    if incident_loc_norm in _CANADA_PROVINCE_CODES:
        return True
    return _canonical_canada_region(incident_location) is not None


def _is_location_in_territory(
    incident_location: str,
    policy_territory: object,
    excluded_territories: object = None,
) -> tuple[bool, str]:
    """Check if incident location is within policy territory.

    Args:
        incident_location: Where the incident occurred (e.g., "California", "TX", "Canada")
        policy_territory: Policy coverage area (e.g., "US", "USA_Canada", ["CA", "NV"])
        excluded_territories: Explicitly excluded territories

    Returns:
        Tuple of (is_covered: bool, reason: str)

    Raises:
        TerritoryConfigurationError: Invalid territory schema from the adapter.
    """
    if not incident_location:
        return False, "Incident location not provided"

    excluded_list = _ensure_str_list(excluded_territories, label="excluded_territories")

    incident_loc = _normalize_location(incident_location)

    # Enforce exclusions even when there is no positive territory (worldwide + carve-outs).
    if excluded_list:
        incident_us = _canonical_us_region(incident_location)
        incident_ca = _canonical_canada_region(incident_location)
        for excluded in excluded_list:
            excluded_norm = _normalize_location(excluded)
            # Direct normalized match
            if incident_loc == excluded_norm:
                return False, f"Incident location '{incident_location}' is in excluded territory"
            # US state/DC/insular code or name equivalence (e.g., AK <-> Alaska, PR <-> Puerto Rico)
            excluded_us = _canonical_us_region(excluded)
            if incident_us and excluded_us and incident_us == excluded_us:
                return False, f"Incident location '{incident_location}' is in excluded territory"
            # Canadian province/territory equivalence (e.g., ON <-> Ontario)
            excluded_ca = _canonical_canada_region(excluded)
            if incident_ca and excluded_ca and incident_ca == excluded_ca:
                return False, f"Incident location '{incident_location}' is in excluded territory"

    if policy_territory is None:
        return True, "No territory restrictions on policy"

    if isinstance(policy_territory, str):
        territory_norm = _normalize_location(policy_territory)

        # Special cases: US or USA_Canada
        if territory_norm == "US":
            if _incident_in_us_policy_geography(incident_location, incident_loc):
                return True, "Incident in US territory"
            if incident_loc == "US":
                return True, "Incident in US territory"
            return False, f"Incident location '{incident_location}' is outside US territory"

        if territory_norm == "USA_CANADA":
            if _incident_in_us_policy_geography(incident_location, incident_loc):
                return True, "Incident in US territory (USA_Canada policy)"
            if _incident_in_canada_geography(incident_location, incident_loc):
                return True, "Incident in Canada (USA_Canada policy)"
            if incident_loc in ("US", "CANADA"):
                return True, "Incident in USA/Canada territory"
            return False, f"Incident location '{incident_location}' is outside USA/Canada territory"

        # Direct match
        if incident_loc == territory_norm:
            return True, f"Incident in policy territory ({policy_territory})"

        return (
            False,
            f"Incident location '{incident_location}' is outside policy territory ({policy_territory})",
        )

    if isinstance(policy_territory, list):
        territories_list = cast(
            list[str],
            _ensure_str_list(policy_territory, label="territory"),
        )
        incident_us = _canonical_us_region(incident_location)
        incident_ca = _canonical_canada_region(incident_location)
        for territory in territories_list:
            territory_norm = _normalize_location(territory)
            # Direct normalized match
            if incident_loc == territory_norm:
                return True, f"Incident in policy territory ({territory})"
            # US state/DC/insular code or name equivalence (e.g., NV <-> Nevada, PR <-> Puerto Rico)
            territory_us = _canonical_us_region(territory)
            if incident_us and territory_us and incident_us == territory_us:
                return True, f"Incident in policy territory ({territory})"
            # Canadian province/territory equivalence (e.g., ON <-> Ontario)
            territory_ca = _canonical_canada_region(territory)
            if incident_ca and territory_ca and incident_ca == territory_ca:
                return True, f"Incident in policy territory ({territory})"

        territories_str = ", ".join(territories_list)
        return (
            False,
            f"Incident location '{incident_location}' is outside policy territories ({territories_str})",
        )

    raise TerritoryConfigurationError(
        f"Unsupported policy territory type: {type(policy_territory).__name__}"
    )


def _normalize_name(name: str | None) -> str:
    """Normalize a name for comparison (lowercase, normalize whitespace)."""
    if not name or not isinstance(name, str):
        return ""
    # Split/join collapses internal runs of whitespace and trims ends.
    return " ".join(name.split()).lower()


def _extract_person_names(value: object) -> list[str]:
    """Extract display names from a policy party structure, omitting PII fields.

    Accepts a dict (single person) or list of dicts (multiple persons) and
    returns only the name strings, leaving out email, phone, license_number, etc.
    """
    names: list[str] = []
    items: list[object] = []
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = value
    for item in items:
        if not isinstance(item, dict):
            continue
        name = get_policy_party_display_name(item)
        if name:
            names.append(name)
    return names


def _verify_named_insured_or_driver(
    claim_data: dict,
    policy_result: dict,
) -> tuple[bool, str | None]:
    """Verify claimant is named insured or authorized driver.

    Returns:
        (is_verified, reason_if_not_verified)
        - If verification data is incomplete, returns (True, None) to allow claim to proceed
        - Only returns (False, reason) when we have both policy and claimant data but they don't match
    """
    named_insured_list = policy_result.get(_POLICY_NAMED_INSURED)
    drivers_list = policy_result.get(_POLICY_DRIVERS)

    # If policy doesn't expose these fields, allow claim to proceed (legacy policies)
    if named_insured_list is None and drivers_list is None:
        return True, None

    # Extract claimant name from claim data
    claimant_name = None
    parties = claim_data.get("parties")
    if not isinstance(parties, list):
        parties = []

    # Look for claimant in parties array (preferred method)
    for party in parties:
        if not isinstance(party, dict):
            continue
        raw_party_type = party.get("party_type", "")
        party_type = raw_party_type.lower() if isinstance(raw_party_type, str) else ""
        if party_type == "claimant":
            claimant_name = party.get("name")
            break

    # Fallback: check claimant_name field directly
    if not claimant_name:
        claimant_name = claim_data.get("claimant_name")

    # If no claimant identified, allow claim to proceed (will be captured by agents)
    if not claimant_name:
        return True, None

    claimant_normalized = _normalize_name(claimant_name)
    if not claimant_normalized:
        return True, None

    # Check if claimant matches any named insured
    if isinstance(named_insured_list, list):
        for insured in named_insured_list:
            if not isinstance(insured, dict):
                continue
            insured_name = _normalize_name(get_policy_party_display_name(insured))
            if insured_name and insured_name == claimant_normalized:
                return True, None

    # Check if claimant matches any authorized driver
    if isinstance(drivers_list, list):
        for driver in drivers_list:
            if not isinstance(driver, dict):
                continue
            driver_name = _normalize_name(get_policy_party_display_name(driver))
            if driver_name and driver_name == claimant_normalized:
                return True, None

    # Claimant does not match named insured or drivers
    return False, f"Claimant '{claimant_name}' is not listed as named insured or authorized driver"


def _parse_iso_date_str(value: object) -> date | None:
    """Parse YYYY-MM-DD from string; return None if missing or invalid."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        s = value.strip()
        if len(s) < 10:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _incident_date_from_claim(claim_data: dict) -> tuple[date | None, bool]:
    """Return (incident_date, unparseable).

    (None, False): no incident date to verify (skip policy-term check).
    (date, False): parsed successfully.
    (None, True): incident_date present but not parseable.
    """
    raw = claim_data.get("incident_date")
    if raw is None:
        return (None, False)
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return (raw, False)
    if isinstance(raw, datetime):
        return (raw.date(), False)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return (None, False)
        try:
            return (date.fromisoformat(s[:10]), False)
        except ValueError:
            return (None, True)
    return (None, True)


def _policy_term_verification_result(
    claim_data: dict,
    policy_result: dict,
) -> CoverageVerificationResult | None:
    """If policy defines a term, verify incident_date is within [effective, expiration].

    Returns None to continue when term data is absent or incident date is not provided.
    """
    eff_raw = policy_result.get(_POLICY_EFFECTIVE_DATE)
    exp_raw = policy_result.get(_POLICY_EXPIRATION_DATE)
    eff_missing = eff_raw is None or (isinstance(eff_raw, str) and not eff_raw.strip())
    exp_missing = exp_raw is None or (isinstance(exp_raw, str) and not exp_raw.strip())

    if eff_missing and exp_missing:
        return None
    if eff_missing or exp_missing:
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Invalid policy term configuration; requires manual review",
            details={
                "error": "policy_term_config",
                "effective_date": eff_raw,
                "expiration_date": exp_raw,
            },
        )

    eff = _parse_iso_date_str(eff_raw)
    exp = _parse_iso_date_str(exp_raw)
    if eff is None or exp is None:
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Invalid policy term dates; requires manual review",
            details={
                "error": "policy_term_parse",
                "effective_date": eff_raw,
                "expiration_date": exp_raw,
            },
        )
    if exp < eff:
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Invalid policy term configuration; requires manual review",
            details={
                "error": "policy_term_inverted",
                "effective_date": eff.isoformat(),
                "expiration_date": exp.isoformat(),
            },
        )

    incident_d, bad_incident = _incident_date_from_claim(claim_data)
    if incident_d is None and not bad_incident:
        return None
    if bad_incident:
        return CoverageVerificationResult(
            under_investigation=True,
            reason="Unable to parse incident date for policy term verification",
            details={
                "error": "incident_date_parse",
                "term_verification": "incident_unparseable",
                "effective_date": eff.isoformat(),
                "expiration_date": exp.isoformat(),
            },
        )

    if incident_d < eff:
        return CoverageVerificationResult(
            denied=True,
            reason=(
                f"Incident date {incident_d.isoformat()} is before policy effective date "
                f"{eff.isoformat()}"
            ),
            details={
                "incident_date": incident_d.isoformat(),
                "effective_date": eff.isoformat(),
                "expiration_date": exp.isoformat(),
                "term_verification": "before_effective",
            },
        )
    if incident_d > exp:
        return CoverageVerificationResult(
            denied=True,
            reason=(
                f"Incident date {incident_d.isoformat()} is after policy expiration date "
                f"{exp.isoformat()}"
            ),
            details={
                "incident_date": incident_d.isoformat(),
                "effective_date": eff.isoformat(),
                "expiration_date": exp.isoformat(),
                "term_verification": "after_expiration",
            },
        )
    return None


def _incident_location_from_claim(claim_data: dict) -> str | None:
    """Return trimmed incident location, or None if absent or whitespace-only."""
    raw = claim_data.get("incident_location") or claim_data.get("loss_state")
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s or None
    s = str(raw).strip()
    return s or None


def verify_coverage_impl(
    claim_data: dict,
    *,
    ctx: ClaimContext | None = None,
    config: dict | None = None,
) -> CoverageVerificationResult:
    """Verify policy coverage for the claim before routing.

    Checks: policy active, physical damage coverage for the loss, optional
    named-insured/authorized-driver match when policy data includes parties,
    and optionally deductible vs estimated damage.

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

    term_outcome = _policy_term_verification_result(claim_data, policy_result)
    if term_outcome is not None:
        return term_outcome

    # Verify policy territory restrictions
    incident_location = _incident_location_from_claim(claim_data)
    if incident_location:
        policy_territory = policy_result.get("territory")
        excluded_territories = policy_result.get("excluded_territories")

        try:
            is_covered, territory_reason = _is_location_in_territory(
                incident_location,
                policy_territory,
                excluded_territories,
            )
        except TerritoryConfigurationError as e:
            return CoverageVerificationResult(
                under_investigation=True,
                reason="Invalid policy territory configuration; requires manual review",
                details={
                    "error": "territory_config",
                    "message": str(e),
                    "territory_verification": "config_error",
                },
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
        policy_territory = policy_result.get("territory")
        excluded_raw = policy_result.get("excluded_territories")
        has_exclusions = isinstance(excluded_raw, list) and len(excluded_raw) > 0
        if policy_territory is not None or has_exclusions:
            return CoverageVerificationResult(
                under_investigation=True,
                reason="Incident location required for territory verification",
                details={
                    "policy_territory": policy_territory,
                    "excluded_territories": excluded_raw,
                    "territory_verification": "location_missing",
                },
            )

    # Named insured / driver verification
    is_verified, verification_reason = _verify_named_insured_or_driver(claim_data, policy_result)
    if not is_verified:
        logger.info(
            "Named insured/driver verification failed: %s",
            verification_reason,
            extra={"claim_data_keys": list(claim_data.keys())},
        )
        return CoverageVerificationResult(
            under_investigation=True,
            reason=verification_reason or "Claimant verification requires manual review",
            details={
                "verification_failed": True,
                "verification_reason": verification_reason,
                # Include only names (no PII: email/phone/license_number) for adjuster review.
                "named_insured": _extract_person_names(policy_result.get(_POLICY_NAMED_INSURED)),
                "drivers": _extract_person_names(policy_result.get(_POLICY_DRIVERS)),
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

    inc_ok, inc_bad = _incident_date_from_claim(claim_data)
    if (
        inc_ok is not None
        and not inc_bad
        and policy_result.get(_POLICY_EFFECTIVE_DATE) is not None
        and policy_result.get(_POLICY_EXPIRATION_DATE) is not None
    ):
        details_dict["term_verified"] = True
        details_dict["incident_date"] = inc_ok.isoformat()

    # Include territory verification in success details when a territory or exclusion rule applied
    incident_location = _incident_location_from_claim(claim_data)
    if incident_location:
        has_positive_territory = policy_result.get("territory") is not None
        excluded_raw = policy_result.get("excluded_territories")
        has_exclusions = isinstance(excluded_raw, list) and len(excluded_raw) > 0
        if has_positive_territory or has_exclusions:
            details_dict["territory_verified"] = True
            details_dict["incident_location"] = incident_location

    return CoverageVerificationResult(
        passed=True,
        reason="Coverage verified",
        details=details_dict,
    )
