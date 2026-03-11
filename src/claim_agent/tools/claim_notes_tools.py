"""Claim notes tools for cross-crew communication.

Agents and crews can add and read notes on a claim, enabling downstream
crews to benefit from observations made by earlier crews.
"""

import json
import logging

from crewai.tools import tool

from claim_agent.config import get_settings
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


@tool("Add Claim Note")
def add_claim_note(claim_id: str, note: str, actor_id: str) -> str:
    """Append a note to a claim for cross-crew communication.

    Use when you want to record an observation, finding, or context that
    downstream crews (e.g., Settlement, Fraud) should see. The actor_id
    identifies who wrote the note (e.g., 'New Claim', 'Fraud Detection',
    'Total Loss', or a specific agent name).

    Args:
        claim_id: The claim ID (e.g., from claim_data).
        note: The note content to append.
        actor_id: Identifier for who wrote the note (crew name, agent, or 'workflow').

    Returns:
        JSON with success (bool) and message.
    """
    claim_id = str(claim_id).strip()
    note = str(note).strip()
    actor_id = str(actor_id).strip()
    if not claim_id:
        return json.dumps({"success": False, "message": "claim_id is required"})
    if not note:
        return json.dumps({"success": False, "message": "note cannot be empty"})
    if not actor_id:
        return json.dumps({"success": False, "message": "actor_id is required"})
    try:
        ClaimRepository().add_note(claim_id, note, actor_id)
        return json.dumps({"success": True, "message": "Note added"})
    except ClaimNotFoundError:
        return json.dumps({"success": False, "message": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error adding note to claim %s", claim_id)
        return json.dumps({"success": False, "message": "An unexpected error occurred while adding the note"})


@tool("Add After-Action Note")
def add_after_action_note(claim_id: str, note: str) -> str:
    """Append the after-action summary note to a claim with token-budget enforcement.

    This tool is specifically for the After-Action Summary agent. The note is
    truncated to the configured AFTER_ACTION_NOTE_MAX_TOKENS limit to ensure
    it fits in downstream LLM context windows when used as claim state.

    Args:
        claim_id: The claim ID (e.g., from claim_data).
        note: The after-action summary content.

    Returns:
        JSON with success (bool), message, and truncated (bool) indicating
        whether the note was trimmed to fit the token budget.
    """
    claim_id = str(claim_id).strip()
    note = str(note).strip()
    if not claim_id:
        return json.dumps({"success": False, "message": "claim_id is required", "truncated": False})
    if not note:
        return json.dumps({"success": False, "message": "note cannot be empty", "truncated": False})

    max_tokens = get_settings().after_action_note_max_tokens
    max_chars = max_tokens * CHARS_PER_TOKEN
    truncated = len(note) > max_chars
    if truncated:
        note = note[:max_chars].rsplit("\n", 1)[0]
        logger.info(
            "After-action note truncated to %d chars (~%d tokens) for claim %s",
            len(note), max_tokens, claim_id,
        )

    try:
        ClaimRepository().add_note(claim_id, note, "After-Action Summary")
        msg = "After-action note added"
        if truncated:
            msg += f" (truncated to ~{max_tokens} tokens)"
        return json.dumps({"success": True, "message": msg, "truncated": truncated})
    except ClaimNotFoundError:
        return json.dumps({"success": False, "message": f"Claim not found: {claim_id}", "truncated": False})
    except Exception:
        logger.exception("Unexpected error adding after-action note to claim %s", claim_id)
        return json.dumps({"success": False, "message": "An unexpected error occurred while adding the note", "truncated": False})


@tool("Get Claim Notes")
def get_claim_notes(claim_id: str) -> str:
    """Retrieve all notes for a claim (for use by downstream crews).

    Notes are ordered by created_at. Use this to read observations and
    context added by earlier crews (e.g., New Claim, Fraud, Total Loss)
    before making decisions.

    Args:
        claim_id: The claim ID (e.g., from claim_data).

    Returns:
        JSON with notes (list) and error (null on success, string on failure).
    """
    claim_id = str(claim_id).strip()
    if not claim_id:
        return json.dumps({"notes": None, "error": "claim_id is required"})
    try:
        notes = ClaimRepository().get_notes(claim_id)
        out = [
            {
                "id": n.get("id"),
                "note": n.get("note"),
                "actor_id": n.get("actor_id"),
                "created_at": n.get("created_at"),
            }
            for n in notes
        ]
        return json.dumps({"notes": out, "error": None})
    except ClaimNotFoundError:
        return json.dumps({"notes": None, "error": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error retrieving notes for claim %s", claim_id)
        return json.dumps({"notes": None, "error": "An unexpected error occurred while retrieving notes"})
