"""Note repository: CRUD for claim notes."""

from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import sanitize_actor_id, sanitize_note


class NoteRepository:
    """Repository for claim note persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def add_note(
        self,
        claim_id: str,
        note: str,
        actor_id: str,
    ) -> None:
        """Append a note to a claim. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                INSERT INTO claim_notes (claim_id, note, actor_id)
                VALUES (:claim_id, :note, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "note": sanitize_note(note),
                    "actor_id": sanitize_actor_id(actor_id),
                },
            )

    def get_notes(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all notes for a claim, ordered by created_at ascending.

        Raises ClaimNotFoundError if claim does not exist.
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                text("""
                SELECT id, claim_id, note, actor_id, created_at
                FROM claim_notes
                WHERE claim_id = :claim_id
                ORDER BY created_at ASC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]
