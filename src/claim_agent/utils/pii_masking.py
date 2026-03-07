"""PII masking for logs and metrics.

Masks policy_number, VIN, and optionally claimant names in log output
to comply with data protection requirements. Format: mask middle characters
(e.g. POL***001, 1HG***3456).
"""

import re
from typing import Any


def mask_policy_number(value: str | None) -> str:
    """Mask policy number, preserving first 3 and last 3 characters.

    Examples:
        POL-12345-001 -> POL***001
        ABC123 -> ABC***
        X -> *
    """
    if not value or not isinstance(value, str):
        return "***"
    s = value.strip()
    if len(s) <= 3:
        return "*" * min(len(s), 3) if s else "***"
    if len(s) <= 6:
        return f"{s[:3]}***"
    # Preserve first 3 and last 3 for longer values
    return f"{s[:3]}***{s[-3:]}"


def mask_vin(value: str | None) -> str:
    """Mask VIN (17 chars), preserving first 3 and last 4 characters.

    VIN format: 1HGCM82633A123456 (17 alphanumeric)
    Example: 1HGCM82633A123456 -> 1HG***3456
    """
    if not value or not isinstance(value, str):
        return "***"
    s = value.strip().upper()
    if len(s) <= 7:
        return "*" * min(len(s), 3) if s else "***"
    # Preserve first 3 and last 4 (typical VIN structure)
    return f"{s[:3]}***{s[-4:]}"


def mask_claimant_name(value: str | None) -> str:
    """Mask claimant/person name, preserving the first letter of each part.

    Example: John Smith -> J*** S***
    """
    if not value or not isinstance(value, str):
        return "***"
    s = value.strip()
    if not s:
        return "***"
    parts = s.split()
    if len(parts) == 1:
        if len(parts[0]) <= 2:
            return "*" * len(parts[0])
        return f"{parts[0][0]}***"
    masked = []
    for part in parts:
        if len(part) <= 1:
            masked.append("*")
        else:
            masked.append(f"{part[0]}***")
    return " ".join(masked)


def mask_value(key: str, value: Any) -> Any:
    """Mask a value based on its key (policy_number, vin, claimant_name, etc.)."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    key_lower = key.lower()
    if "policy" in key_lower or key_lower == "policy_number":
        return mask_policy_number(value)
    if key_lower == "vin":
        return mask_vin(value)
    if "name" in key_lower or "claimant" in key_lower:
        return mask_claimant_name(value)
    return value


# Keys that identify PII fields (exact or substring match)
_DEFAULT_PII_KEYS = {"policy_number", "vin", "policy", "claimant_name", "claimant"}


def _is_pii_key(key_lower: str, keys_to_mask: set[str]) -> bool:
    """True if key should be treated as PII (exact match or contains policy/claimant/name, or vin)."""
    if key_lower in keys_to_mask:
        return True
    return "policy" in key_lower or "claimant" in key_lower or "name" in key_lower or key_lower == "vin"


def mask_dict(data: dict[str, Any], keys_to_mask: set[str] | None = None) -> dict[str, Any]:
    """Recursively mask PII fields in a dict.

    Args:
        data: Dict that may contain PII
        keys_to_mask: Optional set of keys to mask. Default: policy_number, vin, and name-like keys.
    """
    mask_keys = keys_to_mask or _DEFAULT_PII_KEYS

    result: dict[str, Any] = {}
    for k, v in data.items():
        k_lower = k.lower()
        if _is_pii_key(k_lower, mask_keys):
            result[k] = mask_value(k, v)
        elif isinstance(v, dict):
            result[k] = mask_dict(v, keys_to_mask)
        elif isinstance(v, list):
            result[k] = [
                mask_dict(item, keys_to_mask) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# VIN pattern: 17 characters, excluding I, O, Q (standard VIN alphabet)
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{3})[A-HJ-NPR-Z0-9]{10}([A-HJ-NPR-Z0-9]{4})\b")

# Policy number-like: at least 7 chars, first 3 and last 3 preserved; middle must contain digit or hyphen
_POLICY_RE = re.compile(
    r"\b([A-Za-z0-9]{3})(?=[-A-Za-z0-9]*[-0-9][-A-Za-z0-9]*)([-A-Za-z0-9]+)([A-Za-z0-9]{3})\b"
)


def mask_text(text: str) -> str:
    """Mask PII patterns (VINs, policy numbers) found within a free-text string.

    Replaces VIN-like 17-character sequences and policy-number-like sequences
    with masked forms. Example: "VIN 1HGCM82633A123456" -> "VIN 1HG***3456";
    "policy POL-12345-001" -> "policy POL***001".
    """
    out = _VIN_RE.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)
    out = _POLICY_RE.sub(lambda m: f"{m.group(1)}***{m.group(3)}", out)
    return out
