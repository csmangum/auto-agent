"""California and multi-state auto insurance compliance lookup logic."""

import json
from typing import Any

from claim_agent.data.loader import load_state_compliance
from claim_agent.rag.constants import SUPPORTED_STATES, normalize_state


def _json_contains_query(obj: object, query: str) -> bool:
    """Return True if any string value in obj (recursively) contains query (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return False
    if isinstance(obj, str):
        return q in obj.lower()
    if isinstance(obj, dict):
        return any(_json_contains_query(v, query) for v in obj.values())
    if isinstance(obj, list):
        return any(_json_contains_query(v, query) for v in obj)
    return False


def _gather_matches(
    data: dict[str, Any], query: str, section_key: str, matches: list[dict[str, Any]]
) -> None:
    """Recursively gather dicts/lists that contain the query."""
    if not _json_contains_query(data, query):
        return
    list_keys = {"provisions", "deadlines", "disclosures", "prohibited_practices", "key_provisions", "requirements", "limitations", "scenarios", "remedies", "penalties", "consumer_services", "tolling_provisions", "proof_methods"}
    for key, value in data.items():
        if key == "metadata":
            continue
        if key in list_keys and isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict) and _json_contains_query(item, query):
                    matches.append({"section": section_key, "subsection": key, "item": item})
        elif isinstance(value, dict):
            _gather_matches(value, query, section_key or key, matches)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                if _json_contains_query(item, query):
                    matches.append({"section": section_key, "item": item})


def search_california_compliance_impl(query: str) -> str:
    """Search California auto compliance data by keyword. Empty query returns section summary."""
    return search_state_compliance_impl(query, "California")


def search_state_compliance_impl(query: str, state: str) -> str:
    """Search state auto compliance data by keyword. Empty query returns section summary.

    Args:
        query: Search term (e.g. 'total loss', 'deadline', 'disclosure').
        state: State jurisdiction - California, Texas, Florida, or New York.

    Returns:
        JSON with match_count and matches (or section summary if query is empty).
    """
    try:
        normalized = normalize_state(state.strip())
    except ValueError:
        return json.dumps({
            "error": f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}.",
            "match_count": 0,
            "matches": [],
        })
    data = load_state_compliance(normalized)
    if not data:
        return json.dumps({
            "error": f"Compliance data not available for {normalized}",
            "match_count": 0,
            "matches": [],
        })
    query = (query or "").strip()
    if not query:
        summary = {
            "metadata": data.get("metadata", {}),
            "sections": [k for k in data.keys() if k != "metadata"],
        }
        return json.dumps(summary)
    matches: list = []
    for section_key, section_value in data.items():
        if section_key == "metadata":
            continue
        if isinstance(section_value, dict):
            _gather_matches(section_value, query, section_key, matches)
        elif _json_contains_query(section_value, query):
            matches.append({"section": section_key, "content": section_value})
    return json.dumps({"query": query, "match_count": len(matches), "matches": matches})
