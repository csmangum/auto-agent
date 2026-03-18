"""Data Subject Access Request (DSAR) service for privacy compliance.

Handles access requests (right-to-know) and deletion requests (right-to-delete)
per CCPA/state privacy laws. Collects PII for claimants and supports
anonymization for deletion while preserving audit trail.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, get_db_path, row_to_dict


DSAR_REQUEST_ACCESS = "access"
DSAR_REQUEST_DELETION = "deletion"
DSAR_STATUS_PENDING = "pending"
DSAR_STATUS_IN_PROGRESS = "in_progress"
DSAR_STATUS_COMPLETED = "completed"
DSAR_STATUS_REJECTED = "rejected"


def submit_access_request(
    claimant_identifier: str,
    verification_data: dict[str, Any],
    *,
    db_path: str | None = None,
    actor_id: str = "claimant",
) -> str:
    """Submit a DSAR access request. Returns request_id.

    Args:
        claimant_identifier: Email or hashed policy+vin identifier.
        verification_data: Dict with claim_id and/or policy_number, vin for verification.
        db_path: Optional DB path. Uses default when None.
        actor_id: Actor submitting the request.

    Returns:
        Unique request_id (UUID string) for tracking.
    """
    request_id = str(uuid.uuid4())
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO dsar_requests (
                    request_id, claimant_identifier, request_type, status,
                    actor_id, verification_data
                ) VALUES (:request_id, :claimant_identifier, :request_type, :status,
                          :actor_id, :verification_data)
            """),
            {
                "request_id": request_id,
                "claimant_identifier": claimant_identifier,
                "request_type": DSAR_REQUEST_ACCESS,
                "status": DSAR_STATUS_PENDING,
                "actor_id": actor_id,
                "verification_data": json.dumps(verification_data) if verification_data else None,
            },
        )
    return request_id


def fulfill_access_request(
    request_id: str,
    *,
    db_path: str | None = None,
    actor_id: str = "dsar",
) -> dict[str, Any]:
    """Fulfill an access request: collect all PII for the claimant and return export.

    Looks up claims by verification_data (claim_id, or policy_number+vin).
    Collects: claims, claim_parties, claim_audit_log (action, dates, actor_id),
    claim_notes, documents metadata.

    Args:
        request_id: DSAR request ID from submit_access_request.
        db_path: Optional DB path.
        actor_id: Actor fulfilling the request.

    Returns:
        Dict with claims, parties, audit_entries, notes for the claimant.

    Raises:
        ValueError: If request not found or not access type.
    """
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text(
                "SELECT * FROM dsar_requests WHERE request_id = :request_id"
            ),
            {"request_id": request_id},
        ).fetchone()
        if row is None:
            raise ValueError(f"DSAR request not found: {request_id}")
        req = row_to_dict(row)
        if req.get("request_type") != DSAR_REQUEST_ACCESS:
            raise ValueError(f"Request {request_id} is not an access request")
        if req.get("status") == DSAR_STATUS_COMPLETED:
            # Already fulfilled; could return cached export
            pass

        # Mark in progress
        conn.execute(
            text(
                "UPDATE dsar_requests SET status = :status, actor_id = :actor_id WHERE request_id = :request_id"
            ),
            {
                "status": DSAR_STATUS_IN_PROGRESS,
                "actor_id": actor_id,
                "request_id": request_id,
            },
        )

        verification = {}
        if req.get("verification_data"):
            try:
                verification = json.loads(req["verification_data"])
            except (json.JSONDecodeError, TypeError):
                pass

        claim_ids: list[str] = []
        if verification.get("claim_id"):
            claim_ids.append(str(verification["claim_id"]))
        if verification.get("policy_number") and verification.get("vin"):
            # Look up claims by policy_number and vin
            rows = conn.execute(
                text(
                    "SELECT id FROM claims WHERE policy_number = :pn AND vin = :vin"
                ),
                {
                    "pn": verification["policy_number"],
                    "vin": verification["vin"],
                },
            ).fetchall()
            for r in rows:
                cid = r[0] if hasattr(r, "__getitem__") else r["id"]
                if cid not in claim_ids:
                    claim_ids.append(str(cid))

        # Also match by claimant_identifier (email) in claim_parties
        if not claim_ids and req.get("claimant_identifier"):
            rows = conn.execute(
                text(
                    "SELECT DISTINCT claim_id FROM claim_parties WHERE email = :email"
                ),
                {"email": req["claimant_identifier"]},
            ).fetchall()
            for r in rows:
                cid = r[0] if hasattr(r, "__getitem__") else r["claim_id"]
                claim_ids.append(str(cid))

        export: dict[str, Any] = {
            "request_id": request_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "claims": [],
            "parties": [],
            "audit_entries": [],
            "notes": [],
        }

        for claim_id in claim_ids:
            claim_row = conn.execute(
                text("SELECT * FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if claim_row:
                export["claims"].append(row_to_dict(claim_row))

            party_rows = conn.execute(
                text("SELECT * FROM claim_parties WHERE claim_id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchall()
            for pr in party_rows:
                export["parties"].append(row_to_dict(pr))

            audit_rows = conn.execute(
                text(
                    "SELECT id, claim_id, action, old_status, new_status, actor_id, created_at "
                    "FROM claim_audit_log WHERE claim_id = :claim_id ORDER BY created_at"
                ),
                {"claim_id": claim_id},
            ).fetchall()
            for ar in audit_rows:
                export["audit_entries"].append(row_to_dict(ar))

            note_rows = conn.execute(
                text("SELECT * FROM claim_notes WHERE claim_id = :claim_id ORDER BY created_at"),
                {"claim_id": claim_id},
            ).fetchall()
            for nr in note_rows:
                export["notes"].append(row_to_dict(nr))

        # Mark completed
        completed_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text(
                "UPDATE dsar_requests SET status = :status, completed_at = :completed_at "
                "WHERE request_id = :request_id"
            ),
            {
                "status": DSAR_STATUS_COMPLETED,
                "completed_at": completed_at,
                "request_id": request_id,
            },
        )

        # Store export path (optional: write to file/S3)
        export_json = json.dumps(export, default=str)
        conn.execute(
            text(
                "INSERT INTO dsar_exports (request_id, export_path) VALUES (:request_id, :path)"
            ),
            {"request_id": request_id, "path": f"inline:{len(export_json)}"},
        )

    return export


def get_dsar_request(request_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    """Get DSAR request status by request_id."""
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("SELECT * FROM dsar_requests WHERE request_id = :request_id"),
            {"request_id": request_id},
        ).fetchone()
        if row is None:
            return None
        return row_to_dict(row)


REDACTED = "[REDACTED]"


def submit_deletion_request(
    claimant_identifier: str,
    verification_data: dict[str, Any],
    *,
    db_path: str | None = None,
    actor_id: str = "claimant",
) -> str:
    """Submit a DSAR deletion request. Returns request_id."""
    request_id = str(uuid.uuid4())
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO dsar_requests (
                    request_id, claimant_identifier, request_type, status,
                    actor_id, verification_data
                ) VALUES (:request_id, :claimant_identifier, :request_type, :status,
                          :actor_id, :verification_data)
            """),
            {
                "request_id": request_id,
                "claimant_identifier": claimant_identifier,
                "request_type": DSAR_REQUEST_DELETION,
                "status": DSAR_STATUS_PENDING,
                "actor_id": actor_id,
                "verification_data": json.dumps(verification_data) if verification_data else None,
            },
        )
    return request_id


def fulfill_deletion_request(
    request_id: str,
    *,
    db_path: str | None = None,
    actor_id: str = "dsar",
) -> dict[str, Any]:
    """Fulfill a deletion request: anonymize claim and party PII, preserve audit trail.

    Skips claims with litigation_hold=1. Returns summary of anonymized records.
    """
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("SELECT * FROM dsar_requests WHERE request_id = :request_id"),
            {"request_id": request_id},
        ).fetchone()
        if row is None:
            raise ValueError(f"DSAR request not found: {request_id}")
        req = row_to_dict(row)
        if req.get("request_type") != DSAR_REQUEST_DELETION:
            raise ValueError(f"Request {request_id} is not a deletion request")

        conn.execute(
            text("UPDATE dsar_requests SET status = :status, actor_id = :actor_id WHERE request_id = :request_id"),
            {"status": DSAR_STATUS_IN_PROGRESS, "actor_id": actor_id, "request_id": request_id},
        )

        verification = {}
        if req.get("verification_data"):
            try:
                verification = json.loads(req["verification_data"])
            except (json.JSONDecodeError, TypeError):
                pass

        claim_ids: list[str] = []
        if verification.get("claim_id"):
            claim_ids.append(str(verification["claim_id"]))
        if verification.get("policy_number") and verification.get("vin"):
            rows = conn.execute(
                text("SELECT id FROM claims WHERE policy_number = :pn AND vin = :vin"),
                {"pn": verification["policy_number"], "vin": verification["vin"]},
            ).fetchall()
            for r in rows:
                cid = r[0] if hasattr(r, "__getitem__") else r["id"]
                if cid not in claim_ids:
                    claim_ids.append(str(cid))
        if not claim_ids and req.get("claimant_identifier"):
            rows = conn.execute(
                text("SELECT DISTINCT claim_id FROM claim_parties WHERE email = :email"),
                {"email": req["claimant_identifier"]},
            ).fetchall()
            for r in rows:
                claim_ids.append(str(r[0] if hasattr(r, "__getitem__") else r["claim_id"]))

        anonymized_claims = 0
        anonymized_parties = 0
        skipped_litigation = 0

        for claim_id in claim_ids:
            hold_row = conn.execute(
                text("SELECT litigation_hold FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if hold_row and (hold_row[0] if hasattr(hold_row, "__getitem__") else hold_row.get("litigation_hold")):
                skipped_litigation += 1
                continue

            conn.execute(
                text("""
                    UPDATE claims SET policy_number = :redacted, vin = :redacted,
                    attachments = '[]', updated_at = :now WHERE id = :claim_id
                """),
                {"redacted": REDACTED, "claim_id": claim_id, "now": datetime.now(timezone.utc).isoformat()},
            )
            anonymized_claims += 1

            party_count = conn.execute(
                text("SELECT COUNT(*) FROM claim_parties WHERE claim_id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            n_parties = party_count[0] if party_count and hasattr(party_count, "__getitem__") else 0

            conn.execute(
                text("""
                    UPDATE claim_parties SET name = :redacted, email = :redacted,
                    phone = :redacted, address = :redacted, updated_at = :now
                    WHERE claim_id = :claim_id
                """),
                {"redacted": REDACTED, "claim_id": claim_id, "now": datetime.now(timezone.utc).isoformat()},
            )
            anonymized_parties += n_parties

        conn.execute(
            text("""
                UPDATE dsar_requests SET status = :status, completed_at = :completed_at
                WHERE request_id = :request_id
            """),
            {
                "status": DSAR_STATUS_COMPLETED,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
            },
        )

    return {
        "request_id": request_id,
        "anonymized_claims": anonymized_claims,
        "anonymized_parties": anonymized_parties,
        "skipped_litigation_hold": skipped_litigation,
    }


def revoke_consent_by_email(
    email: str,
    *,
    db_path: str | None = None,
    actor_id: str = "dsar",
) -> int:
    """Revoke data processing consent for all parties with the given email.

    Returns the number of parties updated.
    """
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        result = conn.execute(
            text(
                "UPDATE claim_parties SET consent_status = 'revoked', updated_at = :now "
                "WHERE email = :email AND consent_status != 'revoked'"
            ),
            {"email": email, "now": datetime.now(timezone.utc).isoformat()},
        )
        return result.rowcount if hasattr(result, "rowcount") else 0


def list_dsar_requests(
    *,
    status: str | None = None,
    request_type: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """List DSAR requests, optionally filtered by status and/or request_type."""
    path = db_path or get_db_path()
    query = "SELECT * FROM dsar_requests WHERE 1=1"
    params: dict[str, Any] = {}
    if status:
        query += " AND status = :status"
        params["status"] = status
    if request_type:
        query += " AND request_type = :request_type"
        params["request_type"] = request_type
    query += " ORDER BY requested_at DESC"

    with get_connection(path) as conn:
        rows = conn.execute(text(query), params).fetchall()
        return [row_to_dict(r) for r in rows]
