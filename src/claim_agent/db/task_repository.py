"""Task repository: CRUD for claim_tasks table."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.audit_events import (
    ACTOR_WORKFLOW,
    AUDIT_EVENT_TASK_CREATED,
    AUDIT_EVENT_TASK_UPDATED,
)
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import (
    sanitize_actor_id,
    sanitize_resolution_notes,
    sanitize_task_description,
    sanitize_task_title,
)


class TaskRepository:
    """Repository for claim task persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def create_task(
        self,
        claim_id: str,
        title: str,
        task_type: str,
        *,
        description: str = "",
        priority: str = "medium",
        assigned_to: str | None = None,
        created_by: str = ACTOR_WORKFLOW,
        due_date: str | None = None,
        document_request_id: int | None = None,
        document_type: str | None = None,
        requested_from: str | None = None,
        recurrence_rule: str | None = None,
        recurrence_interval: int | None = None,
        parent_task_id: int | None = None,
        auto_created_from: str | None = None,
    ) -> int:
        """Create a task for a claim. Returns the task id.

        Raises ClaimNotFoundError if claim does not exist.

        When task_type is request_documents or obtain_police_report and document_type is
        provided, creates a document_request and links it to the task.
        """
        title = sanitize_task_title(title)
        description = sanitize_task_description(description)
        created_by = sanitize_actor_id(created_by)
        if not title:
            raise ValueError("Task title must not be empty after sanitization")
        # Normalize and validate recurrence fields
        if recurrence_rule is None and recurrence_interval is not None:
            recurrence_interval = None
        if recurrence_rule is not None:
            from claim_agent.diary.recurrence import (
                RECURRENCE_INTERVAL_DAYS,
                VALID_RECURRENCE_RULES,
            )

            if recurrence_rule not in VALID_RECURRENCE_RULES:
                raise ValueError(
                    f"Invalid recurrence_rule '{recurrence_rule}'. "
                    f"Must be one of: {', '.join(sorted(VALID_RECURRENCE_RULES))}"
                )
            if recurrence_rule == RECURRENCE_INTERVAL_DAYS:
                if recurrence_interval is None:
                    raise ValueError(
                        "recurrence_interval is required when recurrence_rule is 'interval_days'"
                    )
                if recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
            else:
                # daily/weekly: default interval to 1
                if recurrence_interval is None:
                    recurrence_interval = 1
                elif recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
        doc_req_id = document_request_id
        if (
            doc_req_id is None
            and document_type
            and task_type in ("request_documents", "obtain_police_report")
        ):
            from claim_agent.db.document_repository import DocumentRepository

            doc_repo = DocumentRepository(db_path=self._db_path)
            doc_req_id = doc_repo.create_document_request(
                claim_id, document_type, requested_from=requested_from
            )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO claim_tasks
                    (claim_id, title, task_type, description, status, priority, assigned_to, created_by, due_date, document_request_id, recurrence_rule, recurrence_interval, parent_task_id, auto_created_from)
                VALUES (:claim_id, :title, :task_type, :description, 'pending', :priority, :assigned_to, :created_by, :due_date, :document_request_id, :recurrence_rule, :recurrence_interval, :parent_task_id, :auto_created_from)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "title": title,
                    "task_type": task_type,
                    "description": description,
                    "priority": priority,
                    "assigned_to": assigned_to,
                    "created_by": created_by,
                    "due_date": due_date,
                    "document_request_id": doc_req_id,
                    "recurrence_rule": recurrence_rule,
                    "recurrence_interval": recurrence_interval,
                    "parent_task_id": parent_task_id,
                    "auto_created_from": auto_created_from,
                },
            )
            row = result.fetchone()
            task_id = row[0] if row else 0
            details = json.dumps(
                {
                    "task_id": task_id,
                    "title": title,
                    "task_type": task_type,
                    "priority": priority,
                    "assigned_to": assigned_to,
                }
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_TASK_CREATED,
                    "details": details,
                    "actor_id": created_by,
                },
            )
        return int(task_id)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Fetch a single task by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_tasks_for_claim(
        self,
        claim_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks for a claim with optional status filter. Returns (tasks, total)."""
        conditions = ["claim_id = :claim_id"]
        params: dict[str, Any] = {"claim_id": claim_id, "limit": limit, "offset": offset}
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claim_tasks WHERE {where}"),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""SELECT * FROM claim_tasks WHERE {where}
                    ORDER BY
                        CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        created_at DESC
                    LIMIT :limit OFFSET :offset"""),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def list_overdue_tasks(
        self,
        *,
        max_escalation_level: int | None = None,
        min_escalation_level: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List overdue tasks (due_date < today, status not completed/cancelled).

        Args:
            max_escalation_level: If set, only include tasks with escalation_level <= this.
            min_escalation_level: If set, only include tasks with escalation_level >= this.
            limit: Max tasks to return.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        conditions = [
            "due_date IS NOT NULL",
            "substr(due_date, 1, 10) < :today",
            "status NOT IN ('completed', 'cancelled')",
        ]
        params: dict[str, Any] = {"today": today, "limit": limit}
        if max_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) <= :max_escalation_level")
            params["max_escalation_level"] = max_escalation_level
        if min_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) >= :min_escalation_level")
            params["min_escalation_level"] = min_escalation_level
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(f"""
                SELECT * FROM claim_tasks WHERE {where}
                ORDER BY due_date ASC
                LIMIT :limit
                """),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def mark_task_overdue_notified(self, task_id: int) -> None:
        """Mark task as overdue notification sent (escalation_level=1)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                UPDATE claim_tasks SET
                    escalation_level = 1,
                    escalation_notified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :task_id
                """),
                {"task_id": task_id},
            )

    def mark_task_supervisor_escalated(self, task_id: int) -> None:
        """Mark task as escalated to supervisor (escalation_level=2)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                UPDATE claim_tasks SET
                    escalation_level = 2,
                    escalation_escalated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :task_id
                """),
                {"task_id": task_id},
            )

    def update_task(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        due_date: str | None = None,
        resolution_notes: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> dict[str, Any]:
        """Update a task. Returns the updated task dict. Raises ValueError if task not found."""
        if title is not None:
            title = sanitize_task_title(title)
            if not title:
                raise ValueError("Task title must not be empty after sanitization")
        if description is not None:
            description = sanitize_task_description(description)
        if resolution_notes is not None:
            resolution_notes = sanitize_resolution_notes(resolution_notes)
        actor_id = sanitize_actor_id(actor_id)
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Task not found: {task_id}")

            row_d = row_to_dict(row)
            updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: dict[str, Any] = {"task_id": task_id}
            changes: dict[str, Any] = {}

            for field, value in [
                ("title", title),
                ("description", description),
                ("status", status),
                ("priority", priority),
                ("assigned_to", assigned_to),
                ("due_date", due_date),
                ("resolution_notes", resolution_notes),
            ]:
                if value is not None:
                    updates.append(f"{field} = :{field}")
                    params[field] = value
                    changes[field] = value

            if not changes:
                return row_d

            conn.execute(
                text(f"UPDATE claim_tasks SET {', '.join(updates)} WHERE id = :task_id"),
                params,
            )
            details = json.dumps({"task_id": task_id, **changes})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": row_d["claim_id"],
                    "action": AUDIT_EVENT_TASK_UPDATED,
                    "details": details,
                    "actor_id": actor_id,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
        return row_to_dict(updated)

    def list_all_tasks(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        assigned_to: str | None = None,
        due_date_from: str | None = None,
        due_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks across all claims with optional filters. Returns (tasks, total)."""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            conditions.append("ct.status = :status")
            params["status"] = status
        if task_type is not None:
            conditions.append("ct.task_type = :task_type")
            params["task_type"] = task_type
        if assigned_to is not None:
            conditions.append("ct.assigned_to = :assigned_to")
            params["assigned_to"] = assigned_to
        if due_date_from is not None:
            conditions.append("ct.due_date >= :due_date_from")
            params["due_date_from"] = due_date_from
        if due_date_to is not None:
            conditions.append("ct.due_date <= :due_date_to")
            params["due_date_to"] = due_date_to
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection(self._db_path) as conn:
            # Exclude pagination parameters from the COUNT query to avoid unused bound params.
            count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claim_tasks ct {where}"),
                count_params,
            ).fetchone()
            total = count_row[0]
            rows = conn.execute(
                text(
                    f"""SELECT ct.* FROM claim_tasks ct {where}
                    ORDER BY
                        CASE ct.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE ct.status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        ct.created_at DESC
                    LIMIT :limit OFFSET :offset"""
                ),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def get_task_stats(self) -> dict[str, Any]:
        """Get aggregate task statistics."""
        with get_connection(self._db_path) as conn:
            total = conn.execute(text("SELECT COUNT(*) as cnt FROM claim_tasks")).fetchone()[0]
            by_status = {
                (d := row_to_dict(r))["status"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY status"
                    )
                ).fetchall()
            }
            by_type = {
                (d := row_to_dict(r))["task_type"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(task_type, 'unknown') as task_type, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY task_type"
                    )
                ).fetchall()
            }
            by_priority = {
                (d := row_to_dict(r))["priority"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(priority, 'unknown') as priority, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY priority"
                    )
                ).fetchall()
            }
            overdue = conn.execute(
                text(
                    "SELECT COUNT(*) as cnt FROM claim_tasks "
                    "WHERE due_date IS NOT NULL AND date(due_date) < CURRENT_DATE "
                    "AND status NOT IN ('completed', 'cancelled')"
                )
            ).fetchone()[0]
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_priority": by_priority,
            "overdue": overdue,
        }
