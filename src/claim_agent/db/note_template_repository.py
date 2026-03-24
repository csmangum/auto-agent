"""CRUD persistence for note_templates (server-driven adjuster quick-insert snippets)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, row_to_dict


class NoteTemplateRepository:
    """CRUD for note_templates table."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def create(
        self,
        label: str,
        body: str,
        *,
        category: str | None = None,
        sort_order: int = 0,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        label = label.strip()
        body = body.strip()
        if not label:
            raise ValueError("label cannot be blank")
        if not body:
            raise ValueError("body cannot be blank")
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "INSERT INTO note_templates (label, body, category, sort_order, created_by) "
                    "VALUES (:label, :body, :category, :sort_order, :created_by) "
                    "RETURNING *"
                ),
                {
                    "label": label,
                    "body": body,
                    "category": category.strip() if category else None,
                    "sort_order": sort_order,
                    "created_by": created_by,
                },
            ).fetchone()
        if row is None:
            raise RuntimeError("INSERT INTO note_templates did not return a row")
        return row_to_dict(row)

    def list(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        clause = " WHERE is_active = 1" if active_only else ""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(
                    f"SELECT * FROM note_templates{clause} ORDER BY sort_order ASC, label ASC"
                )
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get(self, template_id: int) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM note_templates WHERE id = :id"),
                {"id": template_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def update(
        self,
        template_id: int,
        *,
        label: str | None = None,
        body: str | None = None,
        category: str | None = ...,  # type: ignore[assignment]
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        params: dict[str, Any] = {"id": template_id}
        if label is not None:
            label = label.strip()
            if not label:
                raise ValueError("label cannot be blank")
            fields.append("label = :label")
            params["label"] = label
        if body is not None:
            body = body.strip()
            if not body:
                raise ValueError("body cannot be blank")
            fields.append("body = :body")
            params["body"] = body
        if category is not ...:
            fields.append("category = :category")
            params["category"] = category.strip() if category else None
        if is_active is not None:
            fields.append("is_active = :is_active")
            params["is_active"] = 1 if is_active else 0
        if sort_order is not None:
            fields.append("sort_order = :sort_order")
            params["sort_order"] = sort_order
        if not fields:
            return self.get(template_id)
        now = datetime.now(timezone.utc).isoformat()
        fields.append("updated_at = :updated_at")
        params["updated_at"] = now
        with get_connection(self._db_path) as conn:
            conn.execute(
                text(f"UPDATE note_templates SET {', '.join(fields)} WHERE id = :id"),
                params,
            )
        return self.get(template_id)

    def delete(self, template_id: int) -> bool:
        with get_connection(self._db_path) as conn:
            r = conn.execute(
                text("DELETE FROM note_templates WHERE id = :id"),
                {"id": template_id},
            )
            return int(getattr(r, "rowcount", 0) or 0) > 0
