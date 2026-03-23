"""Replace heavy sentence-transformers with deterministic lexical embeddings in unit tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from claim_agent.rag.embeddings import EmbeddingProvider


class LexicalHashEmbedding(EmbeddingProvider):
    """Pseudo-embeddings from word multiset (L2-normalized bag-of-hashes).

    Cosine similarity correlates with lexical overlap, so RAG search and
    similarity tests stay meaningful without loading torch/transformers.

    Uses MD5 (via hashlib) instead of Python's built-in hash() so the bucket
    index is stable across interpreter runs regardless of PYTHONHASHSEED.
    """

    model_name = "test-lexical-hash"
    _dim = 384

    def embed(self, text: str) -> np.ndarray:
        return self._vec_for_text(text)

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return np.stack([self._vec_for_text(t) for t in texts])

    @property
    def dimension(self) -> int:
        return self._dim

    def _vec_for_text(self, text: str) -> np.ndarray:
        normalized = "".join(c.lower() if c.isalnum() else " " for c in text)
        words = [w for w in normalized.split() if w]
        v = np.zeros(self._dim, dtype=np.float64)
        for w in words:
            h = int(hashlib.md5(w.encode()).hexdigest(), 16) % self._dim
            v[h] += 1.0
        n = np.linalg.norm(v)
        if n >= 1e-9:
            v = v / n
        return v


def _is_integration_e2e_or_load(request: pytest.FixtureRequest) -> bool:
    for m in request.node.iter_markers():
        if m.name in ("integration", "e2e", "load"):
            return True
    node_path = getattr(request.node, "path", None)
    if node_path is None:
        return False
    parts = set(Path(node_path).parts)
    return any(name in parts for name in ("integration", "e2e", "load"))


@pytest.fixture(autouse=True)
def _mock_embedding_provider_for_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Use fast lexical fake for all tests except integration / e2e / load."""
    if _is_integration_e2e_or_load(request):
        return

    fake = LexicalHashEmbedding()

    import claim_agent.rag.embeddings as embeddings_mod
    import claim_agent.rag.retriever as retriever_mod
    import claim_agent.rag.vector_store as vector_store_mod

    monkeypatch.setattr(embeddings_mod, "get_embedding_provider", lambda *a, **kw: fake)
    monkeypatch.setattr(vector_store_mod, "get_embedding_provider", lambda *a, **kw: fake)
    monkeypatch.setattr(retriever_mod, "get_embedding_provider", lambda *a, **kw: fake)

    # Isolate on-disk RAG cache: ~/.cache may hold vectors from a real model; fake query
    # embeddings must match indexed vectors or semantic search returns nothing.
    # Request tmp_path lazily so pytest only creates a temp dir for unit tests.
    tmp_path: Path = request.getfixturevalue("tmp_path")
    rag_cache = tmp_path / "rag_cache"
    rag_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAIM_AGENT_CACHE_DIR", str(rag_cache))

    monkeypatch.setattr(retriever_mod, "_global_retriever", None)

    import claim_agent.tools.rag_tools as rag_tools_mod

    monkeypatch.setattr(rag_tools_mod, "_retriever", None)

    import claim_agent.skills as skills_mod

    monkeypatch.setattr(skills_mod, "_rag_provider", None)

    import claim_agent.tools.claims_logic as claims_logic_mod

    monkeypatch.setattr(claims_logic_mod, "_embedding_provider", fake)
    monkeypatch.setattr(claims_logic_mod, "_embedding_provider_failed", False)
