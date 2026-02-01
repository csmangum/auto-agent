"""Embedding generation for RAG.

Supports multiple embedding backends:
- sentence-transformers (local, default)
- OpenAI embeddings (API-based)
"""

import os
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Union

import numpy as np

# Max retries for transient OpenAI API failures
OPENAI_EMBED_MAX_ATTEMPTS = 3


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""
    
    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as numpy array
        """
        pass
    
    @abstractmethod
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            2D numpy array of embeddings (num_texts x embedding_dim)
        """
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass


class SentenceTransformerEmbedding(EmbeddingProvider):
    """Sentence-transformers based embeddings (local, no API needed)."""
    
    # Default model - good balance of quality and speed
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    
    def __init__(self, model_name: Optional[str] = None):
        """Initialize the embedding provider.
        
        Args:
            model_name: Name of the sentence-transformers model to use
        """
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = None
        self._dimension = None
    
    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for local embeddings. "
                    "Install with: pip install sentence-transformers"
                )
        return self._model
    
    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        if self._dimension is None:
            # Trigger model load
            _ = self.model
        return self._dimension
    
    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        return self.model.encode(text, convert_to_numpy=True)
    
    def embed_batch(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Batch size for encoding
            
        Returns:
            2D numpy array of embeddings
        """
        return self.model.encode(
            texts, 
            convert_to_numpy=True,
            batch_size=batch_size,
            show_progress_bar=False,
        )


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI API-based embeddings."""
    
    DEFAULT_MODEL = "text-embedding-3-small"
    
    def __init__(
        self, 
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize the OpenAI embedding provider.
        
        Args:
            model_name: Name of the OpenAI embedding model
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.model_name = model_name or self.DEFAULT_MODEL
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = None
        
        # Embedding dimensions for known models
        self._dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
    
    @property
    def client(self):
        """Lazy load the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "openai is required for OpenAI embeddings. "
                    "Install with: pip install openai"
                )
        return self._client
    
    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        return self._dimensions.get(self.model_name, 1536)
    
    def _call_embeddings_api(self, input_text: Union[str, List[str]]):
        """Call OpenAI embeddings API with retries for rate limits and transient errors."""
        for attempt in range(OPENAI_EMBED_MAX_ATTEMPTS):
            try:
                return self.client.embeddings.create(
                    model=self.model_name,
                    input=input_text,
                )
            except Exception as e:
                is_retryable = (
                    "rate" in type(e).__name__.lower()
                    or "connection" in type(e).__name__.lower()
                    or "429" in str(e)
                    or "503" in str(e)
                    or "500" in str(e)
                )
                if not is_retryable or attempt == OPENAI_EMBED_MAX_ATTEMPTS - 1:
                    raise
                time.sleep(2**attempt)

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        response = self._call_embeddings_api(text)
        return np.array(response.data[0].embedding)

    def embed_batch(self, texts: list[str], batch_size: int = 100) -> np.ndarray:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            batch_size: Batch size for API calls

        Returns:
            2D numpy array of embeddings
        """
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self._call_embeddings_api(batch)
            batch_embeddings = [np.array(d.embedding) for d in response.data]
            embeddings.extend(batch_embeddings)

        return np.array(embeddings)


def get_embedding_provider(
    provider: str = "sentence-transformers",
    model_name: Optional[str] = None,
    **kwargs,
) -> EmbeddingProvider:
    """Factory function to get an embedding provider.
    
    Args:
        provider: Provider type ("sentence-transformers" or "openai")
        model_name: Model name for the provider
        **kwargs: Additional arguments for the provider
        
    Returns:
        EmbeddingProvider instance
    """
    if provider == "sentence-transformers":
        return SentenceTransformerEmbedding(model_name=model_name)
    elif provider == "openai":
        return OpenAIEmbedding(model_name=model_name, **kwargs)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
