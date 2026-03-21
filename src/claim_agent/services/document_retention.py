"""Per-document retention enforcement (``claim_documents.retention_date``).

Separate from claim-level ``retention-enforce``. Intended to be run on a schedule
(for example cron) via ``claim-agent document-retention-enforce``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from claim_agent.db.audit_events import ACTOR_RETENTION, AUDIT_EVENT_DOCUMENT_RETENTION_ENFORCED
from claim_agent.db.document_repository import DocumentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.utils.sanitization import sanitize_actor_id, truncate_audit_json

logger = logging.getLogger(__name__)


def run_document_retention_enforce(
    *,
    db_path: str | None,
    cutoff_date: str,
    dry_run: bool = False,
    actor_id: str = ACTOR_RETENTION,
) -> dict[str, Any]:
    """Soft-archive documents whose ``retention_date`` is strictly before ``cutoff_date``.

    Sets ``retention_enforced_at`` and appends ``document_retention_enforced`` audit rows.
    Does not delete storage objects or DB rows.
    """
    doc_repo = DocumentRepository(db_path)
    claim_repo = ClaimRepository(db_path)
    rows = doc_repo.list_documents_past_retention(cutoff_date)
    if dry_run:
        return {
            "dry_run": True,
            "cutoff_date": cutoff_date,
            "document_count": len(rows),
            "documents": [
                {
                    "id": r["id"],
                    "claim_id": r["claim_id"],
                    "storage_key": r["storage_key"],
                    "retention_date": r["retention_date"],
                    "document_type": r.get("document_type"),
                }
                for r in rows
            ],
        }

    enforced_ids: list[int] = []
    failed_ids: list[int] = []
    safe_actor = sanitize_actor_id(actor_id)
    for r in rows:
        doc_id = int(r["id"])
        claim_id = str(r["claim_id"])
        try:
            updated = doc_repo.mark_retention_enforced(doc_id)
            if not updated:
                continue
            payload = truncate_audit_json(
                {
                    "document_id": doc_id,
                    "storage_key": r.get("storage_key"),
                    "retention_date": r.get("retention_date"),
                    "document_type": r.get("document_type"),
                    "enforced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            claim_repo.insert_audit_entry(
                claim_id,
                AUDIT_EVENT_DOCUMENT_RETENTION_ENFORCED,
                actor_id=safe_actor,
                details=f"Document {doc_id} soft-archived (retention_date past cutoff {cutoff_date})",
                after_state=payload,
            )
            enforced_ids.append(doc_id)
        except Exception:
            logger.exception("document retention enforce failed for document_id=%s", doc_id)
            failed_ids.append(doc_id)

    return {
        "dry_run": False,
        "cutoff_date": cutoff_date,
        "enforced_count": len(enforced_ids),
        "enforced_document_ids": enforced_ids,
        "failed_count": len(failed_ids),
        "failed_document_ids": failed_ids,
    }
