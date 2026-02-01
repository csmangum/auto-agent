"""Skills module for loading agent skill definitions from markdown files."""

import re
from pathlib import Path
from typing import Optional


SKILLS_DIR = Path(__file__).parent


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
