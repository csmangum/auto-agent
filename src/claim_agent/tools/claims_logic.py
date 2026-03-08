"""Claims database search and similarity logic."""

import json

from claim_agent.db.repository import ClaimRepository


def search_claims_db_impl(
    vin: str,
    incident_date: str,
    *,
    repo: ClaimRepository | None = None,
) -> str:
    if not vin or not isinstance(vin, str) or not vin.strip():
        return json.dumps([])
    if not incident_date or not isinstance(incident_date, str) or not incident_date.strip():
        return json.dumps([])
    repo = repo or ClaimRepository()
    matches = repo.search_claims(vin=vin.strip(), incident_date=incident_date.strip())
    out = [
        {
            "claim_id": c.get("id"),
            "vin": c.get("vin"),
            "incident_date": c.get("incident_date"),
            "incident_description": c.get("incident_description", ""),
        }
        for c in matches
    ]
    return json.dumps(out)


def compute_similarity_score_impl(description_a: str, description_b: str) -> float:
    """Compute Jaccard similarity (0-100) between two descriptions."""
    a = description_a.lower().strip()
    b = description_b.lower().strip()
    if not a or not b:
        return 0.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return round((intersection / union) * 100.0, 2)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    score = compute_similarity_score_impl(description_a, description_b)
    return json.dumps({"similarity_score": score, "is_duplicate": score > 80.0})
