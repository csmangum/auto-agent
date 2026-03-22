"""LLM data minimization for privacy compliance.

Only sends fields necessary for each crew's task to the LLM. Masks PII
(policy_number, VIN) when minimization is enabled. Excludes claimant
name/email/phone/address unless crew explicitly requires it.
"""

from __future__ import annotations

from typing import Any

from claim_agent.config import get_settings
from claim_agent.utils.pii_masking import mask_policy_number, mask_vin

# Per-crew allowlists of claim fields. Keys are crew identifiers used in stages.
# Fields not in the allowlist are excluded. Use "*" to allow all (no minimization).
_CREW_ALLOWLISTS: dict[str, frozenset[str]] = {
    # Router: classification needs incident/damage, vehicle, loss_state
    "router": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "loss_state",
            "attachments",
            "prior_claim_id",
            "reopening_reason",
            "is_reopened",
            "existing_claims_for_vin",
            "damage_tags",
            "definitive_duplicate",
            "is_economic_total_loss",
            "is_catastrophic_event",
            "damage_indicates_total_loss",
            "damage_is_repairable",
            "vehicle_value",
            "damage_to_value_ratio",
            "high_value_claim",
            "pre_routing_fraud_indicators",
        }
    ),
    # Duplicate crew: vin, incident_date for search; incident_description for similarity
    "duplicate": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "existing_claims_for_vin",
            "damage_tags",
            "definitive_duplicate",
        }
    ),
    # New claim crew: minimal for FNOL
    "new": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "loss_state",
            "attachments",
        }
    ),
    # Fraud detection: needs incident/damage, vehicle; no party PII
    "fraud": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "pre_routing_fraud_indicators",
            "high_value_claim",
        }
    ),
    # Partial loss: repair estimate, shop assignment, parts
    "partial_loss": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "attachments",
        }
    ),
    # Total loss: vehicle value, salvage
    "total_loss": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "attachments",
            "vehicle_value",
            "damage_to_value_ratio",
            "is_economic_total_loss",
        }
    ),
    # Bodily injury: incident, parties (role only, no contact PII for liability)
    "bodily_injury": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "attachments",
            "parties",  # role only; strip name/email/phone/address below
        }
    ),
    # Reopened: prior claim context
    "reopened": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "prior_claim_id",
            "reopening_reason",
            "loss_state",
        }
    ),
    # Escalation: router output, similarity, payout
    "escalation_check": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "router_confidence",
            "router_reasoning",
            "raw_output",
            "existing_claims_for_vin",
            "definitive_duplicate",
            "high_value_claim",
        }
    ),
    # Task planner: loss_state for compliance deadlines
    "task_planner": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
        }
    ),
    # Rental: vehicle, payout, estimate
    "rental": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
        }
    ),
    # Liability: incident_description, loss_state; no policy_number, vin, parties PII
    "liability_determination": frozenset(
        {
            "claim_id",
            "incident_date",
            "incident_description",
            "damage_description",
            "claim_type",
            "status",
            "loss_state",
            "workflow_output",
        }
    ),
    # Settlement: payout, status
    "settlement": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
            "liability_percentage",
            "liability_basis",
        }
    ),
    # Subrogation: liability, payout
    "subrogation": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
            "liability_percentage",
            "liability_basis",
        }
    ),
    # Salvage: vehicle, payout
    "salvage": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
        }
    ),
    # After action: summary
    "after_action": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
            "payout_amount",
            "loss_state",
            "workflow_output",
        }
    ),
    # Standalone orchestrators
    "siu": frozenset(
        {
            "id",
            "claim_id",
            "siu_case_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "status",
            "claim_type",
            "state",
        }
    ),
    "follow_up": frozenset(
        {
            "id",
            "claim_id",
            "policy_number",
            "vin",
            "status",
            "claim_type",
            "incident_description",
            "damage_description",
        }
    ),
    "party_intake": frozenset(
        {
            "id",
            "claim_id",
            "policy_number",
            "vin",
            "status",
            "claim_type",
            "incident_description",
            "damage_description",
            "parties",
        }
    ),
    "dispute": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "payout_amount",
            "claim_type",
            "status",
        }
    ),
    "supplemental": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "payout_amount",
            "claim_type",
            "status",
        }
    ),
    "denial_coverage": frozenset(
        {
            "claim_id",
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
            "estimated_damage",
            "claim_type",
            "status",
        }
    ),
    "claim_review": frozenset(
        {
            "id",
            "status",
            "claim_type",
            "policy_number",
            "vin",
            "incident_date",
            "incident_description",
            "damage_description",
            "payout_amount",
            "created_at",
            "updated_at",
        }
    ),
}


def _minimize_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip descriptions from attachments; keep url and type only."""
    if not attachments or not isinstance(attachments, list):
        return []
    result = []
    for a in attachments:
        if isinstance(a, dict) and a.get("url"):
            result.append({"url": a["url"], "type": a.get("type", "other")})
    return result


def _strip_party_pii(parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip name, email, phone, address from parties; keep role and party_type."""
    if not parties or not isinstance(parties, list):
        return []
    result = []
    for p in parties:
        if isinstance(p, dict):
            stripped = {
                "party_type": p.get("party_type"),
                "role": p.get("role"),
            }
            result.append({k: v for k, v in stripped.items() if v is not None})
    return result


def minimize_claim_data_for_crew(
    claim_data: dict[str, Any],
    crew_name: str,
    *,
    mask_pii: bool | None = None,
    force_allowlist: bool = False,
) -> dict[str, Any]:
    """Return minimized claim data for the given crew.

    - Filters to allowlisted fields only
    - When mask_pii is True (default from config): masks policy_number and vin
    - Strips attachment descriptions (urls only)
    - For bodily_injury crew only: strips party name/email/phone/address

    Args:
        claim_data: Full claim dict
        crew_name: Crew identifier (e.g. "router", "partial_loss", "siu")
        mask_pii: Override config. None = use get_settings().privacy.llm_data_minimization
        force_allowlist: When True, apply the crew allowlist even if
            ``PRIVACY_LLM_DATA_MINIMIZATION`` is false (e.g. router validation LLM calls).

    Returns:
        Minimized dict safe to pass to LLM prompts
    """
    settings = get_settings()
    enabled = settings.privacy.llm_data_minimization

    if mask_pii is None:
        mask_pii = enabled

    if not force_allowlist and not enabled and not mask_pii:
        return dict(claim_data)

    allowlist = _CREW_ALLOWLISTS.get(crew_name)
    if allowlist is None:
        allowlist = frozenset(claim_data.keys())  # allow all for unknown crews

    result: dict[str, Any] = {}
    for key, value in claim_data.items():
        if key not in allowlist:
            continue
        if key == "attachments" and isinstance(value, list):
            result[key] = _minimize_attachments(value)
        elif key == "parties" and crew_name == "bodily_injury":
            result[key] = _strip_party_pii(value) if isinstance(value, list) else value
        elif key == "policy_number" and mask_pii:
            result[key] = mask_policy_number(value) if value else value
        elif key == "vin" and mask_pii:
            result[key] = mask_vin(value) if value else value
        else:
            result[key] = value

    return result
