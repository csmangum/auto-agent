"""FNOL: seed policyholder party from policy ``named_insured`` when missing."""

from __future__ import annotations

from typing import Any

from claim_agent.models.party import ClaimPartyInput
from claim_agent.utils.policy_party_name import get_policy_party_display_name


def _coerce_contact(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s or None
    return None


def policyholder_party_from_named_insured(policy: dict[str, Any] | None) -> ClaimPartyInput | None:
    """Build a policyholder ``ClaimPartyInput`` from the first named insured with a display name."""
    if not policy:
        return None
    raw = policy.get("named_insured")
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = get_policy_party_display_name(entry)
        if not name:
            continue
        return ClaimPartyInput(
            party_type="policyholder",
            name=name,
            email=_coerce_contact(entry.get("email")),
            phone=_coerce_contact(entry.get("phone")),
        )
    return None


def merge_fnol_parties_with_named_insured_policyholder(
    parties: list[ClaimPartyInput] | None,
    policy: dict[str, Any] | None,
) -> list[ClaimPartyInput]:
    """Return parties list, prepending policyholder from policy when no policyholder was supplied."""
    existing = list(parties) if parties else []
    if any(p.party_type == "policyholder" for p in existing):
        return existing
    ph = policyholder_party_from_named_insured(policy)
    if ph is None:
        return existing
    return [ph, *existing]
