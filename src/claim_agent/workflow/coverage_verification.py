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

logger = logging.getLogger(__name__)


def verify_coverage_impl(
    claim_data: dict,
    *,
    ctx: ClaimContext | None = None,
) -> CoverageVerificationResult:
    """Verify policy coverage for the claim before routing.

    Checks: policy active, coverage type matches loss type, deductible vs damage.
    Named insured/driver/territory deferred to under_investigation when policy
    lacks those fields.

    Returns:
        CoverageVerificationResult with passed, denied, or under_investigation.
    """
    config = get_coverage_config()
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

    valid = policy_result.get("valid", False)
    if not valid:
        status = policy_result.get("status", "unknown")
        message = policy_result.get("message", "Policy not found or inactive")
        return CoverageVerificationResult(
            denied=True,
            reason=message,
            details={
                "policy_status": status,
                "message": message,
            },
        )

    physical_damage_covered = policy_result.get("physical_damage_covered", False)
    if not physical_damage_covered:
        coverages = policy_result.get("physical_damage_coverages", [])
        return CoverageVerificationResult(
            denied=True,
            reason="Loss type not covered under policy (no collision/comprehensive)",
            details={
                "physical_damage_covered": False,
                "policy_coverages": coverages,
                "damage_description": damage_description[:100],
            },
        )

    if config.get("deny_when_deductible_exceeds_damage") and estimated_damage is not None:
        deductible = policy_result.get("deductible")
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
            except (TypeError, ValueError):
                pass

    return CoverageVerificationResult(
        passed=True,
        reason="Coverage verified",
        details={
            "policy_status": policy_result.get("status", "active"),
            "physical_damage_covered": True,
            "deductible": policy_result.get("deductible"),
        },
    )
