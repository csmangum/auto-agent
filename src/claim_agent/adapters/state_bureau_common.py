"""Shared helpers for state bureau fraud filing adapters."""

from __future__ import annotations

STATE_NAME_TO_CODE: dict[str, str] = {
    "california": "CA",
    "texas": "TX",
    "florida": "FL",
    "new york": "NY",
    "georgia": "GA",
}


def normalize_state_name_and_code(state: str) -> tuple[str, str]:
    """Return canonical state display name and two-letter code fallback."""
    state_norm = (state or "California").strip() or "California"
    state_code = STATE_NAME_TO_CODE.get(
        state_norm.lower(),
        state_norm[:2].upper() if len(state_norm) >= 2 else state_norm.upper(),
    )
    return state_norm, state_code
