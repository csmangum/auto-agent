"""Follow-up message repository: CRUD for follow_up_messages table."""

import json
from typing import Any

from sqlalchemy import text

from claim_agent.db.audit_events import (
    ACTOR_WORKFLOW,
    AUDIT_EVENT_FOLLOW_UP_RESPONSE,
    AUDIT_EVENT_FOLLOW_UP_SENT,
)
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import sanitize_note


class FollowUpRepository:
    """Repository for follow-up message persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def create_follow_up_message(
        self,
        claim_id: str,
        user_type: str,
        message_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        topic: str | None = None,
    ) -> int:
        """Create a follow-up message record. Returns the message id.

        Raises ClaimNotFoundError if claim does not exist.
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO follow_up_messages (claim_id, user_type, message_content, status, actor_id, topic)
                VALUES (:claim_id, :user_type, :message_content, 'pending', :actor_id, :topic)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "user_type": user_type,
                    "message_content": sanitize_note(message_content),
                    "actor_id": actor_id,
                    "topic": topic,
                },
            )
            row = result.fetchone()
            msg_id = row[0] if row else 0
        return int(msg_id)

    def mark_follow_up_sent(self, message_id: int) -> None:
        """Mark a follow-up message as sent (status=sent) and log audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT claim_id, user_type, actor_id FROM follow_up_messages WHERE id = :message_id"
                ),
                {"message_id": message_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            row_d = row_to_dict(row)
            claim_id = row_d["claim_id"]
            user_type = row_d["user_type"]
            actor_id = row_d["actor_id"]
            conn.execute(
                text("UPDATE follow_up_messages SET status = 'sent' WHERE id = :message_id"),
                {"message_id": message_id},
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_FOLLOW_UP_SENT,
                    "details": details,
                    "actor_id": actor_id,
                },
            )

    def record_follow_up_response(
        self,
        message_id: int,
        response_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        expected_claim_id: str | None = None,
    ) -> None:
        """Record a user response to a follow-up message. Updates status to responded and logs audit.

        Args:
            message_id: The follow-up message ID.
            response_content: The user's response text.
            actor_id: Who recorded the response.
            expected_claim_id: If provided, raises ValueError when the message belongs to a
                different claim (prevents cross-claim response injection).
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT claim_id, user_type FROM follow_up_messages WHERE id = :message_id"),
                {"message_id": message_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            row_d = row_to_dict(row)
            claim_id = row_d["claim_id"]
            user_type = row_d["user_type"]
            if expected_claim_id is not None and claim_id != expected_claim_id:
                raise ValueError(
                    f"Follow-up message {message_id} does not belong to claim {expected_claim_id}"
                )
            conn.execute(
                text("""
                UPDATE follow_up_messages
                SET status = 'responded', response_content = :response_content, responded_at = CURRENT_TIMESTAMP
                WHERE id = :message_id
                """),
                {"response_content": sanitize_note(response_content), "message_id": message_id},
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_FOLLOW_UP_RESPONSE,
                    "details": details,
                    "actor_id": actor_id,
                },
            )

    def get_pending_follow_ups(
        self,
        claim_id: str,
        *,
        user_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending or sent (not yet responded) follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if user_type:
                rows = conn.execute(
                    text("""
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at, topic
                    FROM follow_up_messages
                    WHERE claim_id = :claim_id AND user_type = :user_type AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """),
                    {"claim_id": claim_id, "user_type": user_type},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("""
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at, topic
                    FROM follow_up_messages
                    WHERE claim_id = :claim_id AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """),
                    {"claim_id": claim_id},
                ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_follow_up_messages(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                text("""
                SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at, topic
                FROM follow_up_messages
                WHERE claim_id = :claim_id
                ORDER BY created_at DESC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_follow_up_message_by_id(self, message_id: int) -> dict[str, Any] | None:
        """Return a single follow-up message row by id, or None if missing."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at, topic
                FROM follow_up_messages
                WHERE id = :message_id
                """),
                {"message_id": message_id},
            ).fetchone()
        return row_to_dict(row) if row else None
