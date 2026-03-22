"""Focused tests for fraud guidance RAG tool query behavior."""

from claim_agent.tools import rag_tools


def test_fraud_guidance_query_includes_nicb_niss_terms(monkeypatch):
    """Fraud guidance tool query should include NICB/NISS terms for retrieval."""

    class _FakeRetriever:
        def __init__(self):
            self.query = None

        def search(self, **kwargs):
            self.query = kwargs.get("query")
            return []

    fake_retriever = _FakeRetriever()
    monkeypatch.setattr(rag_tools, "_get_retriever", lambda: fake_retriever)

    result = rag_tools.get_fraud_detection_guidance.run(state="California")

    assert result == "No fraud guidance found for California."
    assert fake_retriever.query is not None
    assert "NICB" in fake_retriever.query
    assert "NISS" in fake_retriever.query
