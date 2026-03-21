"""Document repository: CRUD for claim_documents and document_requests."""

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.document import (
    DocumentRequestStatus,
    DocumentType,
    ReviewStatus,
)


def _row_to_document(row: Any) -> dict[str, Any]:
    """Convert DB row to document dict."""
    d = row_to_dict(row)
    if d.get("extracted_data"):
        try:
            d["extracted_data"] = json.loads(d["extracted_data"])
        except (json.JSONDecodeError, TypeError):
            d["extracted_data"] = None
    d["privileged"] = bool(d.get("privileged", 0))
    return d


def _row_to_request(row: Any) -> dict[str, Any]:
    """Convert DB row to document request dict."""
    return row_to_dict(row)


def build_document_version_groups(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group documents by ``storage_key`` and order by version (ascending) for timeline UI.

    Adds ``is_current_version`` on each document dict copy: true for the row with the
    highest ``version`` (ties broken by largest ``id``).
    """
    from collections import defaultdict

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in documents:
        sk = (d.get("storage_key") or "").strip()
        key = sk if sk else f"__noid_{d.get('id')}"
        by_key[key].append(d)

    out: list[dict[str, Any]] = []
    for group_key, versions in sorted(by_key.items(), key=lambda x: x[0]):
        max_ver = max((v.get("version") or 1) for v in versions)
        candidates = [v for v in versions if (v.get("version") or 1) == max_ver]
        current_id = max(int(v["id"]) for v in candidates) if candidates else None

        sorted_versions = sorted(
            versions,
            key=lambda x: ((x.get("version") or 1), int(x.get("id") or 0)),
        )
        enriched: list[dict[str, Any]] = []
        for v in sorted_versions:
            vd = dict(v)
            vd["is_current_version"] = current_id is not None and int(vd.get("id") or 0) == current_id
            enriched.append(vd)

        display_key = versions[0].get("storage_key") or ""
        out.append(
            {
                "storage_key": display_key,
                "versions": enriched,
                "version_count": len(enriched),
            }
        )
    return out


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
            received_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc_type = document_type.value if isinstance(document_type, DocumentType) else document_type
        ext_json = json.dumps(extracted_data) if extracted_data else None
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO claim_documents
                    (claim_id, storage_key, document_type, received_date, received_from,
                     review_status, privileged, retention_date, version, extracted_data)
                VALUES (:claim_id, :storage_key, :doc_type, :received_date, :received_from,
                        :review_status, :privileged, :retention_date, :version, :extracted_data)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "storage_key": storage_key,
                    "doc_type": doc_type,
                    "received_date": received_date,
                    "received_from": received_from,
                    "review_status": review_status.value,
                    "privileged": 1 if privileged else 0,
                    "retention_date": retention_date,
                    "version": version,
                    "extracted_data": ext_json,
                },
            )
            rid = result.fetchone()
            return int(rid[0]) if rid else 0

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        """Fetch a single document by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_documents WHERE id = :id"),
                {"id": document_id},
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
        conditions = ["claim_id = :claim_id"]
        params: dict[str, Any] = {"claim_id": claim_id}
        if document_type is not None:
            conditions.append("document_type = :document_type")
            params["document_type"] = document_type
        if review_status is not None:
            conditions.append("review_status = :review_status")
            params["review_status"] = review_status
        where = " AND ".join(conditions)
        params["limit"] = limit
        params["offset"] = offset
        count_params = {k: v for k, v in params.items() if k in ("claim_id", "document_type", "review_status")}
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claim_documents WHERE {where}"),
                count_params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""SELECT * FROM claim_documents WHERE {where}
                    ORDER BY received_date DESC, created_at DESC
                    LIMIT :limit OFFSET :offset"""),
                params,
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
        now = datetime.now(timezone.utc).isoformat()
        updates: list[str] = ["updated_at = :now"]
        params: dict[str, Any] = {"now": now, "id": document_id}
        if review_status is not None:
            updates.append("review_status = :review_status")
            params["review_status"] = review_status.value
        if document_type is not None:
            doc_type = (
                document_type.value if isinstance(document_type, DocumentType) else document_type
            )
            updates.append("document_type = :document_type")
            params["document_type"] = doc_type
        if received_from is not None:
            updates.append("received_from = :received_from")
            params["received_from"] = received_from
        if privileged is not None:
            updates.append("privileged = :privileged")
            params["privileged"] = 1 if privileged else 0
        if retention_date is not None:
            updates.append("retention_date = :retention_date")
            params["retention_date"] = retention_date
        if extracted_data is not None:
            updates.append("extracted_data = :extracted_data")
            params["extracted_data"] = json.dumps(extracted_data)
        if len(params) <= 2:  # only now and id
            return self.get_document(document_id)
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text(f"UPDATE claim_documents SET {', '.join(updates)} WHERE id = :id"),
                params,
            )
            if result.rowcount == 0:
                return None
            row = conn.execute(
                text("SELECT * FROM claim_documents WHERE id = :id"),
                {"id": document_id},
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
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO document_requests
                    (claim_id, document_type, requested_at, requested_from, status)
                VALUES (:claim_id, :document_type, :now, :requested_from, 'requested')
                RETURNING id
                """),
                {"claim_id": claim_id, "document_type": document_type, "now": now, "requested_from": requested_from},
            )
            rid = result.fetchone()
            return int(rid[0]) if rid else 0

    def get_document_request(self, request_id: int) -> dict[str, Any] | None:
        """Fetch a single document request by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM document_requests WHERE id = :id"),
                {"id": request_id},
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
        conditions = ["claim_id = :claim_id"]
        params: dict[str, Any] = {"claim_id": claim_id}
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions)
        params["limit"] = limit
        params["offset"] = offset
        count_params = {k: v for k, v in params.items() if k in ("claim_id", "status")}
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM document_requests WHERE {where}"),
                count_params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""SELECT * FROM document_requests WHERE {where}
                    ORDER BY requested_at DESC
                    LIMIT :limit OFFSET :offset"""),
                params,
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
        now = datetime.now(timezone.utc).isoformat()
        updates: list[str] = ["updated_at = :now"]
        params: dict[str, Any] = {"now": now, "id": request_id}
        if status is not None:
            st = status.value if isinstance(status, DocumentRequestStatus) else status
            updates.append("status = :status")
            params["status"] = st
        if received_at is not None:
            updates.append("received_at = :received_at")
            params["received_at"] = received_at
        if len(params) <= 2:
            return self.get_document_request(request_id)
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text(f"UPDATE document_requests SET {', '.join(updates)} WHERE id = :id"),
                params,
            )
            if result.rowcount == 0:
                return None
            row = conn.execute(
                text("SELECT * FROM document_requests WHERE id = :id"),
                {"id": request_id},
            ).fetchone()
        return _row_to_request(row) if row else None

    def link_task_to_document_request(
        self,
        task_id: int,
        document_request_id: int,
    ) -> bool:
        """Link a claim task to a document request. Returns True on success."""
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("UPDATE claim_tasks SET document_request_id = :dr_id, updated_at = :now WHERE id = :id"),
                {"dr_id": document_request_id, "now": now, "id": task_id},
            )
            return bool(result.rowcount)

    def find_pending_document_requests_for_type(
        self,
        claim_id: str,
        document_type: str,
    ) -> list[dict[str, Any]]:
        """Find document requests that are still requested/partial for the given type."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""SELECT * FROM document_requests
                   WHERE claim_id = :claim_id AND document_type = :document_type
                   AND status IN ('requested', 'partial')
                   ORDER BY requested_at ASC"""),
                {"claim_id": claim_id, "document_type": document_type},
            ).fetchall()
        return [_row_to_request(r) for r in rows]

    def list_documents_past_retention(self, cutoff_date: str) -> list[dict[str, Any]]:
        """Rows with ``retention_date`` before ``cutoff_date`` (YYYY-MM-DD), not yet enforced.

        Ignores blank ``retention_date``. Compares trimmed non-empty values lexicographically
        (ISO dates) against ``cutoff_date``.
        """
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT id, claim_id, storage_key, retention_date, document_type
                FROM claim_documents
                WHERE retention_date IS NOT NULL
                  AND length(trim(retention_date)) > 0
                  AND trim(retention_date) < :cutoff
                  AND retention_enforced_at IS NULL
                ORDER BY id ASC
                """),
                {"cutoff": cutoff_date},
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = row_to_dict(r)
            out.append(d)
        return out

    def mark_retention_enforced_with_audit(
        self,
        document_id: int,
        claim_id: str,
        *,
        action: str,
        actor_id: str,
        details: str,
        after_state: str,
    ) -> bool:
        """Set ``retention_enforced_at`` and append ``claim_audit_log`` in one transaction.

        Returns True if the document row was updated (was not already enforced). If the
        audit insert fails, the document update is rolled back with the same connection.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                UPDATE claim_documents
                SET retention_enforced_at = :ts, updated_at = :ts
                WHERE id = :id
                  AND retention_enforced_at IS NULL
                """),
                {"ts": now, "id": document_id},
            )
            if not result.rowcount:
                return False
            conn.execute(
                text("""
                INSERT INTO claim_audit_log
                    (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": action,
                    "old_status": None,
                    "new_status": None,
                    "details": details or "",
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": after_state,
                },
            )
            return True
