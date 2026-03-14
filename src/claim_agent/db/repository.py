"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only: it only inserts new
audit entries and does not perform UPDATE or DELETE operations on that table.
"""

import json
import uuid
from typing import Any

from claim_agent.models.claim import Attachment

from claim_agent.db.audit_events import (
    ACTOR_RETENTION,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_ASSIGN,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
    AUDIT_EVENT_CLAIM_REVIEW,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_ESCALATE_TO_SIU,
    AUDIT_EVENT_FOLLOW_UP_RESPONSE,
    AUDIT_EVENT_FOLLOW_UP_SENT,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REQUEST_INFO,
    AUDIT_EVENT_RETENTION,
    AUDIT_EVENT_SIU_CASE_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
)
from claim_agent.db.constants import (
    STATUS_ARCHIVED,
    STATUS_DENIED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.db.database import get_connection
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import sanitize_actor_id, sanitize_note
from claim_agent.events import ClaimEvent, emit_claim_event
from claim_agent.models.claim import ClaimInput


def _generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class ClaimRepository:
    """Repository for claim persistence and audit logging."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def create_claim(
        self,
        claim_input: ClaimInput,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> str:
        """Insert new claim, generate ID, log 'created' audit entry. Returns claim_id."""
        claim_id = _generate_claim_id()
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in claim_input.attachments],
            default=str,
        )
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, status, attachments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    claim_input.policy_number,
                    claim_input.vin,
                    claim_input.vehicle_year,
                    claim_input.vehicle_make,
                    claim_input.vehicle_model,
                    claim_input.incident_date.isoformat(),
                    claim_input.incident_description,
                    claim_input.damage_description,
                    claim_input.estimated_damage,
                    None,
                    STATUS_PENDING,
                    attachments_json,
                ),
            )
            after_state = json.dumps({"status": STATUS_PENDING, "claim_type": None, "payout_amount": None})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_CREATED, STATUS_PENDING, "Claim record created", actor_id, after_state),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_PENDING, summary="Claim submitted")
        )
        return claim_id

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch claim by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_claim_status(
        self,
        claim_id: str,
        new_status: str,
        details: str | None = None,
        claim_type: str | None = None,
        payout_amount: float | None = None,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Update status, optionally claim_type and payout_amount; log state change to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]

            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": new_status,
                "claim_type": claim_type if claim_type is not None else old_claim_type,
                "payout_amount": payout_amount if payout_amount is not None else old_payout,
            }

            # Explicit parameterized queries (no dynamic SQL)
            if claim_type is not None and payout_amount is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, claim_type = ?, payout_amount = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_type, payout_amount, claim_id),
                )
            elif claim_type is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, claim_type = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_type, claim_id),
                )
            elif payout_amount is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, payout_amount = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, payout_amount, claim_id),
                )
            else:
                conn.execute(
                    """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_id),
                )

            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_STATUS_CHANGE,
                    old_status,
                    new_status,
                    details or "",
                    actor_id,
                    json.dumps(before_state),
                    json.dumps(after_state),
                ),
            )

        final_claim_type = claim_type if claim_type is not None else old_claim_type
        final_payout = payout_amount if payout_amount is not None else old_payout
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=new_status,
                summary=details,
                claim_type=final_claim_type,
                payout_amount=final_payout,
            )
        )

    def save_workflow_result(
        self,
        claim_id: str,
        claim_type: str,
        router_output: str,
        workflow_output: str,
    ) -> None:
        """Save workflow run result to workflow_runs."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, claim_type, router_output, workflow_output),
            )

    def get_workflow_runs(
        self,
        claim_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch workflow run records for a claim, most recent first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT claim_type, router_output, workflow_output, created_at
                FROM workflow_runs
                WHERE claim_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (claim_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_task_checkpoint(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_key: str,
        output: str,
    ) -> None:
        """Persist a stage checkpoint. Replaces any existing checkpoint for the same key."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_checkpoints
                    (claim_id, workflow_run_id, stage_key, output)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, workflow_run_id, stage_key, output),
            )

    def get_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
    ) -> dict[str, str]:
        """Load all checkpoints for a workflow run. Returns {stage_key: output_json}."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT stage_key, output FROM task_checkpoints
                WHERE claim_id = ? AND workflow_run_id = ?
                """,
                (claim_id, workflow_run_id),
            ).fetchall()
        return {row["stage_key"]: row["output"] for row in rows}

    def delete_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_keys: list[str] | None = None,
    ) -> None:
        """Delete checkpoints. If stage_keys given, only those; if None, all for the run.
        Empty list deletes nothing."""
        if stage_keys is not None and not stage_keys:
            return
        with get_connection(self._db_path) as conn:
            if stage_keys is not None:
                placeholders = ",".join("?" for _ in stage_keys)
                conn.execute(
                    f"""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = ? AND workflow_run_id = ? AND stage_key IN ({placeholders})
                    """,
                    [claim_id, workflow_run_id, *stage_keys],
                )
            else:
                conn.execute(
                    """
                    DELETE FROM task_checkpoints
                    WHERE claim_id = ? AND workflow_run_id = ?
                    """,
                    (claim_id, workflow_run_id),
                )

    def get_latest_checkpointed_run_id(self, claim_id: str) -> str | None:
        """Return the most recent workflow_run_id that has checkpoints for this claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT workflow_run_id FROM task_checkpoints
                WHERE claim_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
        return row["workflow_run_id"] if row else None

    def update_claim_attachments(
        self,
        claim_id: str,
        attachments: list[Attachment],
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Update attachments for a claim (e.g. after file upload). Logs an audit entry."""
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in attachments],
            default=str,
        )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT attachments FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            before_attachments = row["attachments"] or "[]"
            cursor = conn.execute(
                "UPDATE claims SET attachments = ?, updated_at = datetime('now') WHERE id = ?",
                (attachments_json, claim_id),
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            before_state = before_attachments  # already a serialized JSON array
            after_state = attachments_json      # already a serialized JSON array
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_ATTACHMENTS_UPDATED,
                    f"Attachments updated: {len(attachments)} file(s)",
                    actor_id,
                    before_state,
                    after_state,
                ),
            )

    def get_claim_history(
        self,
        claim_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get audit log entries for a claim with optional pagination.

        Returns:
            (rows, total_count). When limit is None, returns all rows.
        """
        with get_connection(self._db_path) as conn:
            query = """
                SELECT id, claim_id, action, old_status, new_status, details,
                       actor_id, before_state, after_state, created_at
                FROM claim_audit_log
                WHERE claim_id = ?
                ORDER BY id ASC
            """
            params: tuple[Any, ...] = (claim_id,)
            if limit is not None:
                # Only run COUNT(*) when paginating; fetching a page doesn't
                # give us the total for free.
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM claim_audit_log WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                total = count_row[0] if count_row else 0
                query += " LIMIT ? OFFSET ?"
                params = (claim_id, limit, offset)
            rows = conn.execute(query, params).fetchall()
        result = [dict(r) for r in rows]
        if limit is None:
            # All rows fetched; total is simply the list length — no extra query needed.
            total = len(result)
        return result, total

    def record_claim_review(
        self,
        claim_id: str,
        report_json: str,
        actor_id: str,
    ) -> None:
        """Record a claim review result in the audit log. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_CLAIM_REVIEW, report_json, sanitize_actor_id(actor_id)),
            )

    def add_note(
        self,
        claim_id: str,
        note: str,
        actor_id: str,
    ) -> None:
        """Append a note to a claim. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_notes (claim_id, note, actor_id)
                VALUES (?, ?, ?)
                """,
                (claim_id, sanitize_note(note), sanitize_actor_id(actor_id)),
            )

    def get_notes(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all notes for a claim, ordered by created_at ascending. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                """
                SELECT id, claim_id, note, actor_id, created_at
                FROM claim_notes
                WHERE claim_id = ?
                ORDER BY created_at ASC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_follow_up_message(
        self,
        claim_id: str,
        user_type: str,
        message_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> int:
        """Create a follow-up message record. Returns the message id. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            cursor = conn.execute(
                """
                INSERT INTO follow_up_messages (claim_id, user_type, message_content, status, actor_id)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (claim_id, user_type, sanitize_note(message_content), actor_id),
            )
            msg_id = cursor.lastrowid
        return int(msg_id)

    def mark_follow_up_sent(self, message_id: int) -> None:
        """Mark a follow-up message as sent (status=sent) and log audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT claim_id, user_type, actor_id FROM follow_up_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            claim_id = row["claim_id"]
            user_type = row["user_type"]
            actor_id = row["actor_id"]
            conn.execute(
                "UPDATE follow_up_messages SET status = 'sent' WHERE id = ?",
                (message_id,),
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_FOLLOW_UP_SENT, details, actor_id),
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
                "SELECT claim_id, user_type FROM follow_up_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            claim_id = row["claim_id"]
            user_type = row["user_type"]
            if expected_claim_id is not None and claim_id != expected_claim_id:
                raise ValueError(
                    f"Follow-up message {message_id} does not belong to claim {expected_claim_id}"
                )
            conn.execute(
                """
                UPDATE follow_up_messages
                SET status = 'responded', response_content = ?, responded_at = datetime('now')
                WHERE id = ?
                """,
                (sanitize_note(response_content), message_id),
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_FOLLOW_UP_RESPONSE, details, actor_id),
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
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if user_type:
                rows = conn.execute(
                    """
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = ? AND user_type = ? AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """,
                    (claim_id, user_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = ? AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """,
                    (claim_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_follow_up_messages(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                """
                SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                FROM follow_up_messages
                WHERE claim_id = ?
                ORDER BY created_at DESC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_audit_entry(
        self,
        claim_id: str,
        action: str,
        *,
        old_status: str | None = None,
        new_status: str | None = None,
        details: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
        before_state: str | None = None,
        after_state: str | None = None,
    ) -> None:
        """Insert an audit log entry without changing claim status."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, action, old_status, new_status, details or "", actor_id, before_state, after_state),
            )

    def update_claim_siu_case_id(
        self,
        claim_id: str,
        siu_case_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Store SIU case ID on claim and log siu_case_created audit entry.

        Calling this method overwrites any existing siu_case_id on the claim and
        always appends a new siu_case_created audit log entry. Retrying this call
        after a transient failure will therefore produce multiple
        siu_case_created entries for the same claim in claim_audit_log.
        """
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE claims SET siu_case_id = ?, updated_at = datetime('now') WHERE id = ?
                """,
                (siu_case_id, claim_id),
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_SIU_CASE_CREATED, f"SIU case created: {siu_case_id}", actor_id),
            )

    def update_claim_review_metadata(
        self,
        claim_id: str,
        *,
        priority: str | None = None,
        due_at: str | None = None,
        review_started_at: str | None = None,
    ) -> None:
        """Update review metadata (priority, due_at, review_started_at) on a claim."""
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if due_at is not None:
            updates.append("due_at = ?")
            params.append(due_at)
        if review_started_at is not None:
            updates.append("review_started_at = ?")
            params.append(review_started_at)
        if not params:
            return
        params.append(claim_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                f"UPDATE claims SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def assign_claim(
        self,
        claim_id: str,
        assignee_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Assign claim to an adjuster. Sets review_started_at if not already set.
        Only claims with status needs_review can be assigned."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT assignee, status FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if row["status"] != STATUS_NEEDS_REVIEW:
                raise ValueError(
                    f"Claim {claim_id} is not in needs_review (status={row['status']}); "
                    "only claims in the review queue can be assigned"
                )
            old_assignee = row["assignee"]
            conn.execute(
                """
                UPDATE claims SET assignee = ?,
                    review_started_at = COALESCE(review_started_at, datetime('now')),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (assignee_id, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_ASSIGN,
                    f"Assigned to {assignee_id}",
                    actor_id,
                    json.dumps({"assignee": old_assignee}),
                    json.dumps({"assignee": assignee_id}),
                ),
            )

    def _ensure_claim_needs_review(self, conn: Any, claim_id: str) -> Any:
        """Fetch claim row and ensure status is needs_review. Raises if not found or wrong status."""
        row = conn.execute(
            "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        if row["status"] != STATUS_NEEDS_REVIEW:
            raise ValueError(
                f"Claim {claim_id} is not in needs_review (status={row['status']}); "
                "adjuster actions only apply to claims in the review queue"
            )
        return row

    def approve_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Insert approval audit. Caller must invoke run_claim_workflow."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_APPROVAL, row["status"], None, "Approved for continued processing", actor_id, None, None),
            )

    def reject_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        reason: str | None = None,
    ) -> None:
        """Reject claim: set status to denied, insert audit, emit event."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_DENIED, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_DENIED, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_DENIED, reason or "Rejected by adjuster", actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_REJECTION, old_status, STATUS_DENIED, reason or "", actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_DENIED, summary=reason or "Rejected by adjuster")
        )

    def request_info_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        note: str | None = None,
    ) -> None:
        """Request more information: set status to pending_info, insert audit, emit event."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_PENDING_INFO, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_PENDING_INFO, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_PENDING_INFO, note or "Requested more information", actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_REQUEST_INFO, old_status, STATUS_PENDING_INFO, note or "", actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_PENDING_INFO, summary=note or "Requested more information")
        )

    def escalate_claim_to_siu(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Escalate to SIU: set status to under_investigation, insert audit, emit event."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_UNDER_INVESTIGATION, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_UNDER_INVESTIGATION, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_UNDER_INVESTIGATION, "Escalated to SIU", actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_ESCALATE_TO_SIU, old_status, STATUS_UNDER_INVESTIGATION, "Referred to Special Investigations Unit", actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_UNDER_INVESTIGATION, summary="Escalated to SIU")
        )

    def list_claims_needing_review(
        self,
        *,
        assignee: str | None = None,
        priority: str | None = None,
        older_than_hours: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List claims with status needs_review. Returns (claims, total_count)."""
        conditions = ["status = ?"]
        params: list[Any] = [STATUS_NEEDS_REVIEW]
        if assignee is not None:
            conditions.append("assignee = ?")
            params.append(assignee)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        if older_than_hours is not None:
            if older_than_hours < 0:
                raise ValueError("older_than_hours must be non-negative")
            conditions.append("review_started_at IS NOT NULL AND datetime(review_started_at) <= datetime('now', ?)")
            params.append(f"-{older_than_hours} hours")
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM claims WHERE {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"SELECT * FROM claims WHERE {where} ORDER BY "
                "CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, "
                "COALESCE(due_at, '9999-12-31') ASC, created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def search_claims(
        self,
        vin: str | None = None,
        incident_date: str | None = None,
        policy_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claims by VIN, policy_number and/or incident_date. All optional; if all None, returns []."""
        vin = None if vin is None else str(vin).strip()
        incident_date = None if incident_date is None else str(incident_date).strip()
        policy_number = None if policy_number is None else str(policy_number).strip()
        if not vin and not incident_date and not policy_number:
            return []
        with get_connection(self._db_path) as conn:
            conditions = []
            params = []
            if vin:
                conditions.append("vin = ?")
                params.append(vin)
            if incident_date:
                conditions.append("incident_date = ?")
                params.append(incident_date)
            if policy_number:
                conditions.append("policy_number = ?")
                params.append(policy_number)
            where_clause = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM claims WHERE {where_clause}",
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_claims_for_retention(
        self,
        retention_period_years: int,
    ) -> list[dict[str, Any]]:
        """List claims older than retention period that are not yet archived.

        Uses created_at for cutoff. Excludes claims with status archived
        or a non-null archived_at.
        """
        if retention_period_years < 0:
            raise ValueError("retention_period_years must be non-negative")
        cutoff = f"-{retention_period_years} years"
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM claims
                WHERE datetime(created_at) <= datetime('now', ?)
                  AND archived_at IS NULL
                  AND status != ?
                ORDER BY created_at ASC
                """,
                (cutoff, STATUS_ARCHIVED),
            ).fetchall()
        return [dict(r) for r in rows]

    def archive_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Archive a claim (soft delete for retention). Sets archived_at and status=archived."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            if old_status == STATUS_ARCHIVED:
                return
            conn.execute(
                """
                UPDATE claims SET status = ?, archived_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?
                """,
                (STATUS_ARCHIVED, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_RETENTION,
                    old_status,
                    STATUS_ARCHIVED,
                    "Archived for retention (claim older than retention period)",
                    actor_id,
                ),
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_ARCHIVED,
                summary="Archived for retention",
                claim_type=row["claim_type"],
                payout_amount=row["payout_amount"],
            )
        )
