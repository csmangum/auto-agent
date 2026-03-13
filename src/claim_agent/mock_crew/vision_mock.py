"""Mock vision analysis: derive damage assessment from claim context without API call."""

import json
from typing import Any

_SEVERITY_TOTAL_LOSS = frozenset(
    {"total", "totaled", "totalled", "destroyed", "total loss", "write-off", "writeoff"}
)
_SEVERITY_HIGH = frozenset(
    {"severe", "extensive", "major", "significant", "heavy", "critical"}
)
_SEVERITY_MEDIUM = frozenset(
    {"moderate", "medium", "substantial", "considerable"}
)

_PARTS_KEYWORDS: dict[str, frozenset[str]] = {
    "bumper": frozenset({"bumper", "bumpers"}),
    "fender": frozenset({"fender", "fenders"}),
    "door": frozenset({"door", "doors"}),
    "hood": frozenset({"hood", "hoods"}),
    "quarter panel": frozenset({"quarter panel", "quarter panels", "qtr panel"}),
    "headlight": frozenset({"headlight", "headlights"}),
    "taillight": frozenset({"taillight", "taillights", "tail light"}),
    "windshield": frozenset({"windshield", "windscreen"}),
    "grille": frozenset({"grille", "grill"}),
    "mirror": frozenset({"mirror", "side mirror"}),
    "roof": frozenset({"roof"}),
    "trunk": frozenset({"trunk", "boot"}),
}


def _infer_severity(text: str) -> str:
    """Infer severity from damage description."""
    if not text:
        return "unknown"
    lower = text.lower()
    if any(kw in lower for kw in _SEVERITY_TOTAL_LOSS):
        return "total_loss"
    if any(kw in lower for kw in _SEVERITY_HIGH):
        return "high"
    if any(kw in lower for kw in _SEVERITY_MEDIUM):
        return "medium"
    return "low"


def _infer_parts(text: str) -> list[str]:
    """Extract parts_affected from damage description."""
    if not text:
        return []
    lower = text.lower()
    parts: list[str] = []
    for part_name, keywords in _PARTS_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            parts.append(part_name)
    return parts


def _infer_consistency(
    damage_description: str | None,
    parts_affected: list[str],
) -> str:
    """Determine consistency_with_description."""
    if not damage_description:
        return "unknown"
    if not parts_affected:
        return "unknown"
    # If we inferred parts from the description, they're consistent
    return "consistent"


def analyze_damage_photo_mock(
    image_url: str,
    damage_description: str | None = None,
    claim_context: dict[str, Any] | None = None,
) -> str:
    """Return JSON damage analysis derived from claim context, no API call.

    Uses damage_description (or claim_context.damage_description) to infer
    severity, parts_affected, and consistency_with_description.
    """
    desc = damage_description
    if desc is None and claim_context:
        desc = claim_context.get("damage_description")

    severity = _infer_severity(desc or "")
    parts_affected = _infer_parts(desc or "")
    consistency = _infer_consistency(desc, parts_affected)

    notes = "Mock analysis derived from claim context (no vision API call)."
    if desc:
        notes = f"Derived from: {desc[:100]}{'...' if len(desc or '') > 100 else ''}"

    result: dict[str, Any] = {
        "severity": severity,
        "parts_affected": parts_affected,
        "consistency_with_description": consistency,
        "notes": notes,
        "error": None,
    }
    return json.dumps(result)
