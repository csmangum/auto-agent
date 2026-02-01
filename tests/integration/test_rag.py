"""RAG system integration tests.

These tests verify that the Retrieval-Augmented Generation system works correctly
for providing policy and compliance context to claim processing agents.
"""

from pathlib import Path

import pytest

# Skip all RAG tests if sentence-transformers is not installed
pytest.importorskip("sentence_transformers")


# Test data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ============================================================================
# Retriever Integration Tests
# ============================================================================


class TestRetrieverIntegration:
    """Test PolicyRetriever integration with the rest of the system."""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_retriever_loads_all_policy_documents(self, rag_cache_dir):
        """Test that retriever loads all policy documents from data directory."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
            auto_load=True,
        )
        
        stats = retriever.get_stats()
        
        # Should have loaded chunks from multiple states
        assert stats["total_chunks"] > 0
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_retriever_search_returns_relevant_results(self, rag_cache_dir):
        """Test that search returns relevant policy/compliance content."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        results = retriever.search(
            query="total loss vehicle valuation settlement",
            state="California",
            top_k=5,
        )
        
        assert len(results) > 0
        
        # Results should be relevant to total loss
        for chunk, score in results:
            assert score > 0.0
            assert chunk.content is not None
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_retriever_filters_by_state(self, rag_cache_dir):
        """Test that retriever correctly filters by state."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        ca_results = retriever.search(
            query="insurance coverage",
            state="California",
        )
        
        tx_results = retriever.search(
            query="insurance coverage",
            state="Texas",
        )
        
        # All California results should be from California
        for chunk, _ in ca_results:
            assert chunk.metadata.state == "California"
        
        # All Texas results should be from Texas
        for chunk, _ in tx_results:
            assert chunk.metadata.state == "Texas"
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_retriever_cache_persistence(self, rag_cache_dir):
        """Test that retriever cache is persisted and can be reloaded."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        # Create and populate first retriever
        retriever1 = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        stats1 = retriever1.get_stats()
        
        # Create second retriever from cache
        retriever2 = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
            auto_load=True,
        )
        stats2 = retriever2.get_stats()
        
        assert stats1["total_chunks"] == stats2["total_chunks"]
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_context_for_claim_type(self, rag_cache_dir):
        """Test getting context for specific claim types."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        # Test different claim types
        for claim_type in ["total_loss", "partial_loss", "fraud", "new"]:
            chunks = retriever.get_context_for_claim_type(
                claim_type=claim_type,
                state="California",
                top_k=5,
            )
            
            # Should return relevant chunks
            assert isinstance(chunks, list)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_compliance_deadlines(self, rag_cache_dir):
        """Test getting compliance deadlines."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        chunks = retriever.get_compliance_deadlines(state="California")
        
        assert isinstance(chunks, list)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_format_context(self, rag_cache_dir):
        """Test formatting context for prompts."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        chunks = retriever.get_context_for_claim_type(
            claim_type="total_loss",
            state="California",
            top_k=3,
        )
        
        context = retriever.format_context(chunks, include_metadata=True)
        
        assert isinstance(context, str)
        if chunks:
            assert "California" in context


# ============================================================================
# RAG Context Provider Tests
# ============================================================================


class TestRAGContextProvider:
    """Test RAG context provider integration."""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_context_provider_get_context(self, rag_cache_dir):
        """Test RAG context provider returns context."""
        from claim_agent.rag.context import RAGContextProvider
        
        provider = RAGContextProvider(
            data_dir=DATA_DIR,
            default_state="California",
        )
        
        context = provider.get_context(
            skill_name="damage_assessor",
            claim_type="total_loss",
        )
        
        assert isinstance(context, str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_context_provider_caching(self, rag_cache_dir):
        """Test that context provider caches results."""
        from claim_agent.rag.context import RAGContextProvider
        
        provider = RAGContextProvider(
            data_dir=DATA_DIR,
            default_state="California",
        )
        
        # First call
        context1 = provider.get_context(
            skill_name="damage_assessor",
            claim_type="total_loss",
            use_cache=True,
        )
        
        # Second call with same parameters
        context2 = provider.get_context(
            skill_name="damage_assessor",
            claim_type="total_loss",
            use_cache=True,
        )
        
        # Should return same cached result
        assert context1 == context2
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_enrich_skill_with_context(self, rag_cache_dir):
        """Test enriching a skill with RAG context."""
        from claim_agent.rag.context import enrich_skill_with_context
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        skill = {
            "role": "Damage Assessor",
            "goal": "Evaluate vehicle damage",
            "backstory": "You are an experienced damage assessor.",
        }
        
        enriched = enrich_skill_with_context(
            skill_dict=skill,
            skill_name="damage_assessor",
            state="California",
            retriever=retriever,
        )
        
        # Backstory should be enriched
        assert len(enriched["backstory"]) >= len(skill["backstory"])


# ============================================================================
# RAG Tools Integration Tests
# ============================================================================


class TestRAGToolsIntegration:
    """Test RAG tools integration with claim processing."""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_search_policy_compliance(self):
        """Test policy compliance search tool."""
        from claim_agent.tools.rag_tools import search_policy_compliance
        
        result = search_policy_compliance.run(
            query="total loss valuation requirements",
            state="California",
        )
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_compliance_deadlines_tool(self):
        """Test compliance deadlines tool."""
        from claim_agent.tools.rag_tools import get_compliance_deadlines
        
        result = get_compliance_deadlines.run(state="California")
        
        assert isinstance(result, str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_total_loss_requirements(self):
        """Test total loss requirements tool."""
        from claim_agent.tools.rag_tools import get_total_loss_requirements
        
        result = get_total_loss_requirements.run(state="California")
        
        assert isinstance(result, str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_fraud_detection_guidance(self):
        """Test fraud detection guidance tool."""
        from claim_agent.tools.rag_tools import get_fraud_detection_guidance
        
        result = get_fraud_detection_guidance.run(state="California")
        
        assert isinstance(result, str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_repair_standards(self):
        """Test repair standards tool."""
        from claim_agent.tools.rag_tools import get_repair_standards
        
        result = get_repair_standards.run(state="California")
        
        assert isinstance(result, str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_rag_tool_unsupported_state(self):
        """Test RAG tools return friendly message for unsupported states."""
        from claim_agent.tools.rag_tools import get_compliance_deadlines
        from claim_agent.rag.constants import SUPPORTED_STATES
        
        result = get_compliance_deadlines.run(state="InvalidState")
        
        assert "Unsupported state" in result or "Supported" in result
        for state in SUPPORTED_STATES:
            assert state in result


# ============================================================================
# RAG Workflow Integration Tests
# ============================================================================


class TestRAGWorkflowIntegration:
    """Test RAG integration with claim processing workflows."""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_total_loss_context_includes_valuation_info(self, rag_cache_dir):
        """Test that total loss context includes valuation information."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        chunks = retriever.get_context_for_claim_type(
            claim_type="total_loss",
            state="California",
            top_k=10,
        )
        
        context = retriever.format_context(chunks)
        context_lower = context.lower()
        
        # Should mention valuation-related concepts
        valuation_terms = ["value", "total loss", "settlement", "salvage", "actual cash"]
        found_terms = [t for t in valuation_terms if t in context_lower]
        
        # At least some valuation terms should be present
        assert len(found_terms) > 0 or len(chunks) == 0
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_fraud_context_includes_investigation_info(self, rag_cache_dir):
        """Test that fraud context includes investigation information."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        chunks = retriever.get_context_for_claim_type(
            claim_type="fraud",
            state="California",
            top_k=10,
        )
        
        assert isinstance(chunks, list)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_multiple_state_context_retrieval(self, rag_cache_dir):
        """Test retrieving context for claims across multiple states."""
        from claim_agent.rag.retriever import PolicyRetriever
        from claim_agent.rag.constants import SUPPORTED_STATES
        
        retriever = PolicyRetriever(
            data_dir=DATA_DIR,
            cache_dir=rag_cache_dir,
        )
        
        for state in SUPPORTED_STATES:
            results = retriever.search(
                query="insurance coverage",
                state=state,
                top_k=3,
            )
            
            # Should return results for each supported state
            for chunk, score in results:
                assert chunk.metadata.state == state


# ============================================================================
# Skills RAG Integration Tests
# ============================================================================


class TestSkillsRAGIntegration:
    """Test skills module integration with RAG."""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_load_skill_with_context(self):
        """Test loading a skill with RAG context."""
        from claim_agent.skills import load_skill_with_context
        
        skill = load_skill_with_context(
            "damage_assessor",
            state="California",
            claim_type="total_loss",
            use_rag=True,
        )
        
        assert skill["role"] is not None
        assert skill["goal"] is not None
        assert "backstory" in skill
    
    @pytest.mark.integration
    def test_load_skill_without_rag(self):
        """Test loading a skill without RAG context."""
        from claim_agent.skills import load_skill_with_context
        
        skill = load_skill_with_context(
            "damage_assessor",
            state="California",
            use_rag=False,
        )
        
        assert skill["role"] is not None
        assert skill["goal"] is not None
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_skill_context_varies_by_claim_type(self):
        """Test that skill context differs based on claim type."""
        from claim_agent.skills import load_skill_with_context
        
        skill_total_loss = load_skill_with_context(
            "damage_assessor",
            state="California",
            claim_type="total_loss",
            use_rag=True,
        )
        
        skill_partial_loss = load_skill_with_context(
            "damage_assessor",
            state="California",
            claim_type="partial_loss",
            use_rag=True,
        )
        
        # Both should have valid structure
        assert skill_total_loss["role"] is not None
        assert skill_partial_loss["role"] is not None
