"""Mock Crew: simulate external interactions for testing.

Provides mock claimant, image generator, vision analysis, and other
third-party simulators to enable E2E testing without real services.
"""

from claim_agent.mock_crew.image_generator import generate_damage_image
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock

__all__ = [
    "analyze_damage_photo_mock",
    "generate_damage_image",
]
