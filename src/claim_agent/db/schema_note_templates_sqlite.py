"""SQLite DDL for note_templates (server-driven adjuster quick-insert templates).

Used by ``database.py`` (``SCHEMA_SQL``) and Alembic revision 053 so these
definitions stay in one place.

PostgreSQL equivalents use ``TIMESTAMP WITH TIME ZONE`` instead of ``TEXT`` for
temporal columns and ``SERIAL`` for auto-increment primary keys; keep columns,
nullability, and indexes logically aligned when changing schema.
"""

NOTE_TEMPLATES_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS note_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

IDX_NOTE_TEMPLATES_ACTIVE = (
    "CREATE INDEX IF NOT EXISTS idx_note_templates_active ON note_templates(is_active)"
)
