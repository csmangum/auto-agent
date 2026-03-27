"""Input sanitization for claim data to prevent prompt injection and abuse."""

import json
import re
from typing import Any

from claim_agent.models.party import AuthorizationStatus, ConsentStatus, PartyType

# Maximum lengths for text fields (characters)
MAX_INCIDENT_DESCRIPTION = 5000
MAX_DAMAGE_DESCRIPTION = 3000
MAX_ACTOR_ID = 128
MAX_NOTE = 5000
MAX_POLICY_NUMBER = 64
MAX_VIN = 32
MAX_VEHICLE_MAKE = 64
MAX_VEHICLE_MODEL = 128
MAX_DENIAL_REASON = 4096
MAX_AUDIT_DETAILS = 4096
MAX_POLICYHOLDER_EVIDENCE = 8192
MAX_REOPENING_REASON = 1000
MAX_PRIOR_CLAIM_ID = 64
MAX_TASK_TITLE = 500
MAX_TASK_DESCRIPTION = 5000
MAX_RESOLUTION_NOTES = 5000
MAX_PARTY_NAME = 256
MAX_PARTY_EMAIL = 320
MAX_PARTY_PHONE = 32
MAX_PARTY_ADDRESS = 500
MAX_PARTY_ROLE = 128
MAX_PAYEE = 500

# Maximum payout amount (dollars) for reviewer-confirmed payout validation
MAX_PAYOUT = 50_000_000

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


def sanitize_actor_id(actor_id: str | None) -> str:
    """Sanitize actor_id for prompt injection before storage. Truncates and redacts patterns."""
    if actor_id is None or not isinstance(actor_id, str):
        return ""
    t = _sanitize_text(actor_id, MAX_ACTOR_ID)
    return _remove_injection_patterns(t)


def sanitize_note(note: str | None) -> str:
    """Sanitize note content for prompt injection before storage. Used for claim notes."""
    if note is None or not isinstance(note, str):
        return ""
    t = _sanitize_text(note, MAX_NOTE)
    return _remove_injection_patterns(t)


def sanitize_supplemental_damage_description(text: str | None) -> str:
    """Sanitize supplemental damage description for prompt injection before passing to LLM."""
    if text is None or not isinstance(text, str):
        return ""
    t = _sanitize_text(text, MAX_DAMAGE_DESCRIPTION)
    return _remove_injection_patterns(t)


def sanitize_denial_reason(text: str | None) -> str:
    """Sanitize denial reason for prompt injection before passing to LLM."""
    if text is None or not isinstance(text, str):
        return ""
    t = _sanitize_text(text, MAX_DENIAL_REASON)
    return _remove_injection_patterns(t)


def truncate_audit_json(obj: dict[str, Any]) -> str:
    """JSON-dump for audit storage; truncates to MAX_AUDIT_DETAILS if oversized."""
    s = json.dumps(obj)
    if len(s) <= MAX_AUDIT_DETAILS:
        return s
    return json.dumps({
        "_truncated": True,
        "original_length": len(s),
        "preview": s[:3500],
    })


def sanitize_policyholder_evidence(text: str | None) -> str | None:
    """Sanitize policyholder evidence for prompt injection before passing to LLM."""
    if text is None:
        return None
    if not isinstance(text, str):
        return None
    t = _sanitize_text(text, MAX_POLICYHOLDER_EVIDENCE)
    return _remove_injection_patterns(t) or None


def sanitize_task_title(title: str | None) -> str:
    """Sanitize task title for prompt injection before storage. Truncates to 500 chars."""
    if title is None or not isinstance(title, str):
        return ""
    t = _sanitize_text(title, MAX_TASK_TITLE)
    return _remove_injection_patterns(t)


def sanitize_task_description(description: str | None) -> str:
    """Sanitize task description for prompt injection before storage. Truncates to 5000 chars."""
    if description is None or not isinstance(description, str):
        return ""
    t = _sanitize_text(description, MAX_TASK_DESCRIPTION)
    return _remove_injection_patterns(t)


def sanitize_resolution_notes(notes: str | None) -> str:
    """Sanitize task resolution notes for prompt injection before storage. Truncates to 5000 chars."""
    if notes is None or not isinstance(notes, str):
        return ""
    t = _sanitize_text(notes, MAX_RESOLUTION_NOTES)
    return _remove_injection_patterns(t)


def sanitize_payee(payee: str | None) -> str:
    """Sanitize payee name for prompt injection before storage and audit logging.
    
    Payee data may be passed to LLMs via payment tools, included in audit logs that 
    are used in prompts, or rendered in UI contexts. This sanitization helps prevent:
    - Prompt injection attacks via payee names
    - Control character injection

    Truncates to 500 chars, removes instruction-like patterns, and normalizes
    whitespace (tabs and newlines are replaced with spaces and collapsed) since
    payee names are single-line identifiers.

    Note: This function does *not* perform HTML or UI escaping/encoding. The returned
    string must still be contextually escaped/encoded when rendered (e.g., in HTML)
    to prevent XSS and other injection vulnerabilities.
    """
    if payee is None or not isinstance(payee, str):
        return ""
    t = _sanitize_text(payee, MAX_PAYEE)
    t = re.sub(r"[\t\n\r]+", " ", t)
    t = re.sub(r" {2,}", " ", t).strip()
    return _remove_injection_patterns(t)


def _remove_injection_patterns(text: str) -> str:
    """Remove or neutralize instruction-like patterns that could manipulate the LLM."""
    if not text:
        return text
    result = text
    for pattern in INJECTION_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result


_DANGEROUS_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")


def is_safe_attachment_url(url: str) -> bool:
    """Reject javascript:, data:, vbscript:, file: and other dangerous schemes."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return not any(u.startswith(s) for s in _DANGEROUS_URL_SCHEMES)


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
        elif key == "reopening_reason":
            t = _sanitize_text(value, MAX_REOPENING_REASON)
            out[key] = _remove_injection_patterns(t)
        elif key == "prior_claim_id":
            t = _sanitize_text(value, MAX_PRIOR_CLAIM_ID)
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
        elif key == "claim_type":
            # Strip from intake; only trusted when set via DB (reviewer/supervisor paths)
            continue
        elif key == "loss_state":
            t = _sanitize_text(value, 64) if value else ""
            out[key] = t if t else None
        elif key == "attachments":
            # Sanitize attachment list: url, type (photo|pdf|estimate|other), description
            if isinstance(value, list):
                valid_types = {"photo", "pdf", "estimate", "other"}
                sanitized_attachments = []
                for item in value:
                    if isinstance(item, dict):
                        t = str(item.get("type", "other")).strip().lower()
                        if t not in valid_types:
                            t = "other"
                        a: dict[str, str | None] = {
                            "url": _remove_injection_patterns(_sanitize_text(item.get("url"), 2048)),
                            "type": t,
                            "description": _remove_injection_patterns(
                                _sanitize_text(item.get("description"), 500)
                            )
                            or None,
                        }
                        if a["url"] and is_safe_attachment_url(a["url"]):
                            sanitized_attachments.append(a)
                out[key] = sanitized_attachments
            else:
                out[key] = []
        elif key == "parties":
            # Sanitize party list: validate party_type, sanitize text fields
            if isinstance(value, list):
                valid_party_types = {pt.value for pt in PartyType}
                valid_consent = {cs.value for cs in ConsentStatus}
                valid_auth = {au.value for au in AuthorizationStatus}
                sanitized_parties = []
                for item in value:
                    if isinstance(item, dict):
                        pt = str(item.get("party_type", "")).strip().lower()
                        if pt not in valid_party_types:
                            continue
                        p: dict[str, Any] = {
                            "party_type": pt,
                            "name": _remove_injection_patterns(
                                _sanitize_text(item.get("name"), MAX_PARTY_NAME)
                            ) or None,
                            "email": _remove_injection_patterns(
                                _sanitize_text(item.get("email"), MAX_PARTY_EMAIL)
                            ) or None,
                            "phone": _remove_injection_patterns(
                                _sanitize_text(item.get("phone"), MAX_PARTY_PHONE)
                            ) or None,
                            "address": _remove_injection_patterns(
                                _sanitize_text(item.get("address"), MAX_PARTY_ADDRESS)
                            ) or None,
                            "role": _remove_injection_patterns(
                                _sanitize_text(item.get("role"), MAX_PARTY_ROLE)
                            ) or None,
                            "consent_status": "pending",
                            "authorization_status": "pending",
                        }
                        cs = str(item.get("consent_status", "pending")).strip().lower()
                        if cs in valid_consent:
                            p["consent_status"] = cs
                        au = str(item.get("authorization_status", "pending")).strip().lower()
                        if au in valid_auth:
                            p["authorization_status"] = au
                        sanitized_parties.append(p)
                out[key] = sanitized_parties
            else:
                out[key] = []
        else:
            if isinstance(value, str):
                t = _sanitize_text(value, MAX_INCIDENT_DESCRIPTION)
                out[key] = _remove_injection_patterns(t)
            else:
                out[key] = value
    return out
