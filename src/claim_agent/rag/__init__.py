"""RAG (Retrieval-Augmented Generation) module for policy and compliance context.

This module provides semantic search over policy language and compliance regulations,
enabling agents to retrieve relevant context for claim processing.
"""

from claim_agent.rag.chunker import (
    DocumentChunker,
    Chunk,
    ChunkMetadata,
    chunk_policy_data,
    chunk_compliance_data,
)
from claim_agent.rag.vector_store import VectorStore
from claim_agent.rag.retriever import PolicyRetriever
from claim_agent.rag.context import (
    get_rag_context,
    enrich_skill_with_context,
    RAGContextProvider,
)

__all__ = [
    # Chunking
    "DocumentChunker",
    "Chunk",
    "ChunkMetadata",
    "chunk_policy_data",
    "chunk_compliance_data",
    # Vector store
    "VectorStore",
    # Retrieval
    "PolicyRetriever",
    # Context integration
    "get_rag_context",
    "enrich_skill_with_context",
    "RAGContextProvider",
]
