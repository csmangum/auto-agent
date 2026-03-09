"""Claim notes tools for cross-crew communication.

Agents and crews can add and read notes on a claim, enabling downstream
crews to benefit from observations made by earlier crews.
"""

import json
import logging

from crewai.tools import tool

from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError

logger = logging.getLogger(__name__)


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


@tool("Get Claim Notes")
def get_claim_notes(claim_id: str) -> str:
    """Retrieve all notes for a claim (for use by downstream crews).

    Notes are ordered by created_at. Use this to read observations and
    context added by earlier crews (e.g., New Claim, Fraud, Total Loss)
    before making decisions.

    Args:
        claim_id: The claim ID (e.g., from claim_data).

    Returns:
        JSON array of notes with id, note, actor_id, created_at.
    """
    claim_id = str(claim_id).strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required"})
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
        return json.dumps(out)
    except ClaimNotFoundError:
        return json.dumps({"error": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error retrieving notes for claim %s", claim_id)
        return json.dumps({"error": "An unexpected error occurred while retrieving notes"})
