"""Mock Crew: simulate external interactions for testing.

Provides mock claimant, image generator, vision analysis, claim generator,
and other third-party simulators to enable E2E testing without real services.
"""

from claim_agent.config.settings_model import ResponseStrategy
from claim_agent.mock_crew.claim_generator import generate_claim_from_prompt
from claim_agent.mock_crew.claimant import generate_claim_input, respond_to_message
from claim_agent.mock_crew.document_generator import generate_damage_photo_url, generate_repair_estimate
from claim_agent.mock_crew.image_generator import generate_damage_image
from claim_agent.mock_crew.notifier import clear_all_pending_mock_responses, get_pending_mock_responses
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock

__all__ = [
    "ResponseStrategy",
    "analyze_damage_photo_mock",
    "clear_all_pending_mock_responses",
    "generate_claim_from_prompt",
    "generate_claim_input",
    "generate_damage_image",
    "generate_damage_photo_url",
    "generate_repair_estimate",
    "get_pending_mock_responses",
    "respond_to_message",
]
