"""Mock Crew: simulate external interactions for testing.

Provides mock claimant, image generator, vision analysis, claim generator,
and other third-party simulators to enable E2E testing without real services.
"""

from claim_agent.config.settings_model import ResponseStrategy, ThirdPartyOutcome
from claim_agent.mock_crew.claim_generator import generate_claim_from_prompt
from claim_agent.mock_crew.claimant import generate_claim_input, respond_to_message
from claim_agent.mock_crew.document_generator import generate_damage_photo_url, generate_repair_estimate
from claim_agent.mock_crew.image_generator import generate_damage_image
from claim_agent.mock_crew.notifier import clear_all_pending_mock_responses, get_pending_mock_responses
from claim_agent.mock_crew.repair_shop import (
    clear_all_pending_repair_shop_responses,
    get_pending_repair_shop_responses,
    mock_notify_repair_shop,
)
from claim_agent.mock_crew.third_party import mock_send_demand_letter
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock
from claim_agent.mock_crew.webhook import (
    capture_webhook,
    clear_captured_webhooks,
    get_captured_webhooks,
)

__all__ = [
    "ResponseStrategy",
    "ThirdPartyOutcome",
    "analyze_damage_photo_mock",
    "capture_webhook",
    "clear_all_pending_mock_responses",
    "clear_all_pending_repair_shop_responses",
    "clear_captured_webhooks",
    "generate_claim_from_prompt",
    "generate_claim_input",
    "generate_damage_image",
    "generate_damage_photo_url",
    "generate_repair_estimate",
    "get_captured_webhooks",
    "get_pending_mock_responses",
    "get_pending_repair_shop_responses",
    "mock_notify_repair_shop",
    "mock_send_demand_letter",
    "respond_to_message",
]
