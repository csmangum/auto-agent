"""Policy and compliance retriever for RAG.

High-level interface for retrieving relevant policy and compliance context
for claim processing agents.
"""

import json
import os
from pathlib import Path
from typing import Optional

from claim_agent.rag.chunker import (
    Chunk,
    chunk_policy_data,
    chunk_compliance_data,
)
from claim_agent.rag.embeddings import EmbeddingProvider, get_embedding_provider
from claim_agent.rag.vector_store import VectorStore


def _get_default_cache_dir() -> Path:
    """Return a suitable default cache directory for the vector store.

    Preference order:
    1. Environment variable CLAIM_AGENT_CACHE_DIR, if set.
    2. A user-level cache directory based on the current platform.
    """
    env_dir = os.getenv("CLAIM_AGENT_CACHE_DIR")
    if env_dir:
        return Path(env_dir)

    # Windows: use LOCALAPPDATA if available, otherwise fall back under the home directory
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / "AppData" / "Local"
        return base / "claim_agent" / "cache"

    # POSIX and other: use XDG-style cache directory under the home directory
    return Path.home() / ".cache" / "claim_agent"


# Default data directory
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"

# Default cache directory for persisted vector store
DEFAULT_CACHE_DIR = _get_default_cache_dir()


class PolicyRetriever:
    """Retriever for policy and compliance documents.
    
    Provides a high-level interface for:
    - Loading and indexing policy/compliance documents
    - Semantic search across documents
    - Filtering by state, claim type, and coverage type
    """
    
    def __init__(
        self,
        data_dir: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        auto_load: bool = True,
    ):
        """Initialize the retriever.
        
        Args:
            data_dir: Directory containing policy/compliance JSON files
            cache_dir: Directory for caching the vector store
            embedding_provider: Provider for generating embeddings
            auto_load: Whether to automatically load documents on init
        """
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.vector_store = VectorStore(embedding_provider=self.embedding_provider)
        
        self._loaded = False
        
        if auto_load:
            self.load_or_build_index()
    
    def load_or_build_index(self, force_rebuild: bool = False) -> None:
        """Load the index from cache or build it from scratch.
        
        Args:
            force_rebuild: If True, rebuild even if cache exists
        """
        cache_exists = (self.cache_dir / "chunks.json").exists()
        
        if cache_exists and not force_rebuild:
            try:
                self.vector_store.load(self.cache_dir)
                self._loaded = True
                return
            except (json.JSONDecodeError, FileNotFoundError, KeyError, ValueError) as e:
                # Cache is corrupted or incompatible, rebuild
                import logging
                logging.warning(f"Failed to load cache from {self.cache_dir}: {e}. Rebuilding index.")
        
        self._build_index()
        self._loaded = True
    
    def _build_index(self) -> None:
        """Build the vector store index from documents."""
        import logging
        
        # Validate data directory exists
        if not self.data_dir.exists():
            logging.warning(f"Data directory {self.data_dir} does not exist. Creating empty index.")
            return
        
        # Chunk all documents
        all_chunks = []
        
        # Policy language files
        policy_chunks = chunk_policy_data(self.data_dir)
        all_chunks.extend(policy_chunks)
        
        # Compliance files
        compliance_chunks = chunk_compliance_data(self.data_dir)
        all_chunks.extend(compliance_chunks)
        
        # Warn if no chunks found
        if not all_chunks:
            logging.warning(
                f"No policy or compliance documents found in {self.data_dir}. "
                "Expected JSON files matching patterns: "
                "*_auto_policy_language.json, *_auto_compliance.json"
            )
            return
        
        # Add to vector store
        self.vector_store.add_chunks(all_chunks)
        
        # Save cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store.save(self.cache_dir)
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        state: Optional[str] = None,
        data_type: Optional[str] = None,
        section: Optional[str] = None,
        min_score: float = 0.3,
    ) -> list[tuple[Chunk, float]]:
        """Search for relevant policy/compliance content.
        
        Args:
            query: Natural language search query
            top_k: Number of results to return
            state: Filter by state (e.g., "California", "Texas")
            data_type: Filter by type ("compliance" or "policy_language")
            section: Filter by section name
            min_score: Minimum similarity score
            
        Returns:
            List of (Chunk, score) tuples
        """
        return self.vector_store.search(
            query=query,
            top_k=top_k,
            state_filter=state,
            data_type_filter=data_type,
            section_filter=section,
            min_score=min_score,
        )
    
    def get_context_for_claim_type(
        self,
        claim_type: str,
        state: str,
        top_k: int = 10,
    ) -> list[Chunk]:
        """Get relevant context for a specific claim type.
        
        Args:
            claim_type: Type of claim (total_loss, partial_loss, fraud, etc.)
            state: State jurisdiction
            top_k: Number of chunks to retrieve
            
        Returns:
            List of relevant chunks
        """
        # Build query based on claim type
        claim_queries = {
            "total_loss": "total loss vehicle valuation settlement actual cash value salvage",
            "partial_loss": "repair estimate parts labor damage assessment collision coverage",
            "fraud": "fraud investigation suspicious patterns staged accident indicators",
            "new": "claim intake policy verification coverage validation",
            "duplicate": "duplicate claim matching VIN incident date",
        }
        
        query = claim_queries.get(claim_type, f"{claim_type} claim processing")
        
        results = self.search(
            query=query,
            top_k=top_k,
            state=state,
            min_score=0.2,
        )
        
        return [chunk for chunk, _ in results]
    
    def get_context_for_coverage(
        self,
        coverage_type: str,
        state: str,
        top_k: int = 5,
    ) -> list[Chunk]:
        """Get context for a specific coverage type.
        
        Args:
            coverage_type: Type of coverage (liability, collision, comprehensive, etc.)
            state: State jurisdiction
            top_k: Number of chunks to retrieve
            
        Returns:
            List of relevant chunks
        """
        coverage_queries = {
            "liability": "liability coverage bodily injury property damage limits",
            "collision": "collision coverage deductible physical damage",
            "comprehensive": "comprehensive other than collision coverage theft fire flood",
            "uninsured_motorist": "uninsured motorist UM underinsured UIM coverage",
            "medical_payments": "medical payments MedPay coverage no-fault PIP",
            "pip": "personal injury protection PIP no-fault benefits",
        }
        
        query = coverage_queries.get(
            coverage_type.lower(), 
            f"{coverage_type} coverage insurance"
        )
        
        results = self.search(
            query=query,
            top_k=top_k,
            state=state,
            min_score=0.2,
        )
        
        return [chunk for chunk, _ in results]
    
    def get_compliance_deadlines(
        self,
        state: str,
        action_type: Optional[str] = None,
    ) -> list[Chunk]:
        """Get compliance deadlines for a state.
        
        Args:
            state: State jurisdiction
            action_type: Optional filter for deadline type
            
        Returns:
            List of deadline-related chunks
        """
        query = "deadline time limit days calendar claims processing"
        if action_type:
            query += f" {action_type}"
        
        results = self.search(
            query=query,
            top_k=10,
            state=state,
            data_type="compliance",
            min_score=0.2,
        )
        
        # Also do metadata search for deadline subsections
        deadline_chunks = self.vector_store.search_by_metadata(
            state=state,
            data_type="compliance",
            section="time_limits",
        )
        
        # Combine and deduplicate
        seen_ids = set()
        combined = []
        
        for chunk, _ in results:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                combined.append(chunk)
        
        for chunk in deadline_chunks:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                combined.append(chunk)
        
        return combined
    
    def get_required_disclosures(self, state: str) -> list[Chunk]:
        """Get required disclosure information for a state.
        
        Args:
            state: State jurisdiction
            
        Returns:
            List of disclosure-related chunks
        """
        results = self.search(
            query="required disclosure notice consumer rights claimant",
            top_k=10,
            state=state,
            data_type="compliance",
            min_score=0.2,
        )
        
        return [chunk for chunk, _ in results]
    
    def get_exclusions(
        self,
        coverage_type: str,
        state: str,
    ) -> list[Chunk]:
        """Get exclusions for a coverage type.
        
        Args:
            coverage_type: Type of coverage
            state: State jurisdiction
            
        Returns:
            List of exclusion-related chunks
        """
        query = f"{coverage_type} exclusion not covered exception"
        
        results = self.search(
            query=query,
            top_k=10,
            state=state,
            data_type="policy_language",
            min_score=0.2,
        )
        
        return [chunk for chunk, _ in results]
    
    def format_context(
        self,
        chunks: list[Chunk],
        include_metadata: bool = True,
        max_length: int = 4000,
    ) -> str:
        """Format chunks into a context string for prompts.
        
        Args:
            chunks: List of chunks to format
            include_metadata: Whether to include metadata in output
            max_length: Maximum character length
            
        Returns:
            Formatted context string
        """
        if not chunks:
            return ""
        
        parts = []
        current_length = 0
        
        for chunk in chunks:
            if include_metadata:
                meta = chunk.metadata
                header = f"[{meta.state} - {meta.section}]"
                if meta.title:
                    header += f" {meta.title}"
                content = f"{header}\n{chunk.content}"
            else:
                content = chunk.content
            
            # Check length
            if current_length + len(content) + 4 > max_length:  # +4 for separator
                break
            
            parts.append(content)
            current_length += len(content) + 4
        
        return "\n---\n".join(parts)
    
    def get_stats(self) -> dict:
        """Get retriever statistics.
        
        Returns:
            Dictionary with statistics
        """
        return self.vector_store.get_stats()
    
    def refresh_index(self) -> None:
        """Refresh the index by rebuilding from source documents."""
        self.vector_store.clear()
        self._build_index()


# Global retriever instance (lazy-loaded)
_global_retriever: Optional[PolicyRetriever] = None


def get_retriever(
    data_dir: Optional[Path] = None,
    force_new: bool = False,
) -> PolicyRetriever:
    """Get the global PolicyRetriever instance.
    
    Args:
        data_dir: Optional custom data directory
        force_new: If True, create a new instance
        
    Returns:
        PolicyRetriever instance
        
    Raises:
        ValueError: If data_dir differs from existing instance without force_new=True
    """
    global _global_retriever
    
    # Create a new retriever if none exists yet or the caller explicitly requests one.
    if _global_retriever is None or force_new:
        _global_retriever = PolicyRetriever(
            data_dir=data_dir,
            auto_load=True,
        )
        return _global_retriever

    # If a retriever already exists and a custom data_dir is provided, ensure it
    # matches the existing instance's data_dir to avoid confusing, silent misuse.
    if data_dir is not None:
        try:
            existing_dir = Path(getattr(_global_retriever, "data_dir", DEFAULT_DATA_DIR))
        except TypeError:
            # Fallback: if existing data_dir is not path-like, skip strict checking
            existing_dir = getattr(_global_retriever, "data_dir", DEFAULT_DATA_DIR)
        requested_dir = Path(data_dir)

        if existing_dir != requested_dir:
            raise ValueError(
                f"Global PolicyRetriever already initialized with data_dir="
                f"{existing_dir!r}, but get_retriever was called with a different "
                f"data_dir={requested_dir!r}. Either call get_retriever with "
                f"force_new=True to create a new instance, or reuse the existing "
                f"data_dir."
            )
    
    return _global_retriever
