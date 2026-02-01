"""Input sanitization for claim data to prevent prompt injection and abuse."""

import re
from typing import Any

# Maximum lengths for text fields (characters)
MAX_INCIDENT_DESCRIPTION = 5000
MAX_DAMAGE_DESCRIPTION = 3000
MAX_POLICY_NUMBER = 64
MAX_VIN = 32
MAX_VEHICLE_MAKE = 64
MAX_VEHICLE_MODEL = 128

# Patterns that may indicate prompt injection attempts
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|above|prior)", re.I),
    re.compile(r"forget\s+(?:everything|all)\s+(?:you\s+)?(?:know|learned)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"system\s*:\s*", re.I),
    re.compile(r"<\|[a-z_]+\|>", re.I),  # special tokens
]


def _sanitize_text(text: str | None, max_length: int) -> str:
    """Strip control characters and truncate to max_length."""
    if text is None or not isinstance(text, str):
        return ""
    # Remove control characters (0x00-0x1F except tab/newline/carriage return)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned = cleaned.strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _remove_injection_patterns(text: str) -> str:
    """Remove or neutralize instruction-like patterns that could manipulate the LLM."""
    if not text:
        return text
    result = text
    for pattern in INJECTION_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result


def sanitize_claim_data(claim_data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize claim input to limit prompt injection and abuse.

    - Truncates text fields to safe lengths
    - Strips control characters
    - Removes instruction-like patterns from free-text fields
    - Preserves numeric and non-string fields as-is (validated elsewhere)

    Returns a new dict; does not mutate the input.
    """
    if not claim_data or not isinstance(claim_data, dict):
        return claim_data or {}

    out: dict[str, Any] = {}
    for key, value in claim_data.items():
        if key == "incident_description":
            t = _sanitize_text(value, MAX_INCIDENT_DESCRIPTION)
            out[key] = _remove_injection_patterns(t)
        elif key == "damage_description":
            t = _sanitize_text(value, MAX_DAMAGE_DESCRIPTION)
            out[key] = _remove_injection_patterns(t)
        elif key == "policy_number":
            out[key] = _sanitize_text(value, MAX_POLICY_NUMBER)
        elif key == "vin":
            out[key] = _sanitize_text(value, MAX_VIN)
        elif key == "vehicle_make":
            out[key] = _sanitize_text(value, MAX_VEHICLE_MAKE)
        elif key == "vehicle_model":
            out[key] = _sanitize_text(value, MAX_VEHICLE_MODEL)
        elif key in ("vehicle_year", "estimated_damage", "claim_id", "incident_date"):
            # Pass through; validated by Pydantic or business logic
            out[key] = value
        else:
            out[key] = value
    return out
