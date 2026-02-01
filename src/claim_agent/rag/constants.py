"""RAG module constants: supported states and canonical names."""

SUPPORTED_STATES = ("California", "Texas", "Florida", "New York")

DEFAULT_STATE = "California"


def normalize_state(value: str) -> str:
    """Return canonical state name (title-case) or raise ValueError if unsupported.

    Args:
        value: State name (case-insensitive).

    Returns:
        Canonical state name from SUPPORTED_STATES.

    Raises:
        ValueError: If value does not match any supported state.
    """
    if not value:
        raise ValueError("State cannot be empty")
    normalized = value.strip().title()
    if normalized not in SUPPORTED_STATES:
        raise ValueError(
            f"Unsupported state {value!r}. Supported: {', '.join(SUPPORTED_STATES)}"
        )
    return normalized
