"""Shared PII redaction for DSAR deletion and retention purge."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

PII_REDACTED_PLACEHOLDER = "[REDACTED]"


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
