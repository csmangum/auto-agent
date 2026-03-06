"""Documentation and Skills API routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["documentation"])

# Resolve paths relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"
_SKILLS_DIR = _PROJECT_ROOT / "src" / "claim_agent" / "skills"

# Ordered list of documentation pages with display titles
_DOC_PAGES = [
    {"slug": "index", "title": "Overview", "file": "index.md"},
    {"slug": "getting-started", "title": "Getting Started", "file": "getting-started.md"},
    {"slug": "architecture", "title": "Architecture", "file": "architecture.md"},
    {"slug": "crews", "title": "Crews", "file": "crews.md"},
    {"slug": "claim-types", "title": "Claim Types", "file": "claim-types.md"},
    {"slug": "agent-flow", "title": "Agent Flow", "file": "agent-flow.md"},
    {"slug": "tools", "title": "Tools", "file": "tools.md"},
    {"slug": "skills", "title": "Skills", "file": "skills.md"},
    {"slug": "database", "title": "Database", "file": "database.md"},
    {"slug": "configuration", "title": "Configuration", "file": "configuration.md"},
    {"slug": "observability", "title": "Observability", "file": "observability.md"},
    {"slug": "rag", "title": "RAG", "file": "rag.md"},
    {"slug": "mcp-server", "title": "MCP Server", "file": "mcp-server.md"},
    {"slug": "evaluation-results", "title": "Evaluation Results", "file": "evaluation-results.md"},
]

# Skill groupings by workflow
_SKILL_GROUPS = {
    "Core Routing": ["router"],
    "New Claim Workflow": ["intake", "policy_checker", "assignment"],
    "Duplicate Detection": ["search", "similarity", "resolution"],
    "Fraud Detection": ["pattern_analysis", "cross_reference", "fraud_assessment"],
    "Total Loss": ["damage_assessor", "valuation", "payout", "settlement"],
    "Partial Loss": [
        "partial_loss_damage_assessor",
        "repair_estimator",
        "repair_shop_coordinator",
        "parts_ordering",
        "repair_authorization",
    ],
    "Escalation": ["escalation"],
}


def _parse_skill_sections(content: str) -> dict:
    """Parse role, goal, backstory from skill markdown."""
    import re

    result = {}
    for section in ("Role", "Goal", "Backstory"):
        pattern = rf"## {section}\s*\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            result[section.lower()] = match.group(1).strip()
    return result


@router.get("/docs")
async def list_docs():
    """List all available documentation pages."""
    pages = []
    for page in _DOC_PAGES:
        file_path = _DOCS_DIR / page["file"]
        pages.append({
            "slug": page["slug"],
            "title": page["title"],
            "available": file_path.exists(),
        })
    return {"pages": pages}


@router.get("/docs/{slug}")
async def get_doc(slug: str):
    """Get markdown content for a documentation page."""
    # Find the page config
    page_config = None
    for page in _DOC_PAGES:
        if page["slug"] == slug:
            page_config = page
            break

    if page_config is None:
        raise HTTPException(status_code=404, detail=f"Documentation page not found: {slug}")

    file_path = _DOCS_DIR / page_config["file"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Documentation file not found: {page_config['file']}")

    content = file_path.read_text(encoding="utf-8")
    return {
        "slug": slug,
        "title": page_config["title"],
        "content": content,
    }


@router.get("/skills")
async def list_skills():
    """List all agent skills grouped by workflow."""
    groups = {}
    for group_name, skill_names in _SKILL_GROUPS.items():
        skills = []
        for name in skill_names:
            skill_path = _SKILLS_DIR / f"{name}.md"
            if skill_path.exists():
                content = skill_path.read_text(encoding="utf-8")
                sections = _parse_skill_sections(content)
                skills.append({
                    "name": name,
                    "role": sections.get("role", name.replace("_", " ").title()),
                    "goal": sections.get("goal", ""),
                })
            else:
                skills.append({
                    "name": name,
                    "role": name.replace("_", " ").title(),
                    "goal": "Skill file not found",
                })
        groups[group_name] = skills

    return {"groups": groups}


@router.get("/skills/{name}")
async def get_skill(name: str):
    """Get full content for an agent skill."""
    skill_path = _SKILLS_DIR / f"{name}.md"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")

    content = skill_path.read_text(encoding="utf-8")
    sections = _parse_skill_sections(content)

    return {
        "name": name,
        "role": sections.get("role", name.replace("_", " ").title()),
        "goal": sections.get("goal", ""),
        "backstory": sections.get("backstory", ""),
        "content": content,
    }
