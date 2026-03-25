"""Follow-up agent tools: send messages, record responses, check pending."""

import json
import logging

from crewai.tools import tool

from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.user import UserType
from claim_agent.notifications.user import notify_user

logger = logging.getLogger(__name__)

VALID_USER_TYPES = [t.value for t in UserType]

# Claimant portal surfaces tagged follow-ups (e.g. Rental tab). Omit topic for generic messages.
FOLLOW_UP_TOPIC_RENTAL = "rental"
_VALID_FOLLOW_UP_TOPICS = frozenset({FOLLOW_UP_TOPIC_RENTAL})


@tool("Send User Message")
def send_user_message(
    claim_id: str,
    user_type: str,
    message_content: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    identifier: str | None = None,
    topic: str | None = None,
) -> str:
    """Send a follow-up message to a user (claimant, policyholder, repair_shop, etc.).

    Creates a follow-up record, delivers the message via the appropriate channel
    (email, SMS, portal) based on user type, and logs to the audit trail.

    Args:
        claim_id: The claim ID.
        user_type: One of claimant, policyholder, witness, attorney, adjuster,
            repair_shop, siu, other.
        message_content: The message to send (questions, requests, clarifications).
        email: Optional email address for the user (any supported user_type).
        phone: Optional phone number for SMS (any supported user_type).
        identifier: Optional user identifier (e.g., repair shop ID).
        topic: Optional tag for portal grouping. Use "rental" for loss-of-use, rental receipts,
            or rental coordination so the message appears on the claimant portal Rental tab.

    Returns:
        JSON with success (bool), message_id (int), and message or error.
    """
    claim_id = str(claim_id).strip()
    user_type = str(user_type).strip().lower()
    message_content = str(message_content).strip()

    normalized_topic: str | None = None
    if topic is not None:
        t = str(topic).strip().lower()
        if t:
            if t not in _VALID_FOLLOW_UP_TOPICS:
                return json.dumps(
                    {
                        "success": False,
                        "message": (
                            f"topic must be one of: {sorted(_VALID_FOLLOW_UP_TOPICS)} or omitted"
                        ),
                    }
                )
            normalized_topic = t

    if not claim_id:
        return json.dumps({"success": False, "message": "claim_id is required"})
    if not user_type:
        return json.dumps({"success": False, "message": "user_type is required"})
    if not message_content:
        return json.dumps({"success": False, "message": "message_content cannot be empty"})
    if user_type not in VALID_USER_TYPES:
        return json.dumps(
            {"success": False, "message": f"user_type must be one of: {VALID_USER_TYPES}"}
        )

    try:
        repo = ClaimRepository()
        # Resolve contact from claim_parties when not provided (claimant/policyholder)
        if not email and not phone:
            try:
                contact = repo.get_primary_contact_for_user_type(claim_id, user_type)
                if contact:
                    email = contact.get("email") or email
                    phone = contact.get("phone") or phone
            except Exception:
                pass

        msg_id = repo.create_follow_up_message(
            claim_id,
            user_type,
            message_content,
            actor_id="follow_up_agent",
            topic=normalized_topic,
        )

        try:
            delivered = notify_user(
                user_type,
                claim_id,
                message_content,
                email=email,
                phone=phone,
                identifier=identifier or claim_id,
            )
        except Exception:
            logger.exception(
                "Notification delivery failed for claim %s message %s", claim_id, msg_id
            )
            return json.dumps(
                {"success": False, "message": "Notification delivery failed"}
            )

        if not delivered:
            return json.dumps(
                {
                    "success": False,
                    "message": (
                        f"Message not delivered: no contact channel (email/phone) for {user_type}, "
                        "or notifications disabled. Message created but status remains pending."
                    ),
                }
            )

        repo.mark_follow_up_sent(msg_id)

        return json.dumps(
            {
                "success": True,
                "message_id": msg_id,
                "message": f"Follow-up message sent to {user_type}",
            }
        )
    except ClaimNotFoundError:
        return json.dumps({"success": False, "message": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error sending follow-up for claim %s", claim_id)
        return json.dumps(
            {"success": False, "message": "An unexpected error occurred while sending the message"}
        )


@tool("Record User Response")
def record_user_response(
    message_id: int,
    response_content: str,
    *,
    claim_id: str | None = None,
    actor_id: str = "workflow",
) -> str:
    """Record a user's response to a follow-up message.

    When a claimant, repair shop, or other party responds (via webhook, API,
    or manual entry), use this tool to attach the response to the follow-up
    record and update the claim context. Logs to audit trail.

    Args:
        message_id: The follow-up message ID (from send_user_message).
        response_content: The user's response text.
        claim_id: Optional claim ID from claim_data. When provided, validates
            that the message belongs to this claim (defense-in-depth).
        actor_id: Who recorded the response (default: workflow).

    Returns:
        JSON with success (bool) and message or error.
    """
    response_content = str(response_content).strip()
    if not response_content:
        return json.dumps({"success": False, "message": "response_content cannot be empty"})

    # Validate claim_id: if provided, it must not be blank/whitespace.
    expected_claim_id: str | None = None
    if claim_id is not None:
        claim_id_stripped = str(claim_id).strip()
        if not claim_id_stripped:
            return json.dumps(
                {"success": False, "message": "claim_id cannot be blank or whitespace"}
            )
        expected_claim_id = claim_id_stripped

    try:
        repo = ClaimRepository()
        repo.record_follow_up_response(
            message_id,
            response_content,
            actor_id=actor_id,
            expected_claim_id=expected_claim_id,
        )
        return json.dumps(
            {"success": True, "message": "Response recorded"}
        )
    except ValueError as e:
        return json.dumps({"success": False, "message": str(e)})
    except Exception:
        logger.exception("Unexpected error recording response for message %s", message_id)
        return json.dumps(
            {"success": False, "message": "An unexpected error occurred while recording the response"}
        )


@tool("Check Pending Responses")
def check_pending_responses(
    claim_id: str,
    *,
    user_type: str | None = None,
) -> str:
    """Check for pending or sent follow-up messages awaiting response.

    Returns follow-up messages that have been sent but not yet responded to.
    Use this to determine if the workflow should wait for user input or
    proceed with available information.

    Args:
        claim_id: The claim ID.
        user_type: Optional filter by user type (claimant, repair_shop, etc.).

    Returns:
        JSON with pending (list of message objects) and error (null on success).
    """
    claim_id = str(claim_id).strip()
    if not claim_id:
        return json.dumps({"pending": None, "error": "claim_id is required"})

    # Normalize and validate user_type if provided
    normalized_user_type: str | None = None
    if user_type is not None:
        normalized_user_type = str(user_type).strip().lower()
        if not normalized_user_type:
            normalized_user_type = None
        elif normalized_user_type not in VALID_USER_TYPES:
            return json.dumps(
                {
                    "pending": None,
                    "error": f"Invalid user_type: {normalized_user_type!r}. "
                    f"Must be one of: {', '.join(VALID_USER_TYPES)}",
                }
            )

    try:
        repo = ClaimRepository()
        pending = repo.get_pending_follow_ups(claim_id, user_type=normalized_user_type)
        out = [
            {
                "id": p["id"],
                "user_type": p["user_type"],
                "message_content": p["message_content"],
                "status": p["status"],
                "created_at": p["created_at"],
                "topic": p.get("topic"),
            }
            for p in pending
        ]
        return json.dumps({"pending": out, "error": None})
    except ClaimNotFoundError:
        return json.dumps({"pending": None, "error": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error checking pending responses for claim %s", claim_id)
        return json.dumps(
            {"pending": None, "error": "An unexpected error occurred while checking pending responses"}
        )
