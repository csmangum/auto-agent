"""Add claim_documents, document_requests, and document_request_id on claim_tasks.

Revision ID: 019
Revises: 018
Create Date: 2026-03-16

Implements Document Management System:
- claim_documents: structured document metadata (type, received_from, review_status, etc.)
- document_requests: request -> receipt tracking
- claim_tasks.document_request_id: link tasks to document requests
"""
import json

from alembic import op
from sqlalchemy import text


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS claim_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            document_type TEXT,
            received_date TEXT,
            received_from TEXT,
            review_status TEXT NOT NULL DEFAULT 'pending',
            privileged INTEGER NOT NULL DEFAULT 0,
            retention_date TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            extracted_data TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status)"
    ))

    op.execute(text("""
        CREATE TABLE IF NOT EXISTS document_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            document_type TEXT NOT NULL,
            requested_at TEXT NOT NULL DEFAULT (datetime('now')),
            requested_from TEXT,
            status TEXT NOT NULL DEFAULT 'requested',
            received_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_document_requests_claim_id ON document_requests(claim_id)"
    ))

    conn = op.get_bind()
    # claim_tasks may not exist in alembic-only fresh installs (created by database.py)
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "claim_tasks" in tables:
        cursor = conn.execute(text("PRAGMA table_info(claim_tasks)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "document_request_id" not in columns:
            op.execute(text(
                "ALTER TABLE claim_tasks ADD COLUMN document_request_id INTEGER "
                "REFERENCES document_requests(id)"
            ))

    # Data migration: existing attachments -> claim_documents
    rows = conn.execute(text("SELECT id, attachments FROM claims WHERE attachments IS NOT NULL AND attachments != '[]'")).fetchall()
    type_map = {"photo": "photo", "pdf": "pdf", "estimate": "estimate", "other": "other"}
    seen: set[tuple[str, str]] = set()  # (claim_id, storage_key) for deduplication
    for row in rows:
        claim_id = row[0]
        raw = row[1] or "[]"
        try:
            atts = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for att in atts if isinstance(atts, list) else []:
            url = att.get("url", "") or ""
            if not url or url.startswith(("http://", "https://", "file://")):
                continue
            storage_key = url.split("/")[-1] if "/" in url else url
            if (claim_id, storage_key) in seen:
                continue
            seen.add((claim_id, storage_key))
            doc_type = type_map.get((att.get("type") or "other").lower(), "other")
            conn.execute(
                text("""
                    INSERT INTO claim_documents
                    (claim_id, storage_key, document_type, received_from, review_status)
                    VALUES (:claim_id, :storage_key, :doc_type, 'claimant', 'pending')
                """),
                {"claim_id": claim_id, "storage_key": storage_key, "doc_type": doc_type},
            )


def downgrade() -> None:
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "claim_tasks" not in tables:
        op.execute(text("DROP TABLE IF EXISTS document_requests"))
        op.execute(text("DROP TABLE IF EXISTS claim_documents"))
        return
    cursor = conn.execute(text("PRAGMA table_info(claim_tasks)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "document_request_id" in columns:
        op.execute(text(
            "CREATE TABLE claim_tasks_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "claim_id TEXT NOT NULL, "
            "title TEXT NOT NULL, "
            "task_type TEXT NOT NULL, "
            "description TEXT DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'pending', "
            "priority TEXT NOT NULL DEFAULT 'medium', "
            "assigned_to TEXT, "
            "created_by TEXT NOT NULL DEFAULT 'workflow', "
            "due_date TEXT, "
            "resolution_notes TEXT, "
            "created_at TEXT DEFAULT (datetime('now')), "
            "updated_at TEXT DEFAULT (datetime('now')), "
            "FOREIGN KEY (claim_id) REFERENCES claims(id)"
            ")"
        ))
        op.execute(text("""
            INSERT INTO claim_tasks_new
            (id, claim_id, title, task_type, description, status, priority,
             assigned_to, created_by, due_date, resolution_notes, created_at, updated_at)
            SELECT id, claim_id, title, task_type, description, status, priority,
                   assigned_to, created_by, due_date, resolution_notes, created_at, updated_at
            FROM claim_tasks
        """))
        op.execute(text("DROP TABLE claim_tasks"))
        op.execute(text("ALTER TABLE claim_tasks_new RENAME TO claim_tasks"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_id ON claim_tasks(claim_id)"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_status ON claim_tasks(status)"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_status ON claim_tasks(claim_id, status)"))

    op.execute(text("DROP TABLE IF EXISTS document_requests"))
    op.execute(text("DROP TABLE IF EXISTS claim_documents"))
