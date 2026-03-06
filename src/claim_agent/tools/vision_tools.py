"""Vision model tools for damage photo analysis."""

from crewai.tools import tool

from claim_agent.tools.logic import analyze_damage_photo_impl


@tool("Analyze damage photo")
def analyze_damage_photo(image_url: str, damage_description: str | None = None) -> str:
    """Analyze a vehicle damage photo using a vision model.

    Use this when the claim has photo attachments and you need to assess damage severity,
    identify parts affected, or verify consistency with the claimant's description.

    Args:
        image_url: URL to the damage photo (file://, https://, or data URL).
        damage_description: Optional text description to check consistency against.

    Returns:
        JSON with severity, parts_affected, consistency_with_description, notes.
    """
    return analyze_damage_photo_impl(image_url, damage_description)
