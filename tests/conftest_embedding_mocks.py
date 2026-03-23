"""Replace heavy sentence-transformers with deterministic lexical embeddings in unit tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from claim_agent.rag.embeddings import EmbeddingProvider


class LexicalHashEmbedding(EmbeddingProvider):
    """Pseudo-embeddings from word multiset (L2-normalized bag-of-hashes).

    Cosine similarity correlates with lexical overlap, so RAG search and
    similarity tests stay meaningful without loading torch/transformers.
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
            h = hash(w) % self._dim
            v[h] += 1.0
        n = np.linalg.norm(v)
        if n >= 1e-9:
            v = v / n
        return v


def _is_integration_e2e_or_load(request: pytest.FixtureRequest) -> bool:
    for m in request.node.iter_markers():
        if m.name in ("integration", "e2e", "load"):
            return True
    path_s = str(request.node.path)
    return "/integration/" in path_s or "/e2e/" in path_s or "/load/" in path_s


@pytest.fixture(autouse=True)
def _mock_embedding_provider_for_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
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
    rag_cache = tmp_path / "rag_cache"
    rag_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAIM_AGENT_CACHE_DIR", str(rag_cache))

    with retriever_mod._retriever_lock:
        retriever_mod._global_retriever = None

    import claim_agent.tools.rag_tools as rag_tools_mod

    rag_tools_mod._retriever = None

    import claim_agent.skills as skills_mod

    with skills_mod._rag_provider_lock:
        skills_mod._rag_provider = None

    import claim_agent.tools.claims_logic as claims_logic_mod

    monkeypatch.setattr(claims_logic_mod, "_embedding_provider", fake)
    monkeypatch.setattr(claims_logic_mod, "_embedding_provider_failed", False)
