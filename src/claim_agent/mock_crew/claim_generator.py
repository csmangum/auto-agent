"""Mock Crew: generate claim input via policy + vehicle selection, then LLM for damage.

Claim data must match a policy. Flow:
1. Pick a policy (random or filtered: active, optionally with collision coverage)
2. Pick a vehicle from that policy's insured vehicles
3. LLM generates incident/damage details (incident_date, incident_description,
   damage_description, estimated_damage) based on the prompt and vehicle info.
"""

import json
import random
from datetime import date, timedelta
from typing import Any

import litellm

from claim_agent.config.llm import get_llm, get_model_name
from claim_agent.config.settings import get_mock_crew_config
from claim_agent.data.loader import load_mock_db
from claim_agent.models.claim import ClaimInput

_DAMAGE_SCHEMA = """
Return a single JSON object with these exact keys (no extra fields):
- incident_date: string "YYYY-MM-DD" (recent date, within last 90 days)
- incident_description: string (1-3 sentences describing what happened)
- damage_description: string (1-3 sentences describing vehicle damage)
- estimated_damage: number or null (repair cost in dollars, or null if unknown)

Generate realistic US auto insurance claim details. Damage should be consistent
with the incident. Estimated damage should be plausible for the described damage.
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract first JSON object from text (handles nested braces)."""
    if not text:
        return None
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    if "```json" in text:
        try:
            extracted = text.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except (IndexError, json.JSONDecodeError):
            pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


_KNOWN_MAKES_MODELS = (
    "tesla", "honda", "ford", "toyota", "bmw", "jeep", "chevrolet", "chevy",
    "mazda", "volkswagen", "vw", "ram", "dodge", "accord", "civic", "model 3",
    "model s", "mustang", "camry", "corolla", "odyssey"
)


def _vehicle_filter_from_prompt(prompt: str) -> str | None:
    """Extract vehicle make/model from prompt if mentioned."""
    if not prompt:
        return None
    lower = prompt.lower()
    for token in _KNOWN_MAKES_MODELS:
        if token in lower:
            return token.title()
    return None


def _pick_policy_and_vehicle(
    *,
    require_collision: bool = True,
    vehicle_filter: str | None = None,
    seed: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Pick a random active policy and one of its insured vehicles.

    Args:
        require_collision: Only policies with collision coverage.
        vehicle_filter: Optional substring to match vehicle make or model (case-insensitive).
            E.g. "Tesla" or "Honda Accord" to prefer matching vehicles.
        seed: For reproducible selection.

    Returns:
        (policy_number, vehicle_dict with vin, vehicle_year, vehicle_make, vehicle_model)
    """
    db = load_mock_db()
    policies = db.get("policies", {})
    policy_vehicles = db.get("policy_vehicles", {})

    rng = random.Random(seed)

    candidates: list[tuple[str, dict[str, Any]]] = []
    for pn, pdata in policies.items():
        if pdata.get("status") != "active":
            continue
        if require_collision and "collision" not in (pdata.get("coverages") or []):
            continue
        vehicles = policy_vehicles.get(pn)
        if not vehicles:
            continue
        for v in vehicles:
            if vehicle_filter:
                desc = f"{v.get('vehicle_make','')} {v.get('vehicle_model','')}".lower()
                if vehicle_filter.lower() not in desc:
                    continue
            candidates.append((pn, v))

    if not candidates and vehicle_filter:
        # Fallback: ignore vehicle filter if no matches
        candidates = []
        for pn, pdata in policies.items():
            if pdata.get("status") != "active":
                continue
            if require_collision and "collision" not in (pdata.get("coverages") or []):
                continue
            for v in policy_vehicles.get(pn) or []:
                candidates.append((pn, v))

    if not candidates:
        raise ValueError(
            "No active policies with collision coverage and insured vehicles in mock_db. "
            "Add policy_vehicles to data/mock_db.json."
        )

    policy_number, vehicle = rng.choice(candidates)
    return policy_number, vehicle


def generate_claim_from_prompt(
    prompt: str,
    *,
    seed: int | None = None,
    require_collision: bool = True,
) -> ClaimInput:
    """Generate claim input: policy + vehicle from mock_db, incident/damage from LLM.

    Args:
        prompt: Description of the claim scenario (e.g. "partial loss, parking lot
            fender bender" or "total loss, flood damage").
        seed: Optional seed for reproducibility (policy/vehicle selection and LLM).
        require_collision: If True, only pick policies with collision coverage.

    Returns:
        Validated ClaimInput with policy and vehicle from mock_db, incident/damage
        from LLM.

    Raises:
        ValueError: If mock crew disabled or no matching policies/vehicles.
    """
    crew_cfg = get_mock_crew_config()
    if not crew_cfg.get("enabled"):
        raise ValueError(
            "Mock Crew must be enabled (MOCK_CREW_ENABLED=true) to generate claims."
        )
    if seed is None:
        seed = crew_cfg.get("seed")

    # 1. Pick policy and vehicle from mock_db (optionally filter by make/model in prompt)
    vehicle_filter = _vehicle_filter_from_prompt(prompt)
    policy_number, vehicle = _pick_policy_and_vehicle(
        require_collision=require_collision,
        vehicle_filter=vehicle_filter,
        seed=seed,
    )

    # 2. LLM generates incident/damage only
    get_llm()

    vehicle_desc = (
        f"{vehicle['vehicle_year']} {vehicle['vehicle_make']} {vehicle['vehicle_model']} "
        f"(VIN: {vehicle['vin']})"
    )
    full_prompt = f"""{_DAMAGE_SCHEMA}

Vehicle (insured under policy {policy_number}): {vehicle_desc}

User request / scenario: {prompt}

Return only the JSON object, no markdown or explanation."""

    model = get_model_name()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": full_prompt}],
    }
    if seed is not None:
        kwargs["seed"] = seed

    resp = litellm.completion(**kwargs)
    text = (resp.choices[0].message.content or "").strip()
    parsed = _extract_json(text)
    if not parsed:
        raise ValueError(f"LLM did not return valid JSON. Raw output: {text[:500]}")

    # 3. Merge: policy + vehicle (from mock_db) + incident/damage (from LLM)
    incident_date = parsed.get("incident_date")
    if isinstance(incident_date, str):
        incident_date = incident_date[:10]
    else:
        # Fallback: recent date
        incident_date = (date.today() - timedelta(days=7)).isoformat()

    claim_data: dict[str, Any] = {
        "policy_number": policy_number,
        "vin": vehicle["vin"],
        "vehicle_year": vehicle["vehicle_year"],
        "vehicle_make": vehicle["vehicle_make"],
        "vehicle_model": vehicle["vehicle_model"],
        "incident_date": incident_date,
        "incident_description": parsed.get("incident_description", "Incident occurred."),
        "damage_description": parsed.get("damage_description", "Vehicle damage."),
        "estimated_damage": parsed.get("estimated_damage"),
        "attachments": [],
    }

    return ClaimInput.model_validate(claim_data)
