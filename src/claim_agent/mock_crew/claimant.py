"""Mock Claimant: rule/template-based claimant that submits ClaimInput-shaped data.

Provides deterministic, template-driven generation of claim submissions and
rule-based responses to follow-up messages—no LLM required.

Scenario shape (all keys optional; sensible defaults applied when absent):
    {
        "claim_type": str,          # e.g. "partial_loss", "total_loss", "new"
        "incident": {
            "date": str,            # ISO "YYYY-MM-DD"; defaults to 7 days ago
            "description": str,     # free-text incident description
            "location": str,        # e.g. "Main St & 1st Ave, Austin, TX"
            "loss_state": str,      # two-letter state code, e.g. "TX"
        },
        "damage": {
            "description": str,     # free-text damage description
            "estimated_damage": float | None,
        },
        "vehicle": {
            "vin": str,
            "year": int,
            "make": str,
            "model": str,
        },
        "policy": {
            "policy_number": str,
        },
    }
"""

import logging
import random
from datetime import date, timedelta
from typing import Any

from claim_agent.config.settings import get_mock_claimant_config, get_mock_crew_config
from claim_agent.config.settings_model import ResponseStrategy
from claim_agent.models.claim import ClaimInput, ClaimType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

_DEFAULT_INCIDENTS: list[dict[str, str]] = [
    {
        "description": (
            "I was stopped at a red light when another vehicle rear-ended my car. "
            "The other driver admitted fault at the scene."
        ),
        "damage_description": (
            "Significant damage to the rear bumper, trunk lid, and tail lights. "
            "The trunk no longer closes properly."
        ),
    },
    {
        "description": (
            "While parking in a shopping centre car park, another vehicle struck "
            "the driver-side door and drove off without leaving a note."
        ),
        "damage_description": (
            "Deep dent and paint scrape on the driver-side door. "
            "The door seal is also damaged."
        ),
    },
    {
        "description": (
            "A large branch fell on my vehicle during a storm and caused "
            "extensive damage to the roof and windshield."
        ),
        "damage_description": (
            "Crushed roof panel, cracked windshield, and damaged hood. "
            "The vehicle is not drivable."
        ),
    },
    {
        "description": (
            "I lost control of the vehicle on an icy road and struck a guardrail "
            "on the passenger side."
        ),
        "damage_description": (
            "Damage to the front passenger fender, bumper, and headlight assembly. "
            "The airbags did not deploy."
        ),
    },
]

_DEFAULT_VEHICLE = {
    "vin": "1HGBH41JXMN109186",
    "year": 2021,
    "make": "Honda",
    "model": "Accord",
}

_DEFAULT_POLICY_NUMBER = "POL-001"

_RESPONSE_STRATEGY_REFUSE_MSG = (
    "I'm sorry, I'm not able to provide that information at this time."
)
_RESPONSE_STRATEGY_PARTIAL_MSG = (
    "I can share part of what you need, but I don't have everything right now. "
    "I'll follow up as soon as I do."
)
_RESPONSE_STRATEGY_DELAYED_MSG = (
    "I'll need a little more time to gather that. "
    "I'll get back to you within one business day."
)

# ---------------------------------------------------------------------------
# Keyword sets for rule-based respond_to_message
# ---------------------------------------------------------------------------

_PHOTO_KEYWORDS = frozenset(
    {"photo", "photos", "picture", "pictures", "image", "images", "upload", "attach", "attachment"}
)
_ESTIMATE_KEYWORDS = frozenset(
    {
        "estimate", "quote", "appraisal", "body shop", "mechanic", "invoice",
        "repair estimate", "repair shop",
    }
)
_POLICE_REPORT_KEYWORDS = frozenset(
    {"police report", "police", "incident report", "case number", "officer"}
)
_MEDICAL_KEYWORDS = frozenset(
    {"medical", "doctor", "hospital", "injury", "injuries", "records", "treatment", "prescription"}
)
_CONTACT_KEYWORDS = frozenset(
    {"contact", "phone", "email", "reach", "get in touch", "phone number"}
)


def _pick_random_incident(rng: random.Random) -> dict[str, str]:
    """Return a randomly chosen default incident template."""
    return rng.choice(_DEFAULT_INCIDENTS)


def _build_rng(seed: int | None) -> random.Random:
    """Return a seeded (or random) Random instance."""
    return random.Random(seed) if seed is not None else random.Random()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_claim_input(scenario: dict[str, Any]) -> ClaimInput:
    """Generate a validated ClaimInput from a scenario description.

    The scenario may omit any key; defaults are applied for missing fields so
    the result is always a valid ClaimInput.

    The random seed is drawn from the shared mock crew config (``MOCK_CREW_SEED``)
    so that all mock crew components produce correlated, reproducible outputs from
    a single seed—consistent with how ``claim_generator.py`` handles seeding.

    Args:
        scenario: Partial scenario dict (see module docstring for shape).

    Returns:
        Validated ClaimInput instance.
    """
    crew_cfg = get_mock_crew_config()
    seed: int | None = crew_cfg.get("seed")
    rng = _build_rng(seed)

    # --- Policy ---
    policy = scenario.get("policy") or {}
    policy_number: str = policy.get("policy_number") or _DEFAULT_POLICY_NUMBER

    # --- Vehicle ---
    vehicle = scenario.get("vehicle") or {}
    vin: str = vehicle.get("vin") or _DEFAULT_VEHICLE["vin"]
    vehicle_year: int = int(vehicle.get("year") or _DEFAULT_VEHICLE["year"])
    vehicle_make: str = vehicle.get("make") or _DEFAULT_VEHICLE["make"]
    vehicle_model: str = vehicle.get("model") or _DEFAULT_VEHICLE["model"]

    # --- Incident ---
    incident = scenario.get("incident") or {}
    template = _pick_random_incident(rng)

    raw_date = incident.get("date")
    if raw_date:
        incident_date: str = raw_date
    else:
        incident_date = (date.today() - timedelta(days=7)).isoformat()

    incident_description: str = incident.get("description") or template["description"]
    incident_location: str | None = incident.get("location") or None
    loss_state: str | None = incident.get("loss_state") or None

    # --- Damage ---
    damage = scenario.get("damage") or {}
    damage_description: str = damage.get("description") or template["damage_description"]
    estimated_damage: float | None = damage.get("estimated_damage")
    if estimated_damage is not None:
        try:
            estimated_damage = float(estimated_damage)
            if estimated_damage < 0:
                estimated_damage = None
        except (TypeError, ValueError):
            estimated_damage = None

    # --- Claim type (validated against ClaimType enum) ---
    claim_type: str | None = scenario.get("claim_type") or None
    if claim_type is not None:
        valid_types = {ct.value for ct in ClaimType}
        if claim_type not in valid_types:
            logger.warning(
                "Invalid claim_type %r (valid: %s); dropping from scenario",
                claim_type,
                ", ".join(sorted(valid_types)),
            )
            claim_type = None

    result: dict[str, Any] = {
        "policy_number": policy_number,
        "vin": vin,
        "vehicle_year": vehicle_year,
        "vehicle_make": vehicle_make,
        "vehicle_model": vehicle_model,
        "incident_date": incident_date,
        "incident_description": incident_description,
        "damage_description": damage_description,
    }

    if estimated_damage is not None:
        result["estimated_damage"] = estimated_damage
    if claim_type is not None:
        result["claim_type"] = claim_type
    if incident_location is not None:
        result["incident_location"] = incident_location
    if loss_state is not None:
        result["loss_state"] = loss_state

    return ClaimInput.model_validate(result)


def respond_to_message(
    claim_id: str,
    message_content: str,
    claim_context: dict[str, Any] | None = None,
) -> str:
    """Generate a rule-based claimant response to a follow-up message.

    Keyword matching is used to determine the nature of the request and return
    an appropriate canned reply.  The ``claim_context`` dict may contain
    ``incident``, ``damage``, and ``vehicle`` sub-dicts for richer replies.

    Args:
        claim_id: The claim identifier (used for context / logging).
        message_content: The message text the claimant is responding to.
        claim_context: Optional context dict with incident/damage/vehicle info.

    Returns:
        A short string reply from the mock claimant.
    """
    logger.debug("Mock claimant responding to claim %s", claim_id)
    claimant_cfg = get_mock_claimant_config()
    strategy = claimant_cfg.get("response_strategy", ResponseStrategy.IMMEDIATE)

    if strategy == ResponseStrategy.REFUSE:
        return _RESPONSE_STRATEGY_REFUSE_MSG
    if strategy == ResponseStrategy.DELAYED:
        return _RESPONSE_STRATEGY_DELAYED_MSG
    if strategy == ResponseStrategy.PARTIAL:
        return _RESPONSE_STRATEGY_PARTIAL_MSG

    # --- immediate (default): keyword-driven replies ---
    lower = message_content.lower()

    # Photos / images
    if any(kw in lower for kw in _PHOTO_KEYWORDS):
        return (
            "I've uploaded photos of the damage to the portal. "
            "Please let me know if you need additional images from different angles."
        )

    # Repair estimate
    if any(kw in lower for kw in _ESTIMATE_KEYWORDS):
        return (
            "I'll take the vehicle to a local body shop and have a written estimate "
            "ready within 2–3 business days. I'll upload it to the portal as soon as I have it."
        )

    # Police / incident report
    if any(kw in lower for kw in _POLICE_REPORT_KEYWORDS):
        return (
            "I filed a police report at the scene. "
            "I'll upload a copy of the report to the portal shortly."
        )

    # Medical records / injuries
    if any(kw in lower for kw in _MEDICAL_KEYWORDS):
        _vehicle_info = _extract_vehicle_info(claim_context)
        return (
            "I am working with my doctor to gather the relevant medical records "
            "and will submit them once available. "
            + (_vehicle_info or "")
        ).strip()

    # Contact information
    if any(kw in lower for kw in _CONTACT_KEYWORDS):
        return (
            "My contact information is on file. "
            "Please feel free to reach me by email or phone if you need to get in touch."
        )

    # Generic fallback
    return "Thank you for your message. I'll provide that information shortly."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_vehicle_info(claim_context: dict[str, Any] | None) -> str:
    """Return a short vehicle descriptor from claim_context, if available."""
    if not claim_context:
        return ""
    vehicle = claim_context.get("vehicle") or {}
    year = vehicle.get("year") or vehicle.get("vehicle_year")
    make = vehicle.get("make") or vehicle.get("vehicle_make")
    model = vehicle.get("model") or vehicle.get("vehicle_model")
    parts = [str(p) for p in (year, make, model) if p]
    if parts:
        return f"(Vehicle: {' '.join(parts)})"
    return ""
