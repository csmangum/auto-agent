"""Context integration for agent prompts.

Provides functions to enrich agent skills with relevant policy and
compliance context from the RAG system.
"""

from collections import OrderedDict
from pathlib import Path
from typing import Optional

from claim_agent.rag.chunker import Chunk
from claim_agent.rag.constants import DEFAULT_STATE
from claim_agent.rag.retriever import PolicyRetriever, get_retriever


# Maximum number of context entries to cache per RAGContextProvider
CONTEXT_CACHE_MAXSIZE = 100


class _LRUCache(OrderedDict):
    """Bounded LRU cache; evicts oldest when full."""

    def __init__(self, maxsize: int = CONTEXT_CACHE_MAXSIZE, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]


# Mapping of skill names to relevant query context
SKILL_CONTEXT_QUERIES = {
    # Router and intake
    "router": {
        "queries": ["claim classification routing total loss partial loss fraud"],
        "sections": ["common_claim_scenarios"],
    },
    "intake": {
        "queries": ["claim intake validation requirements documentation"],
        "sections": [],
    },
    
    # Policy verification
    "policy_checker": {
        "queries": ["policy coverage validation verification active coverage"],
        "sections": ["definitions", "liability_coverage"],
    },
    
    # Damage and valuation
    "damage_assessor": {
        "queries": ["damage assessment total loss threshold repair cost valuation"],
        "sections": ["total_loss_regulations", "physical_damage_coverage"],
    },
    "partial_loss_damage_assessor": {
        "queries": ["repair damage assessment collision coverage deductible"],
        "sections": ["physical_damage_coverage", "repair_standards"],
    },
    "valuation": {
        "queries": ["actual cash value ACV vehicle valuation market value comparable"],
        "sections": ["total_loss_regulations"],
    },
    
    # Repair workflow
    "repair_estimator": {
        "queries": ["repair estimate labor rate parts OEM aftermarket"],
        "sections": ["repair_standards"],
    },
    "repair_shop_coordinator": {
        "queries": ["repair shop choice direct repair program DRP"],
        "sections": ["repair_standards", "required_disclosures"],
    },
    "parts_ordering": {
        "queries": ["parts OEM aftermarket used recycled disclosure"],
        "sections": ["repair_standards"],
    },
    "repair_authorization": {
        "queries": ["repair authorization payment settlement"],
        "sections": ["fair_claims_settlement_practices"],
    },
    
    # Settlement and payout
    "payout": {
        "queries": ["payout calculation deductible settlement payment"],
        "sections": ["fair_claims_settlement_practices", "total_loss_regulations"],
    },
    "settlement": {
        "queries": ["settlement report claim closure payment deadline"],
        "sections": ["fair_claims_settlement_practices", "time_limits_and_deadlines"],
    },
    
    # Duplicate handling
    "search": {
        "queries": ["claim search duplicate VIN matching"],
        "sections": [],
    },
    "similarity": {
        "queries": ["claim similarity duplicate detection"],
        "sections": [],
    },
    "resolution": {
        "queries": ["duplicate resolution merge reject"],
        "sections": [],
    },
    
    # Fraud detection
    "pattern_analysis": {
        "queries": ["fraud pattern staged accident suspicious indicators"],
        "sections": ["anti_fraud_provisions"],
    },
    "cross_reference": {
        "queries": ["fraud database cross reference indicators"],
        "sections": ["anti_fraud_provisions"],
    },
    "fraud_assessment": {
        "queries": ["fraud assessment SIU referral investigation"],
        "sections": ["anti_fraud_provisions"],
    },
    
    # Escalation
    "escalation": {
        "queries": ["escalation human review high value low confidence"],
        "sections": ["good_faith_requirements"],
    },
}


def get_rag_context(
    skill_name: str,
    state: str = DEFAULT_STATE,
    claim_type: Optional[str] = None,
    top_k: int = 5,
    retriever: Optional[PolicyRetriever] = None,
) -> str:
    """Get RAG context for an agent skill.
    
    Args:
        skill_name: Name of the skill/agent
        state: State jurisdiction for the claim
        claim_type: Optional claim type for additional context
        top_k: Number of chunks to retrieve per query
        retriever: Optional PolicyRetriever instance
        
    Returns:
        Formatted context string to include in agent prompt
    """
    if retriever is None:
        retriever = get_retriever()
    
    skill_config = SKILL_CONTEXT_QUERIES.get(skill_name, {})
    queries = skill_config.get("queries", [])
    sections = skill_config.get("sections", [])
    
    all_chunks: list[Chunk] = []
    seen_ids: set[str] = set()
    
    # Search by queries
    for query in queries:
        results = retriever.search(
            query=query,
            top_k=top_k,
            state=state,
            min_score=0.25,
        )
        for chunk, _ in results:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                all_chunks.append(chunk)
    
    # Search by sections
    for section in sections:
        section_chunks = retriever.vector_store.search_by_metadata(
            state=state,
            section=section,
        )
        for chunk in section_chunks[:3]:  # Limit per section
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                all_chunks.append(chunk)
    
    # Add claim-type specific context if provided
    if claim_type:
        claim_chunks = retriever.get_context_for_claim_type(
            claim_type=claim_type,
            state=state,
            top_k=top_k,
        )
        for chunk in claim_chunks:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                all_chunks.append(chunk)
    
    # Format and return
    return retriever.format_context(all_chunks, include_metadata=True)


def enrich_skill_with_context(
    skill_dict: dict,
    skill_name: str,
    state: str = DEFAULT_STATE,
    claim_type: Optional[str] = None,
    retriever: Optional[PolicyRetriever] = None,
) -> dict:
    """Enrich a skill dictionary with RAG context.
    
    Adds relevant policy and compliance context to the skill's backstory
    or creates a new 'context' field.
    
    Args:
        skill_dict: Dictionary with skill components (role, goal, backstory, etc.)
        skill_name: Name of the skill
        state: State jurisdiction
        claim_type: Optional claim type
        retriever: Optional PolicyRetriever instance
        
    Returns:
        Enriched skill dictionary with added context
    """
    context = get_rag_context(
        skill_name=skill_name,
        state=state,
        claim_type=claim_type,
        retriever=retriever,
    )
    
    if not context:
        return skill_dict
    
    # Create enriched copy
    enriched = skill_dict.copy()
    
    # Add context to backstory or create separate field
    if enriched.get("backstory"):
        enriched["backstory"] = (
            f"{enriched['backstory']}\n\n"
            f"## Applicable Regulations and Policy Language\n\n{context}"
        )
    else:
        enriched["context"] = context
    
    return enriched


class RAGContextProvider:
    """Provider for RAG context in agent workflows.
    
    Caches context and provides easy access during claim processing.
    """
    
    def __init__(
        self,
        data_dir: Optional[Path] = None,
        default_state: str = DEFAULT_STATE,
    ):
        """Initialize the context provider.
        
        Args:
            data_dir: Directory containing policy/compliance data
            default_state: Default state jurisdiction
        """
        self.default_state = default_state
        self._retriever: Optional[PolicyRetriever] = None
        self._data_dir = data_dir
        self._context_cache: _LRUCache = _LRUCache(maxsize=CONTEXT_CACHE_MAXSIZE)
    
    @property
    def retriever(self) -> PolicyRetriever:
        """Lazy-load the retriever."""
        if self._retriever is None:
            self._retriever = PolicyRetriever(
                data_dir=self._data_dir,
                auto_load=True,
            )
        return self._retriever
    
    def get_context(
        self,
        skill_name: str,
        state: Optional[str] = None,
        claim_type: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """Get context for a skill.
        
        Args:
            skill_name: Name of the skill
            state: State jurisdiction (defaults to default_state)
            claim_type: Optional claim type
            use_cache: Whether to use cached context
            
        Returns:
            Context string
        """
        state = state or self.default_state
        cache_key = f"{skill_name}:{state}:{claim_type or ''}"
        
        if use_cache and cache_key in self._context_cache:
            return self._context_cache[cache_key]
        
        context = get_rag_context(
            skill_name=skill_name,
            state=state,
            claim_type=claim_type,
            retriever=self.retriever,
        )
        
        if use_cache:
            self._context_cache[cache_key] = context
        
        return context
    
    def enrich_skill(
        self,
        skill_dict: dict,
        skill_name: str,
        state: Optional[str] = None,
        claim_type: Optional[str] = None,
    ) -> dict:
        """Enrich a skill dictionary with context.
        
        Args:
            skill_dict: Skill dictionary
            skill_name: Name of the skill
            state: State jurisdiction
            claim_type: Optional claim type
            
        Returns:
            Enriched skill dictionary
        """
        return enrich_skill_with_context(
            skill_dict=skill_dict,
            skill_name=skill_name,
            state=state or self.default_state,
            claim_type=claim_type,
            retriever=self.retriever,
        )
    
    def get_claim_context(
        self,
        claim_type: str,
        state: Optional[str] = None,
    ) -> str:
        """Get general context for a claim type.
        
        Args:
            claim_type: Type of claim
            state: State jurisdiction
            
        Returns:
            Context string
        """
        state = state or self.default_state
        chunks = self.retriever.get_context_for_claim_type(
            claim_type=claim_type,
            state=state,
        )
        return self.retriever.format_context(chunks)
    
    def get_deadlines(self, state: Optional[str] = None) -> str:
        """Get compliance deadlines for a state.
        
        Args:
            state: State jurisdiction
            
        Returns:
            Formatted deadlines context
        """
        state = state or self.default_state
        chunks = self.retriever.get_compliance_deadlines(state=state)
        return self.retriever.format_context(chunks)
    
    def get_disclosures(self, state: Optional[str] = None) -> str:
        """Get required disclosures for a state.
        
        Args:
            state: State jurisdiction
            
        Returns:
            Formatted disclosures context
        """
        state = state or self.default_state
        chunks = self.retriever.get_required_disclosures(state=state)
        return self.retriever.format_context(chunks)
    
    def clear_cache(self) -> None:
        """Clear the context cache."""
        self._context_cache.clear()
    
    def get_stats(self) -> dict:
        """Get retriever statistics."""
        return self.retriever.get_stats()
