"""FNOL coverage verification: gate before routing.

Deterministic verification (no LLM) using policy adapter. Denies or escalates
claims that lack coverage before the router runs. When the policy exposes
named insureds/drivers, verifies the claimant name against those lists
(case-insensitive, whitespace-normalized).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

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

logger = logging.getLogger(__name__)


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

    return CoverageVerificationResult(
        passed=True,
        reason="Coverage verified",
        details={
            "policy_status": policy_result.get(_POLICY_STATUS, "active"),
            "physical_damage_covered": True,
            "deductible": policy_result.get(_POLICY_DEDUCTIBLE),
        },
    )
