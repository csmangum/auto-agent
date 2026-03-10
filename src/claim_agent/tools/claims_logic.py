"""Claims database search and similarity logic."""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from claim_agent.db.repository import ClaimRepository

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext
    from claim_agent.rag.embeddings import EmbeddingProvider

_log = logging.getLogger(__name__)

_embedding_provider_lock = threading.Lock()
_embedding_provider: EmbeddingProvider | None = None
_embedding_provider_failed = False


def _get_embedding_provider() -> EmbeddingProvider | None:
    """Return a lazily-initialised, cached embedding provider.

    Returns None when the provider fails to load (e.g. missing
    sentence-transformers) so callers can fall back to Jaccard.
    """
    global _embedding_provider, _embedding_provider_failed
    if _embedding_provider is not None:
        return _embedding_provider
    if _embedding_provider_failed:
        return None
    with _embedding_provider_lock:
        if _embedding_provider is not None:
            return _embedding_provider
        if _embedding_provider_failed:
            return None
        try:
            from claim_agent.rag.embeddings import get_embedding_provider

            _embedding_provider = get_embedding_provider()
        except Exception:
            _log.debug("Embedding provider unavailable; falling back to Jaccard", exc_info=True)
            _embedding_provider_failed = True
            return None
    return _embedding_provider


def search_claims_db_impl(
    vin: str,
    incident_date: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    if not vin or not isinstance(vin, str) or not vin.strip():
        return json.dumps([])
    if not incident_date or not isinstance(incident_date, str) or not incident_date.strip():
        return json.dumps([])
    repo = ctx.repo if ctx else ClaimRepository()
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


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors, returned in [0, 1]."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_jaccard_score(description_a: str, description_b: str) -> float:
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


def compute_similarity_score_impl(description_a: str, description_b: str) -> float:
    """Compute similarity (0-100) between two descriptions.

    Uses embedding cosine similarity when the embedding provider is available,
    falling back to Jaccard bag-of-words similarity otherwise.
    """
    a = description_a.strip()
    b = description_b.strip()
    if not a or not b:
        return 0.0

    provider = _get_embedding_provider()
    if provider is not None:
        try:
            vec_a = provider.embed(a)
            vec_b = provider.embed(b)
            cos = _cosine_similarity(vec_a, vec_b)
            return round(max(0.0, cos) * 100.0, 2)
        except Exception:
            _log.debug("Embedding similarity failed; falling back to Jaccard", exc_info=True)

    return compute_jaccard_score(description_a, description_b)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    score = compute_similarity_score_impl(description_a, description_b)
    return json.dumps({"similarity_score": score, "is_duplicate": score > 80.0})
