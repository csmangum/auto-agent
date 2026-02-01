"""Vector store for storing and searching document embeddings.

A simple, numpy-based vector store that doesn't require external databases.
For production, consider using Chroma, Pinecone, or similar.
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np

from claim_agent.rag.chunker import Chunk, ChunkMetadata
from claim_agent.rag.embeddings import EmbeddingProvider, get_embedding_provider


# Threshold for considering a vector norm to be zero
ZERO_NORM_THRESHOLD = 1e-8


class VectorStore:
    """Simple in-memory vector store with numpy.
    
    Stores embeddings and supports cosine similarity search.
    Can be persisted to disk and loaded back.
    """
    
    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        """Initialize the vector store.
        
        Args:
            embedding_provider: Provider for generating embeddings.
                              Defaults to sentence-transformers.
        """
        self.embedding_provider = embedding_provider or get_embedding_provider()
        
        # Storage
        self._embeddings: Optional[np.ndarray] = None
        self._chunks: list[Chunk] = []
        self._chunk_id_to_idx: dict[str, int] = {}
    
    @property
    def size(self) -> int:
        """Return the number of stored chunks."""
        return len(self._chunks)
    
    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        return self.embedding_provider.dimension
    
    def add_chunks(self, chunks: list[Chunk], show_progress: bool = False) -> None:
        """Add chunks to the vector store.
        
        Args:
            chunks: List of Chunk objects to add
            show_progress: Whether to show progress bar
        """
        if not chunks:
            return
        
        # Filter out duplicates
        new_chunks = [c for c in chunks if c.chunk_id not in self._chunk_id_to_idx]
        if not new_chunks:
            return
        
        # Generate embeddings for new chunks
        texts = [c.content for c in new_chunks]
        new_embeddings = self.embedding_provider.embed_batch(texts)
        
        # Update storage
        start_idx = len(self._chunks)
        for i, chunk in enumerate(new_chunks):
            self._chunk_id_to_idx[chunk.chunk_id] = start_idx + i
            self._chunks.append(chunk)
        
        if self._embeddings is None:
            self._embeddings = new_embeddings
        else:
            self._embeddings = np.vstack([self._embeddings, new_embeddings])
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        state_filter: Optional[str] = None,
        data_type_filter: Optional[str] = None,
        section_filter: Optional[str] = None,
        min_score: float = 0.0,
    ) -> list[tuple[Chunk, float]]:
        """Search for similar chunks.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            state_filter: Filter by state (e.g., "California")
            data_type_filter: Filter by data type (e.g., "compliance", "policy_language")
            section_filter: Filter by section name
            min_score: Minimum similarity score threshold
            
        Returns:
            List of (Chunk, score) tuples, sorted by score descending
        """
        if self._embeddings is None or len(self._chunks) == 0:
            return []
        
        # Generate query embedding
        query_embedding = self.embedding_provider.embed(query)
        
        # Compute cosine similarity
        scores = self._cosine_similarity(query_embedding, self._embeddings)
        
        # Apply filters and collect results
        results = []
        for idx, score in enumerate(scores):
            if score < min_score:
                continue
            
            chunk = self._chunks[idx]
            
            # Apply filters
            if state_filter and chunk.metadata.state.lower() != state_filter.lower():
                continue
            if data_type_filter and data_type_filter not in chunk.metadata.data_type:
                continue
            if section_filter and section_filter.lower() not in chunk.metadata.section.lower():
                continue
            
            results.append((chunk, float(score)))
        
        # Sort by score and return top_k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    def search_by_metadata(
        self,
        state: Optional[str] = None,
        data_type: Optional[str] = None,
        section: Optional[str] = None,
        provision_id: Optional[str] = None,
    ) -> list[Chunk]:
        """Search chunks by metadata (exact match).
        
        Args:
            state: Filter by state
            data_type: Filter by data type
            section: Filter by section name
            provision_id: Filter by provision ID
            
        Returns:
            List of matching chunks
        """
        results = []
        
        for chunk in self._chunks:
            meta = chunk.metadata
            
            if state and meta.state.lower() != state.lower():
                continue
            if data_type and data_type not in meta.data_type:
                continue
            if section and section.lower() not in meta.section.lower():
                continue
            if provision_id and meta.provision_id != provision_id:
                continue
            
            results.append(chunk)
        
        return results
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Chunk]:
        """Get a chunk by its ID.
        
        Args:
            chunk_id: The chunk ID
            
        Returns:
            Chunk if found, None otherwise
        """
        idx = self._chunk_id_to_idx.get(chunk_id)
        if idx is not None:
            return self._chunks[idx]
        return None
    
    def _cosine_similarity(
        self, 
        query_vec: np.ndarray, 
        embeddings: np.ndarray,
    ) -> np.ndarray:
        """Compute cosine similarity between query and all embeddings.
        
        Args:
            query_vec: Query embedding vector
            embeddings: Matrix of embeddings
            
        Returns:
            Array of similarity scores
        """
        # Handle zero-norm query explicitly: no meaningful direction -> zero similarity
        query_norm_value = np.linalg.norm(query_vec)
        if query_norm_value < ZERO_NORM_THRESHOLD:
            return np.zeros(embeddings.shape[0])
        
        # Normalize query vector
        query_norm = query_vec / query_norm_value
        
        # Compute norms for each embedding vector
        emb_norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        # Initialize normalized embeddings as zeros; zero-norm embeddings stay zero
        embeddings_norm = np.zeros_like(embeddings)
        
        # Identify embeddings with non-zero norm and normalize only those
        valid_mask = emb_norms.squeeze(-1) >= ZERO_NORM_THRESHOLD
        if np.any(valid_mask):
            embeddings_norm[valid_mask] = embeddings[valid_mask] / emb_norms[valid_mask]
        
        # Dot product gives cosine similarity for normalized vectors
        return np.dot(embeddings_norm, query_norm)
    
    def save(self, path: Path) -> None:
        """Save the vector store to disk.
        
        Args:
            path: Directory path to save to
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        # Save embeddings
        if self._embeddings is not None:
            np.save(path / "embeddings.npy", self._embeddings)
        
        # Save chunks as JSON
        chunks_data = [c.to_dict() for c in self._chunks]
        with open(path / "chunks.json", "w") as f:
            json.dump(chunks_data, f, indent=2)
        
        # Save index
        with open(path / "index.json", "w") as f:
            json.dump(self._chunk_id_to_idx, f)
    
    def load(self, path: Path) -> None:
        """Load the vector store from disk.
        
        Args:
            path: Directory path to load from
        """
        path = Path(path)
        
        # Load embeddings
        embeddings_path = path / "embeddings.npy"
        if embeddings_path.exists():
            self._embeddings = np.load(embeddings_path)
        
        # Load chunks
        chunks_path = path / "chunks.json"
        if chunks_path.exists():
            with open(chunks_path) as f:
                chunks_data = json.load(f)
            self._chunks = [Chunk.from_dict(c) for c in chunks_data]
        
        # Load index
        index_path = path / "index.json"
        if index_path.exists():
            with open(index_path) as f:
                self._chunk_id_to_idx = json.load(f)
    
    @classmethod
    def load_from_disk(
        cls,
        path: Path,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> "VectorStore":
        """Load a vector store from disk.
        
        Args:
            path: Directory path to load from
            embedding_provider: Provider for generating new embeddings
            
        Returns:
            Loaded VectorStore instance
        """
        store = cls(embedding_provider=embedding_provider)
        store.load(path)
        return store
    
    def clear(self) -> None:
        """Clear all stored data."""
        self._embeddings = None
        self._chunks = []
        self._chunk_id_to_idx = {}
    
    def get_stats(self) -> dict:
        """Get statistics about the vector store.
        
        Returns:
            Dictionary with store statistics
        """
        stats = {
            "total_chunks": len(self._chunks),
            "embedding_dimension": self.dimension if self._embeddings is not None else 0,
        }
        
        # Count by state
        state_counts = {}
        for chunk in self._chunks:
            state = chunk.metadata.state
            state_counts[state] = state_counts.get(state, 0) + 1
        stats["chunks_by_state"] = state_counts
        
        # Count by data type
        type_counts = {}
        for chunk in self._chunks:
            dtype = chunk.metadata.data_type
            type_counts[dtype] = type_counts.get(dtype, 0) + 1
        stats["chunks_by_type"] = type_counts
        
        return stats
