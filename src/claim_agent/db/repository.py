"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only: it only inserts new
audit entries and does not perform UPDATE or DELETE operations on that table.
"""

import json
import uuid
from typing import Any

from claim_agent.models.claim import Attachment

from claim_agent.db.audit_events import (
    ACTOR_WORKFLOW,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_ASSIGN,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_ESCALATE_TO_SIU,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REQUEST_INFO,
    AUDIT_EVENT_STATUS_CHANGE,
)
from claim_agent.db.constants import (
    STATUS_DENIED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.db.database import get_connection
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
                raise ValueError(f"Claim not found: {claim_id}")
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
                raise ValueError(f"Claim not found: {claim_id}")
            before_attachments = row["attachments"] or "[]"
            cursor = conn.execute(
                "UPDATE claims SET attachments = ?, updated_at = datetime('now') WHERE id = ?",
                (attachments_json, claim_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Claim not found: {claim_id}")
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

    def get_claim_history(self, claim_id: str) -> list[dict[str, Any]]:
        """Get audit log entries for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, claim_id, action, old_status, new_status, details,
                       actor_id, before_state, after_state, created_at
                FROM claim_audit_log
                WHERE claim_id = ?
                ORDER BY id ASC
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
        """Assign claim to an adjuster. Sets review_started_at if not already set."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT assignee FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Claim not found: {claim_id}")
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

    def perform_adjuster_action(
        self,
        claim_id: str,
        action: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        reason: str | None = None,
        note: str | None = None,
    ) -> None:
        """Perform adjuster action: approve, reject, request_info, escalate_to_siu.

        - approve: inserts approval audit; caller must invoke run_claim_workflow
        - reject: sets status to denied, inserts rejection audit
        - request_info: sets status to pending_info, inserts request_info audit
        - escalate_to_siu: sets status to under_investigation, inserts escalate_to_siu audit
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Claim not found: {claim_id}")
            old_status = row["status"]

            if action == "approve":
                self.insert_audit_entry(
                    claim_id,
                    AUDIT_EVENT_APPROVAL,
                    old_status=old_status,
                    new_status=STATUS_NEEDS_REVIEW,
                    details="Approved for continued processing",
                    actor_id=actor_id,
                )
                return
            if action == "reject":
                self.update_claim_status(
                    claim_id, STATUS_DENIED, details=reason or "Rejected by adjuster", actor_id=actor_id
                )
                self.insert_audit_entry(
                    claim_id,
                    AUDIT_EVENT_REJECTION,
                    old_status=old_status,
                    new_status=STATUS_DENIED,
                    details=reason or "",
                    actor_id=actor_id,
                )
                return
            if action == "request_info":
                self.update_claim_status(
                    claim_id, STATUS_PENDING_INFO, details=note or "Requested more information", actor_id=actor_id
                )
                self.insert_audit_entry(
                    claim_id,
                    AUDIT_EVENT_REQUEST_INFO,
                    old_status=old_status,
                    new_status=STATUS_PENDING_INFO,
                    details=note or "",
                    actor_id=actor_id,
                )
                return
            if action == "escalate_to_siu":
                self.update_claim_status(
                    claim_id,
                    STATUS_UNDER_INVESTIGATION,
                    details="Escalated to SIU",
                    actor_id=actor_id,
                )
                self.insert_audit_entry(
                    claim_id,
                    AUDIT_EVENT_ESCALATE_TO_SIU,
                    old_status=old_status,
                    new_status=STATUS_UNDER_INVESTIGATION,
                    details="Referred to Special Investigations Unit",
                    actor_id=actor_id,
                )
                return
            raise ValueError(f"Unknown adjuster action: {action}")

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
    ) -> list[dict[str, Any]]:
        """Search claims by VIN and/or incident_date. Both optional; if both None, returns []."""
        vin = None if vin is None else str(vin).strip()
        incident_date = None if incident_date is None else str(incident_date).strip()
        if not vin and not incident_date:
            return []
        with get_connection(self._db_path) as conn:
            if vin and incident_date:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE vin = ? AND incident_date = ?",
                    (vin, incident_date),
                ).fetchall()
            elif vin:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE vin = ?", (vin,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE incident_date = ?",
                    (incident_date,),
                ).fetchall()
        return [dict(r) for r in rows]
