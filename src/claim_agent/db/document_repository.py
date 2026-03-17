"""Document repository: CRUD for claim_documents and document_requests."""

import json
from datetime import datetime
from typing import Any, Optional

from claim_agent.db.database import get_connection
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.document import (
    DocumentRequestStatus,
    DocumentType,
    ReviewStatus,
)


def _row_to_document(row: Any) -> dict[str, Any]:
    """Convert DB row to document dict."""
    d = dict(row)
    if d.get("extracted_data"):
        try:
            d["extracted_data"] = json.loads(d["extracted_data"])
        except (json.JSONDecodeError, TypeError):
            d["extracted_data"] = None
    d["privileged"] = bool(d.get("privileged", 0))
    return d


def _row_to_request(row: Any) -> dict[str, Any]:
    """Convert DB row to document request dict."""
    return dict(row)


class DocumentRepository:
    """Repository for claim documents and document requests."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def add_document(
        self,
        claim_id: str,
        storage_key: str,
        *,
        document_type: Optional[DocumentType | str] = None,
        received_date: Optional[str] = None,
        received_from: Optional[str] = None,
        review_status: ReviewStatus = ReviewStatus.PENDING,
        privileged: bool = False,
        retention_date: Optional[str] = None,
        version: int = 1,
        extracted_data: Optional[dict[str, Any]] = None,
    ) -> int:
        """Add a document record. Returns document id."""
        if received_date is None:
            received_date = datetime.utcnow().strftime("%Y-%m-%d")
        doc_type = document_type.value if isinstance(document_type, DocumentType) else document_type
        ext_json = json.dumps(extracted_data) if extracted_data else None
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            cursor = conn.execute(
                """
                INSERT INTO claim_documents
                    (claim_id, storage_key, document_type, received_date, received_from,
                     review_status, privileged, retention_date, version, extracted_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    storage_key,
                    doc_type,
                    received_date,
                    received_from,
                    review_status.value,
                    1 if privileged else 0,
                    retention_date,
                    version,
                    ext_json,
                ),
            )
            return int(cursor.lastrowid)

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        """Fetch a single document by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM claim_documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(
        self,
        claim_id: str,
        *,
        document_type: Optional[str] = None,
        review_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List documents for a claim with optional filters. Returns (documents, total)."""
        conditions = ["claim_id = ?"]
        params: list[Any] = [claim_id]
        if document_type is not None:
            conditions.append("document_type = ?")
            params.append(document_type)
        if review_status is not None:
            conditions.append("review_status = ?")
            params.append(review_status)
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM claim_documents WHERE {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"""SELECT * FROM claim_documents WHERE {where}
                    ORDER BY received_date DESC, created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return [_row_to_document(r) for r in rows], total

    def update_document_review(
        self,
        document_id: int,
        *,
        review_status: Optional[ReviewStatus] = None,
        document_type: Optional[DocumentType | str] = None,
        received_from: Optional[str] = None,
        privileged: Optional[bool] = None,
        retention_date: Optional[str] = None,
        extracted_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any] | None:
        """Update document metadata. Returns updated document or None if not found."""
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if review_status is not None:
            updates.append("review_status = ?")
            params.append(review_status.value)
        if document_type is not None:
            doc_type = (
                document_type.value if isinstance(document_type, DocumentType) else document_type
            )
            updates.append("document_type = ?")
            params.append(doc_type)
        if received_from is not None:
            updates.append("received_from = ?")
            params.append(received_from)
        if privileged is not None:
            updates.append("privileged = ?")
            params.append(1 if privileged else 0)
        if retention_date is not None:
            updates.append("retention_date = ?")
            params.append(retention_date)
        if extracted_data is not None:
            updates.append("extracted_data = ?")
            params.append(json.dumps(extracted_data))
        if len(params) == 0:
            return self.get_document(document_id)
        params.append(document_id)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE claim_documents SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM claim_documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def create_document_request(
        self,
        claim_id: str,
        document_type: str,
        *,
        requested_from: Optional[str] = None,
    ) -> int:
        """Create a document request. Returns request id."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            cursor = conn.execute(
                """
                INSERT INTO document_requests
                    (claim_id, document_type, requested_at, requested_from, status)
                VALUES (?, ?, datetime('now'), ?, 'requested')
                """,
                (claim_id, document_type, requested_from),
            )
            return int(cursor.lastrowid)

    def get_document_request(self, request_id: int) -> dict[str, Any] | None:
        """Fetch a single document request by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM document_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _row_to_request(row) if row else None

    def list_document_requests(
        self,
        claim_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List document requests for a claim. Returns (requests, total)."""
        conditions = ["claim_id = ?"]
        params: list[Any] = [claim_id]
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM document_requests WHERE {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"""SELECT * FROM document_requests WHERE {where}
                    ORDER BY requested_at DESC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return [_row_to_request(r) for r in rows], total

    def update_document_request(
        self,
        request_id: int,
        *,
        status: Optional[DocumentRequestStatus | str] = None,
        received_at: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Update document request. Returns updated request or None if not found."""
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if status is not None:
            st = status.value if isinstance(status, DocumentRequestStatus) else status
            updates.append("status = ?")
            params.append(st)
        if received_at is not None:
            updates.append("received_at = ?")
            params.append(received_at)
        if len(params) == 0:
            return self.get_document_request(request_id)
        params.append(request_id)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE document_requests SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM document_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _row_to_request(row) if row else None

    def link_task_to_document_request(
        self,
        task_id: int,
        document_request_id: int,
    ) -> bool:
        """Link a claim task to a document request. Returns True on success."""
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE claim_tasks SET document_request_id = ?, updated_at = datetime('now') WHERE id = ?",
                (document_request_id, task_id),
            )
            return bool(cursor.rowcount)

    def find_pending_document_requests_for_type(
        self,
        claim_id: str,
        document_type: str,
    ) -> list[dict[str, Any]]:
        """Find document requests that are still requested/partial for the given type."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM document_requests
                   WHERE claim_id = ? AND document_type = ?
                   AND status IN ('requested', 'partial')
                   ORDER BY requested_at ASC""",
                (claim_id, document_type),
            ).fetchall()
        return [_row_to_request(r) for r in rows]
