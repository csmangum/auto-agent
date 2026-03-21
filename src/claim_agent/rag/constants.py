"""RAG module constants: supported states and canonical names."""

SUPPORTED_STATES = (
    "California", "Texas", "Florida", "New York", "Georgia",
    "New Jersey", "Pennsylvania", "Illinois",
)

DEFAULT_STATE = "California"

_STATE_ABBREV_TO_CANONICAL: dict[str, str] = {
    "CA": "California",
    "TX": "Texas",
    "FL": "Florida",
    "NY": "New York",
    "GA": "Georgia",
    "NJ": "New Jersey",
    "PA": "Pennsylvania",
    "IL": "Illinois",
}


def normalize_state(value: str) -> str:
    """Return canonical state name (title-case) or raise ValueError if unsupported.

    Accepts full state names (case-insensitive) or common abbreviations (e.g. CA, TX, NJ, PA, IL).

    Args:
        value: State name or abbreviation.

    Returns:
        Canonical state name from SUPPORTED_STATES.

    Raises:
        ValueError: If value does not match any supported state.
    """
    if not value:
        raise ValueError("State cannot be empty")
    stripped = value.strip()
    upper = stripped.upper()
    if upper in _STATE_ABBREV_TO_CANONICAL:
        return _STATE_ABBREV_TO_CANONICAL[upper]
    normalized = stripped.title()
    if normalized not in SUPPORTED_STATES:
        raise ValueError(
            f"Unsupported state {value!r}. Supported: {', '.join(SUPPORTED_STATES)}"
        )
    return normalized
