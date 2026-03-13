"""Mock Crew: simulate external interactions for testing.

Provides mock claimant, image generator, vision analysis, and other
third-party simulators to enable E2E testing without real services.
"""

from claim_agent.mock_crew.image_generator import generate_damage_image

__all__ = [
    "generate_damage_image",
]
