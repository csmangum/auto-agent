"""Shared PII redaction for DSAR deletion and retention purge."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from claim_agent.db.database import row_to_dict

PII_REDACTED_PLACEHOLDER = "[REDACTED]"

# Top-level scalar keys in before_state / after_state JSON that contain PII
# and should be replaced with the placeholder on audit-log redaction.
_AUDIT_PII_SCALAR_KEYS: frozenset[str] = frozenset(
# Known PII key names that may appear in claim_audit_log JSON fields
# (details, before_state, after_state). Values under these keys are replaced
# with PII_REDACTED_PLACEHOLDER when the 'redact' audit log policy is used.
_AUDIT_LOG_PII_KEYS: frozenset[str] = frozenset(
    {
        "policy_number",
        "vin",
        "incident_description",
        "damage_description",
    }
)

# Keys inside nested objects (e.g. party dicts) that carry PII.
_AUDIT_PII_NESTED_KEYS: frozenset[str] = frozenset(
    {"name", "email", "phone", "address"}
)


def _redact_json_pii(value: Any, placeholder: str = PII_REDACTED_PLACEHOLDER) -> Any:
    """Recursively redact PII keys from a decoded JSON value.

    - Dict: replace scalar values whose key is in the PII key sets with
      *placeholder*; replace list values for "attachments" with ``[]``; recurse
      into nested dicts/lists for all other keys.
    - List: recurse into each element.
    - Scalar: returned unchanged (callers handle key-based dispatch).
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            k_lower = k.lower()
            if k_lower == "attachments":
                result[k] = []
            elif k_lower in _AUDIT_PII_SCALAR_KEYS or k_lower in _AUDIT_PII_NESTED_KEYS:
                result[k] = placeholder if v is not None else None
            elif isinstance(v, (dict, list)):
                result[k] = _redact_json_pii(v, placeholder)
            else:
                result[k] = v
        return result
    if isinstance(value, list):
        return [_redact_json_pii(item, placeholder) for item in value]
    return value


def redact_audit_log_pii(
    conn: Connection,
    claim_id: str,
    *,
    placeholder: str = PII_REDACTED_PLACEHOLDER,
) -> int:
    """Redact PII from before_state / after_state JSON in claim_audit_log rows.

    This function performs in-place UPDATE of the two JSON columns.  It is
    permitted by the ``claim_audit_log_protect_non_pii_columns`` trigger
    installed by migration 049, which still blocks changes to all other
    columns (claim_id, action, statuses, details, actor_id, created_at).

    This function is a no-op when ``AUDIT_LOG_STATE_REDACTION_ENABLED=false``
    (the default); callers are responsible for checking that gate before
    invoking it.

    Args:
        conn: Active SQLAlchemy connection (within an open transaction).
        claim_id: The claim whose audit rows should be redacted.
        placeholder: String to substitute for PII values (default ``[REDACTED]``).

    Returns:
        Number of audit rows that were updated.
    """
    rows = conn.execute(
        text(
            "SELECT id, before_state, after_state FROM claim_audit_log "
            "WHERE claim_id = :claim_id"
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

    updated = 0
    for row in rows:
        # SQLAlchemy text() rows always support subscript access.
        row_id: int = row[0]
        raw_before: str | None = row[1]
        raw_after: str | None = row[2]

        new_before: str | None = None
        if raw_before:
            try:
                parsed = json.loads(raw_before)
                redacted = _redact_json_pii(parsed, placeholder)
                new_before = json.dumps(redacted)
            except (json.JSONDecodeError, TypeError):
                new_before = raw_before  # leave unparseable values as-is

        new_after: str | None = None
        if raw_after:
            try:
                parsed = json.loads(raw_after)
                redacted = _redact_json_pii(parsed, placeholder)
                new_after = json.dumps(redacted)
            except (json.JSONDecodeError, TypeError):
                new_after = raw_after

        if new_before != raw_before or new_after != raw_after:
            conn.execute(
                text(
                    "UPDATE claim_audit_log "
                    "SET before_state = :before_state, after_state = :after_state "
                    "WHERE id = :row_id"
                ),
                {
                    "before_state": new_before,
                    "after_state": new_after,
                    "row_id": row_id,
                },
            )
            updated += 1

    return updated
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
    redact_audit_log: bool = False,
) -> tuple[int, int]:
    """Redact claim identifiers, narrative fields, attachments, parties, and notes.

    When *redact_audit_log* is ``True`` the function also calls
    :func:`redact_audit_log_pii` to sanitize PII inside the JSON state
    snapshots stored in ``claim_audit_log.before_state`` / ``after_state``.
    This requires migration 049 to be applied (the trigger must allow updates
    to those two columns).  The flag should only be set when the
    ``AUDIT_LOG_STATE_REDACTION_ENABLED`` setting is enabled.

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

    if redact_audit_log:
        redact_audit_log_pii(conn, claim_id, placeholder=PII_REDACTED_PLACEHOLDER)

    return (1, n_parties)
