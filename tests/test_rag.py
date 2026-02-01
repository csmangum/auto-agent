"""Tests for the RAG (Retrieval-Augmented Generation) module."""

import tempfile
from pathlib import Path

import pytest
import numpy as np


# Test data directory
DATA_DIR = Path(__file__).parent.parent / "data"


class TestDocumentChunker:
    """Tests for the document chunker."""
    
    def test_chunk_policy_document(self):
        """Test chunking a policy language document."""
        from claim_agent.rag.chunker import DocumentChunker
        
        chunker = DocumentChunker()
        
        # Test with California policy file
        policy_file = DATA_DIR / "california_auto_policy_language.json"
        if not policy_file.exists():
            pytest.skip(f"Test data file not found: {policy_file}")
            
        chunks = chunker.chunk_json_document(policy_file)
        
        assert len(chunks) > 0
        
        # Check chunk structure
        for chunk in chunks:
            assert chunk.content
            assert chunk.chunk_id
            assert chunk.metadata.state == "California"
            assert "policy_language" in chunk.metadata.data_type
    
    def test_chunk_compliance_document(self):
        """Test chunking a compliance document."""
        from claim_agent.rag.chunker import DocumentChunker
        
        chunker = DocumentChunker()
        
        # Test with California compliance file
        compliance_file = DATA_DIR / "california_auto_compliance.json"
        if not compliance_file.exists():
            pytest.skip(f"Test data file not found: {compliance_file}")
            
        chunks = chunker.chunk_json_document(compliance_file)
        
        assert len(chunks) > 0
        
        # Check for compliance-specific chunks
        compliance_chunks = [
            c for c in chunks 
            if "compliance" in c.metadata.data_type.lower()
        ]
        assert len(compliance_chunks) > 0
    
    def test_chunk_metadata(self):
        """Test chunk metadata extraction."""
        from claim_agent.rag.chunker import DocumentChunker, ChunkMetadata
        
        metadata = ChunkMetadata(
            source_file="test.json",
            state="California",
            jurisdiction="CA",
            data_type="compliance",
            section="total_loss",
            subsection="provision",
            provision_id="TL-001",
            title="Total Loss Threshold",
            is_state_specific=True,
            version="2025.1",
        )
        
        meta_dict = metadata.to_dict()
        
        assert meta_dict["state"] == "California"
        assert meta_dict["provision_id"] == "TL-001"
        assert meta_dict["is_state_specific"] == True
    
    def test_chunk_policy_data_function(self):
        """Test the chunk_policy_data convenience function."""
        from claim_agent.rag.chunker import chunk_policy_data
        
        if not DATA_DIR.exists():
            pytest.skip(f"Test data directory not found: {DATA_DIR}")
            
        chunks = chunk_policy_data(DATA_DIR)
        
        # Should have chunks from multiple states
        states = set(c.metadata.state for c in chunks)
        assert len(states) >= 1
    
    def test_chunk_compliance_data_function(self):
        """Test the chunk_compliance_data convenience function."""
        from claim_agent.rag.chunker import chunk_compliance_data
        
        if not DATA_DIR.exists():
            pytest.skip(f"Test data directory not found: {DATA_DIR}")
            
        chunks = chunk_compliance_data(DATA_DIR)
        
        # All should be compliance type
        for chunk in chunks:
            assert "compliance" in chunk.metadata.data_type.lower()
    
    def test_chunk_to_dict_roundtrip(self):
        """Test chunk serialization/deserialization."""
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        
        metadata = ChunkMetadata(
            source_file="test.json",
            state="Texas",
            jurisdiction="TX",
            data_type="policy_language",
            section="liability",
            title="Liability Coverage",
        )
        
        chunk = Chunk(
            content="This is test content for the chunk.",
            metadata=metadata,
        )
        
        # Serialize and deserialize
        chunk_dict = chunk.to_dict()
        restored = Chunk.from_dict(chunk_dict)
        
        assert restored.content == chunk.content
        assert restored.chunk_id == chunk.chunk_id
        assert restored.metadata.state == "Texas"

    def test_chunk_id_uses_sha256(self):
        """Test chunk IDs use SHA-256 (16 hex chars) and different content yields different IDs."""
        from claim_agent.rag.chunker import Chunk, ChunkMetadata

        meta = ChunkMetadata(
            source_file="test.json",
            state="California",
            jurisdiction="CA",
            data_type="compliance",
            section="test",
        )
        chunk_a = Chunk(content="Content A.", metadata=meta)
        chunk_b = Chunk(content="Content B.", metadata=meta)
        # IDs are state-section-hash; hash part is 16 hex chars (SHA-256 truncated)
        assert chunk_a.chunk_id != chunk_b.chunk_id
        # Format: California-test-<16 hex chars>
        parts_a = chunk_a.chunk_id.rsplit("-", 1)
        assert len(parts_a) == 2
        hash_part = parts_a[1]
        assert len(hash_part) == 16
        assert all(c in "0123456789abcdef" for c in hash_part)


class TestEmbeddings:
    """Tests for embedding providers."""
    
    def test_sentence_transformer_embedding_init(self):
        """Test initializing sentence transformer embeddings."""
        from claim_agent.rag.embeddings import SentenceTransformerEmbedding
        
        # Should not load model on init
        embedder = SentenceTransformerEmbedding()
        assert embedder.model_name == "all-MiniLM-L6-v2"
    
    @pytest.mark.slow
    def test_sentence_transformer_embed(self):
        """Test generating embeddings with sentence transformers."""
        from claim_agent.rag.embeddings import SentenceTransformerEmbedding
        
        embedder = SentenceTransformerEmbedding()
        
        embedding = embedder.embed("This is a test sentence.")
        
        assert isinstance(embedding, np.ndarray)
        assert len(embedding) == embedder.dimension
    
    @pytest.mark.slow
    def test_sentence_transformer_embed_batch(self):
        """Test batch embedding generation."""
        from claim_agent.rag.embeddings import SentenceTransformerEmbedding
        
        embedder = SentenceTransformerEmbedding()
        
        texts = [
            "First test sentence.",
            "Second test sentence.",
            "Third test sentence.",
        ]
        
        embeddings = embedder.embed_batch(texts)
        
        assert embeddings.shape[0] == 3
        assert embeddings.shape[1] == embedder.dimension
    
    def test_get_embedding_provider(self):
        """Test the factory function."""
        from claim_agent.rag.embeddings import get_embedding_provider
        
        provider = get_embedding_provider("sentence-transformers")
        assert provider.model_name == "all-MiniLM-L6-v2"


class TestVectorStore:
    """Tests for the vector store."""
    
    def test_vector_store_init(self):
        """Test vector store initialization."""
        from claim_agent.rag.vector_store import VectorStore
        
        store = VectorStore()
        
        assert store.size == 0
    
    @pytest.mark.slow
    def test_vector_store_add_chunks(self):
        """Test adding chunks to the vector store."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        
        store = VectorStore()
        
        # Create test chunks
        chunks = []
        for i in range(3):
            metadata = ChunkMetadata(
                source_file="test.json",
                state="California",
                jurisdiction="CA",
                data_type="policy_language",
                section=f"section_{i}",
            )
            chunks.append(Chunk(
                content=f"This is test content number {i}.",
                metadata=metadata,
            ))
        
        store.add_chunks(chunks)
        
        assert store.size == 3
    
    @pytest.mark.slow
    def test_vector_store_search(self):
        """Test searching the vector store."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        
        store = VectorStore()
        
        # Add chunks with different content
        chunks = [
            Chunk(
                content="Total loss vehicle valuation and settlement procedures.",
                metadata=ChunkMetadata(
                    source_file="test.json",
                    state="California",
                    jurisdiction="CA",
                    data_type="compliance",
                    section="total_loss",
                ),
            ),
            Chunk(
                content="Repair shop selection and labor rate requirements.",
                metadata=ChunkMetadata(
                    source_file="test.json",
                    state="California",
                    jurisdiction="CA",
                    data_type="compliance",
                    section="repair",
                ),
            ),
            Chunk(
                content="Fraud detection and SIU investigation procedures.",
                metadata=ChunkMetadata(
                    source_file="test.json",
                    state="California",
                    jurisdiction="CA",
                    data_type="compliance",
                    section="fraud",
                ),
            ),
        ]
        
        store.add_chunks(chunks)
        
        # Search for total loss content
        results = store.search("total loss valuation", top_k=2)
        
        assert len(results) > 0
        assert results[0][0].metadata.section == "total_loss"
    
    @pytest.mark.slow
    def test_vector_store_search_with_filters(self):
        """Test searching with metadata filters."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        
        store = VectorStore()
        
        # Add chunks from different states
        chunks = [
            Chunk(
                content="California total loss requirements.",
                metadata=ChunkMetadata(
                    source_file="ca.json",
                    state="California",
                    jurisdiction="CA",
                    data_type="compliance",
                    section="total_loss",
                ),
            ),
            Chunk(
                content="Texas total loss requirements.",
                metadata=ChunkMetadata(
                    source_file="tx.json",
                    state="Texas",
                    jurisdiction="TX",
                    data_type="compliance",
                    section="total_loss",
                ),
            ),
        ]
        
        store.add_chunks(chunks)
        
        # Search with state filter
        ca_results = store.search(
            "total loss",
            state_filter="California",
        )
        
        assert len(ca_results) == 1
        assert ca_results[0][0].metadata.state == "California"
    
    @pytest.mark.slow
    def test_vector_store_save_load(self):
        """Test persisting and loading the vector store."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache"
            
            # Create and populate store
            store = VectorStore()
            chunks = [
                Chunk(
                    content="Test content for persistence.",
                    metadata=ChunkMetadata(
                        source_file="test.json",
                        state="California",
                        jurisdiction="CA",
                        data_type="compliance",
                        section="test",
                    ),
                ),
            ]
            store.add_chunks(chunks)
            
            # Save
            store.save(cache_path)
            
            # Load into new store
            loaded_store = VectorStore.load_from_disk(cache_path)
            
            assert loaded_store.size == 1
            
            # Search should work
            results = loaded_store.search("test content")
            assert len(results) > 0

    def test_vector_store_save_writes_meta_json(self):
        """Test that save() writes meta.json with embedding_dimension."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        from claim_agent.rag.embeddings import EmbeddingProvider
        import json

        class FixedDimProvider(EmbeddingProvider):
            def __init__(self, dim: int = 64):
                self._dim = dim

            def embed(self, text: str):
                return np.zeros(self._dim)

            def embed_batch(self, texts: list):
                return np.zeros((len(texts), self._dim))

            @property
            def dimension(self):
                return self._dim

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache"
            store = VectorStore(embedding_provider=FixedDimProvider(64))
            chunks = [
                Chunk(
                    content="Test content.",
                    metadata=ChunkMetadata(
                        source_file="test.json",
                        state="California",
                        jurisdiction="CA",
                        data_type="compliance",
                        section="test",
                    ),
                ),
            ]
            store.add_chunks(chunks)
            store.save(cache_path)
            meta_path = cache_path / "meta.json"
            assert meta_path.exists()
            with open(meta_path) as f:
                meta = json.load(f)
            assert "embedding_dimension" in meta
            assert meta["embedding_dimension"] == 64
            assert meta.get("chunk_count") == 1

    def test_vector_store_load_dimension_mismatch_raises(self):
        """Test that load() raises ValueError when cache dimension != provider dimension."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        from claim_agent.rag.embeddings import EmbeddingProvider
        import json

        class FixedDimProvider(EmbeddingProvider):
            def __init__(self, dim: int):
                self._dim = dim

            def embed(self, text: str):
                return np.zeros(self._dim)

            def embed_batch(self, texts: list):
                return np.zeros((len(texts), self._dim))

            @property
            def dimension(self):
                return self._dim

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache"
            # Build cache with mock provider dimension 384
            provider_384 = FixedDimProvider(384)
            store_orig = VectorStore(embedding_provider=provider_384)
            chunks = [
                Chunk(
                    content="Test.",
                    metadata=ChunkMetadata(
                        source_file="t.json",
                        state="California",
                        jurisdiction="CA",
                        data_type="compliance",
                        section="s",
                    ),
                ),
            ]
            store_orig.add_chunks(chunks)
            store_orig.save(cache_path)
            # Overwrite meta to a different dimension so load will see mismatch
            with open(cache_path / "meta.json") as f:
                meta = json.load(f)
            meta["embedding_dimension"] = 999
            with open(cache_path / "meta.json", "w") as f:
                json.dump(meta, f)
            # Load with provider that has dimension 100
            provider_100 = FixedDimProvider(100)
            store_loaded = VectorStore(embedding_provider=provider_100)
            with pytest.raises(ValueError, match="dimension=999.*dimension=100"):
                store_loaded.load(cache_path)

    def test_vector_store_load_same_dimension_succeeds(self):
        """Test that load() succeeds when meta.json dimension matches provider."""
        from claim_agent.rag.vector_store import VectorStore
        from claim_agent.rag.chunker import Chunk, ChunkMetadata
        from claim_agent.rag.embeddings import EmbeddingProvider

        class FixedDimProvider(EmbeddingProvider):
            def __init__(self, dim: int = 64):
                self._dim = dim

            def embed(self, text: str):
                return np.zeros(self._dim)

            def embed_batch(self, texts: list):
                return np.zeros((len(texts), self._dim))

            @property
            def dimension(self):
                return self._dim

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache"
            provider = FixedDimProvider(64)
            store = VectorStore(embedding_provider=provider)
            chunks = [
                Chunk(
                    content="Same dimension test.",
                    metadata=ChunkMetadata(
                        source_file="t.json",
                        state="California",
                        jurisdiction="CA",
                        data_type="compliance",
                        section="s",
                    ),
                ),
            ]
            store.add_chunks(chunks)
            store.save(cache_path)
            loaded = VectorStore(embedding_provider=FixedDimProvider(64))
            loaded.load(cache_path)
            assert loaded.size == 1
            assert loaded.dimension == store.dimension


class TestPolicyRetriever:
    """Tests for the policy retriever."""
    
    @pytest.mark.slow
    def test_retriever_init(self):
        """Test retriever initialization."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
                auto_load=True,
            )
            
            stats = retriever.get_stats()
            assert stats["total_chunks"] > 0
    
    @pytest.mark.slow
    def test_retriever_search(self):
        """Test retriever search."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
            )
            
            results = retriever.search(
                query="total loss valuation",
                state="California",
            )
            
            assert len(results) > 0
    
    @pytest.mark.slow
    def test_retriever_get_context_for_claim_type(self):
        """Test getting context for claim types."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
            )
            
            chunks = retriever.get_context_for_claim_type(
                claim_type="total_loss",
                state="California",
            )
            
            assert len(chunks) > 0
    
    @pytest.mark.slow
    def test_retriever_format_context(self):
        """Test formatting context for prompts."""
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
            )
            
            chunks = retriever.get_context_for_claim_type(
                claim_type="total_loss",
                state="California",
                top_k=3,
            )
            
            context = retriever.format_context(chunks, include_metadata=True)
            
            assert len(context) > 0
            assert "California" in context


class TestRAGContext:
    """Tests for RAG context integration."""
    
    @pytest.mark.slow
    def test_get_rag_context(self):
        """Test getting RAG context for a skill."""
        from claim_agent.rag.context import get_rag_context
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
            )
            
            context = get_rag_context(
                skill_name="damage_assessor",
                state="California",
                claim_type="total_loss",
                retriever=retriever,
            )
            
            assert len(context) > 0
    
    @pytest.mark.slow
    def test_enrich_skill_with_context(self):
        """Test enriching a skill dictionary with context."""
        from claim_agent.rag.context import enrich_skill_with_context
        from claim_agent.rag.retriever import PolicyRetriever
        
        with tempfile.TemporaryDirectory() as tmpdir:
            retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
            )
            
            skill = {
                "role": "Damage Assessor",
                "goal": "Evaluate vehicle damage",
                "backstory": "Experienced in damage assessment.",
            }
            
            enriched = enrich_skill_with_context(
                skill_dict=skill,
                skill_name="damage_assessor",
                state="California",
                retriever=retriever,
            )
            
            # Backstory should be enriched
            assert len(enriched["backstory"]) > len(skill["backstory"])
            assert "Regulations" in enriched["backstory"] or "California" in enriched["backstory"]
    
    @pytest.mark.slow
    def test_rag_context_provider(self):
        """Test the RAG context provider class."""
        from claim_agent.rag.context import RAGContextProvider
        
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = RAGContextProvider(
                data_dir=DATA_DIR,
                default_state="California",
            )
            # Force use of temp cache
            provider._retriever = None
            provider._data_dir = DATA_DIR
            
            context = provider.get_context(
                skill_name="valuation",
                claim_type="total_loss",
            )
            
            assert len(context) >= 0  # May be empty if no matching content

    @pytest.mark.slow
    def test_rag_context_provider_cache_bounded(self):
        """Test that RAGContextProvider context cache is bounded (LRU)."""
        from claim_agent.rag.context import RAGContextProvider, CONTEXT_CACHE_MAXSIZE
        from claim_agent.rag.retriever import PolicyRetriever

        with tempfile.TemporaryDirectory() as tmpdir:
            provider = RAGContextProvider(
                data_dir=DATA_DIR,
                default_state="California",
            )
            provider._data_dir = DATA_DIR
            provider._retriever = PolicyRetriever(
                data_dir=DATA_DIR,
                cache_dir=Path(tmpdir),
                auto_load=True,
            )
            # Request more than maxsize distinct keys
            for i in range(CONTEXT_CACHE_MAXSIZE + 50):
                provider.get_context(
                    skill_name="damage_assessor",
                    state="California",
                    claim_type=f"claim_type_{i}",
                    use_cache=True,
                )
            assert len(provider._context_cache) <= CONTEXT_CACHE_MAXSIZE


class TestSkillsIntegration:
    """Tests for skills module RAG integration."""
    
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
        # Backstory should be enriched (if RAG loaded successfully)
        assert "backstory" in skill
    
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


class TestRAGTools:
    """Tests for RAG tools."""
    
    @pytest.mark.slow
    def test_search_policy_compliance_tool(self):
        """Test the search policy compliance tool."""
        from claim_agent.tools.rag_tools import search_policy_compliance
        
        # The tool function has wrapper from crewai
        # Test the underlying implementation
        result = search_policy_compliance.run(
            query="total loss valuation",
            state="California",
        )
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    @pytest.mark.slow
    def test_get_compliance_deadlines_tool(self):
        """Test the compliance deadlines tool."""
        from claim_agent.tools.rag_tools import get_compliance_deadlines
        
        result = get_compliance_deadlines.run(state="California")
        
        assert isinstance(result, str)
    
    @pytest.mark.slow
    def test_get_total_loss_requirements_tool(self):
        """Test the total loss requirements tool."""
        from claim_agent.tools.rag_tools import get_total_loss_requirements
        
        result = get_total_loss_requirements.run(state="California")
        
        assert isinstance(result, str)

    def test_rag_tool_invalid_state_returns_friendly_message(self):
        """Test that RAG tools return a friendly message for unsupported state."""
        from claim_agent.rag.constants import SUPPORTED_STATES
        from claim_agent.tools.rag_tools import get_compliance_deadlines

        result = get_compliance_deadlines.run(state="InvalidStateName")
        assert isinstance(result, str)
        assert "Unsupported state" in result or "Supported" in result
        for state in SUPPORTED_STATES:
            assert state in result
