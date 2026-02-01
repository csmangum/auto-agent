"""Skills module for loading agent skill definitions from markdown files.

Skills can be enriched with RAG context for policy and compliance information.
"""

import logging
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from claim_agent.rag.context import RAGContextProvider


SKILLS_DIR = Path(__file__).parent

# Global RAG context provider (lazy-loaded)
_rag_provider: Optional["RAGContextProvider"] = None


def get_skill_path(skill_name: str) -> Path:
    """Get the full path to a skill markdown file.
    
    Args:
        skill_name: Name of the skill (without .md extension)
        
    Returns:
        Path to the skill file
        
    Raises:
        FileNotFoundError: If skill file doesn't exist
    """
    skill_path = SKILLS_DIR / f"{skill_name}.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return skill_path


def load_skill_content(skill_name: str) -> str:
    """Load the raw content of a skill file.
    
    Args:
        skill_name: Name of the skill (without .md extension)
        
    Returns:
        Full markdown content of the skill file
    """
    skill_path = get_skill_path(skill_name)
    return skill_path.read_text()


def parse_skill_section(content: str, section: str) -> Optional[str]:
    """Extract a specific section from skill content.
    
    Args:
        content: Full markdown content
        section: Section name to extract (e.g., "Role", "Goal", "Backstory")
        
    Returns:
        Section content or None if not found
    """
    # Pattern to match ## Section followed by content until next ## or end
    pattern = rf"## {section}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def load_skill(skill_name: str) -> dict:
    """Load and parse a skill file into a dictionary.
    
    Args:
        skill_name: Name of the skill (without .md extension)
        
    Returns:
        Dictionary with parsed skill components:
        - role: Agent role title
        - goal: Agent goal/objective
        - backstory: Agent backstory
        - full_content: Complete markdown content
    """
    content = load_skill_content(skill_name)
    
    return {
        "role": parse_skill_section(content, "Role"),
        "goal": parse_skill_section(content, "Goal"),
        "backstory": parse_skill_section(content, "Backstory"),
        "tools": parse_skill_section(content, "Tools"),
        "full_content": content,
    }


def load_skill_with_context(
    skill_name: str,
    state: str = "California",
    claim_type: Optional[str] = None,
    use_rag: bool = True,
) -> dict:
    """Load a skill file and enrich it with RAG context.
    
    This adds relevant policy and compliance information to the agent's
    backstory based on the skill type and state jurisdiction.
    
    Args:
        skill_name: Name of the skill (without .md extension)
        state: State jurisdiction for the claim (e.g., "California", "Texas")
        claim_type: Optional claim type for additional context
        use_rag: Whether to enrich with RAG context
        
    Returns:
        Dictionary with parsed skill components, enriched with context
    """
    skill = load_skill(skill_name)
    
    if not use_rag:
        return skill
    
    try:
        global _rag_provider
        if _rag_provider is None:
            from claim_agent.rag.context import RAGContextProvider
            _rag_provider = RAGContextProvider(default_state=state)
        
        return _rag_provider.enrich_skill(
            skill_dict=skill,
            skill_name=skill_name,
            state=state,
            claim_type=claim_type,
        )
    except (ImportError, FileNotFoundError, AttributeError, KeyError) as e:
        # If RAG fails, return the base skill
        logging.warning(f"Failed to enrich skill {skill_name} with RAG context: {e}")
        return skill


def get_rag_provider(state: str = "California") -> "RAGContextProvider":
    """Get the global RAG context provider.
    
    Args:
        state: Default state jurisdiction
        
    Returns:
        RAGContextProvider instance
    """
    global _rag_provider
    if _rag_provider is None:
        from claim_agent.rag.context import RAGContextProvider
        _rag_provider = RAGContextProvider(default_state=state)
    return _rag_provider


def list_skills() -> list[str]:
    """List all available skill files.
    
    Returns:
        List of skill names (without .md extension)
    """
    return [
        f.stem for f in SKILLS_DIR.glob("*.md") 
        if f.name != "README.md"
    ]


# Skill name constants for easy reference
ROUTER = "router"
INTAKE = "intake"
POLICY_CHECKER = "policy_checker"
ASSIGNMENT = "assignment"
SEARCH = "search"
SIMILARITY = "similarity"
RESOLUTION = "resolution"
PATTERN_ANALYSIS = "pattern_analysis"
CROSS_REFERENCE = "cross_reference"
FRAUD_ASSESSMENT = "fraud_assessment"
DAMAGE_ASSESSOR = "damage_assessor"
VALUATION = "valuation"
PAYOUT = "payout"
SETTLEMENT = "settlement"
PARTIAL_LOSS_DAMAGE_ASSESSOR = "partial_loss_damage_assessor"
REPAIR_ESTIMATOR = "repair_estimator"
REPAIR_SHOP_COORDINATOR = "repair_shop_coordinator"
PARTS_ORDERING = "parts_ordering"
REPAIR_AUTHORIZATION = "repair_authorization"
ESCALATION = "escalation"
