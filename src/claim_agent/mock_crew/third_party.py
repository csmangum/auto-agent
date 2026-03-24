"""Mock Third Party: intercept demand-letter dispatch during testing.

When ``MOCK_CREW_ENABLED=true`` and ``MOCK_THIRD_PARTY_ENABLED=true``, calls to
:func:`claim_agent.tools.subrogation_logic.send_demand_letter_impl` are
intercepted and return a configurable third-party response instead of the
default stub behaviour.

The configurable outcome (``MOCK_THIRD_PARTY_OUTCOME``) determines the response:

- ``accept``    – third party accepts the demand and agrees to pay.
- ``reject``    – third party rejects the demand.
- ``negotiate`` – third party counters with a partial offer.

This lets E2E tests exercise the full subrogation workflow (accept path, reject
path, negotiation path) without any real outbound HTTP or external party.
"""

import logging
from typing import Any

from claim_agent.config.settings import get_mock_third_party_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Outcome → response template mapping
# ---------------------------------------------------------------------------

_OUTCOME_RESPONSES: dict[str, dict[str, Any]] = {
    "accept": {
        "third_party_response": "accept",
        "third_party_message": "Demand accepted. Full payment will be remitted within 30 days.",
        "counter_amount": None,
    },
    "reject": {
        "third_party_response": "reject",
        "third_party_message": "Demand rejected. Liability is disputed.",
        "counter_amount": None,
    },
    "negotiate": {
        "third_party_response": "negotiate",
        "third_party_message": "Counter-offer: partial settlement at 60% of demanded amount.",
        "counter_amount_ratio": 0.6,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mock_send_demand_letter(
    case_id: str,
    claim_id: str,
    amount_sought: float,
    third_party_info: str = "",
) -> dict[str, Any]:
    """Return a mock third-party response to a demand letter.

    Called by :func:`claim_agent.tools.subrogation_logic.send_demand_letter_impl`
    when both ``MOCK_CREW_ENABLED`` and ``MOCK_THIRD_PARTY_ENABLED`` are true.

    Args:
        case_id: Subrogation case identifier.
        claim_id: Claim identifier.
        amount_sought: Dollar amount in the demand letter.
        third_party_info: Optional context about the third party.

    Returns:
        Dict with demand letter confirmation fields plus third-party response
        fields (``third_party_response``, ``third_party_message``, and
        optionally ``counter_amount``).
    """
    cfg = get_mock_third_party_config()
    outcome = cfg["outcome"]

    template = _OUTCOME_RESPONSES.get(outcome, _OUTCOME_RESPONSES["accept"])
    response: dict[str, Any] = dict(template)

    # Resolve counter_amount from ratio if applicable
    if "counter_amount_ratio" in response:
        ratio = response.pop("counter_amount_ratio")
        response["counter_amount"] = round(amount_sought * ratio, 2)

    logger.info(
        "MockThirdParty: demand letter intercepted case_id=%s claim_id=%s "
        "amount_sought=%.2f outcome=%s",
        case_id,
        claim_id,
        amount_sought,
        outcome,
    )

    return response
