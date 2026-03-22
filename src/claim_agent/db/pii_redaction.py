"""Shared PII redaction for DSAR deletion and retention purge."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from claim_agent.db.database import row_to_dict

PII_REDACTED_PLACEHOLDER = "[REDACTED]"

# Known PII key names that may appear in claim_audit_log JSON fields
# (details, before_state, after_state). Values under these keys are replaced
# with PII_REDACTED_PLACEHOLDER when the 'redact' audit log policy is used.
_AUDIT_LOG_PII_KEYS: frozenset[str] = frozenset(
    {
        "policy_number",
        "vin",
        "incident_description",
        "damage_description",
        "name",
        "email",
        "phone",
        "address",
        "claimant_name",
    }
)


def _redact_json_value(obj: Any) -> Any:
    """Recursively replace known PII key values in a parsed JSON object."""
    if isinstance(obj, dict):
        return {
            k: (PII_REDACTED_PLACEHOLDER if k in _AUDIT_LOG_PII_KEYS else _redact_json_value(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_json_value(item) for item in obj]
    return obj


def _redact_json_field(raw: str | None) -> str | None:
    """Parse a JSON string, redact PII keys, and return the updated JSON string."""
    if not raw:
        return raw
    try:
        parsed = json.loads(raw)
        redacted = _redact_json_value(parsed)
        return json.dumps(redacted)
    except (json.JSONDecodeError, TypeError):
        return PII_REDACTED_PLACEHOLDER


def redact_audit_log_pii(conn: Connection, claim_id: str) -> int:
    """Scrub PII from claim_audit_log JSON fields for a claim.

    Uses delete-then-reinsert (preserving created_at and action metadata) to work
    around the append-only UPDATE trigger while staying within the DB schema.
    DELETE is permitted since migration 039.

    The ``details``, ``before_state``, and ``after_state`` JSON columns are
    parsed and any values whose key matches a known PII field name are replaced
    with ``PII_REDACTED_PLACEHOLDER``. Non-JSON or unparseable fields are replaced
    with the placeholder string in full.

    Args:
        conn: Active SQLAlchemy connection.
        claim_id: Claim ID whose audit rows should be redacted.

    Returns:
        Number of audit rows processed.
    """
    rows = conn.execute(
        text(
            "SELECT id, action, old_status, new_status, details, actor_id, "
            "before_state, after_state, created_at "
            "FROM claim_audit_log WHERE claim_id = :claim_id"
        ),
        {"claim_id": claim_id},
    ).fetchall()

    if not rows:
        return 0

    redacted: list[dict[str, Any]] = []
    for row in rows:
        r = row_to_dict(row)
        redacted.append(
            {
                "claim_id": claim_id,
                "action": r.get("action"),
                "old_status": r.get("old_status"),
                "new_status": r.get("new_status"),
                "details": _redact_json_field(r.get("details")),
                "actor_id": r.get("actor_id"),
                "before_state": _redact_json_field(r.get("before_state")),
                "after_state": _redact_json_field(r.get("after_state")),
                "created_at": r.get("created_at"),
            }
        )

    # Delete all original rows in one statement (DELETE is permitted since migration 039)
    conn.execute(
        text("DELETE FROM claim_audit_log WHERE claim_id = :claim_id"),
        {"claim_id": claim_id},
    )
    # Reinsert redacted copies preserving created_at and action metadata
    for params in redacted:
        conn.execute(
            text("""
                INSERT INTO claim_audit_log
                    (claim_id, action, old_status, new_status, details,
                     actor_id, before_state, after_state, created_at)
                VALUES
                    (:claim_id, :action, :old_status, :new_status, :details,
                     :actor_id, :before_state, :after_state, :created_at)
            """),
            params,
        )
    return len(redacted)


def delete_audit_log_entries(conn: Connection, claim_id: str) -> int:
    """Delete all claim_audit_log rows for a claim.

    DELETE is permitted since migration 039, which dropped the append-only
    delete trigger. This operation is irreversible and should only be used
    after compliance sign-off as part of a DSAR deletion where the
    ``DSAR_AUDIT_LOG_POLICY=delete`` policy has been explicitly configured.

    Args:
        conn: Active SQLAlchemy connection.
        claim_id: Claim ID whose audit rows should be removed.

    Returns:
        Number of rows deleted.
    """
    result = conn.execute(
        text("DELETE FROM claim_audit_log WHERE claim_id = :claim_id"),
        {"claim_id": claim_id},
    )
    rowcount: Any = result.rowcount
    return int(rowcount) if rowcount is not None else 0


def anonymize_claim_pii(
    conn: Connection,
    claim_id: str,
    *,
    now_iso: str,
    notes_redaction_text: str,
) -> tuple[int, int]:
    """Redact claim identifiers, narrative fields, attachments, parties, and notes.

    Preserves audit log. Narrative columns may contain embedded PII (names, locations).

    Returns:
        Tuple of (1 if claim row updated, number of party rows for the claim).
    """
    conn.execute(
        text("""
            UPDATE claims SET policy_number = :redacted, vin = :redacted,
            incident_description = :redacted, damage_description = :redacted,
            attachments = '[]', updated_at = :now WHERE id = :claim_id
        """),
        {"redacted": PII_REDACTED_PLACEHOLDER, "claim_id": claim_id, "now": now_iso},
    )

    party_count = conn.execute(
        text("SELECT COUNT(*) FROM claim_parties WHERE claim_id = :claim_id"),
        {"claim_id": claim_id},
    ).fetchone()
    n_parties = 0
    if party_count is not None:
        raw: Any = party_count[0] if hasattr(party_count, "__getitem__") else party_count
        n_parties = int(raw) if raw is not None else 0

    conn.execute(
        text("""
            UPDATE claim_parties SET name = :redacted, email = :redacted,
            phone = :redacted, address = :redacted, updated_at = :now
            WHERE claim_id = :claim_id
        """),
        {"redacted": PII_REDACTED_PLACEHOLDER, "claim_id": claim_id, "now": now_iso},
    )

    conn.execute(
        text("UPDATE claim_notes SET note = :redacted WHERE claim_id = :claim_id"),
        {"redacted": notes_redaction_text, "claim_id": claim_id},
    )

    return (1, n_parties)
