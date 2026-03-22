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

from claim_agent.compliance.dsar_state_rules import get_state_response_metadata
from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.pii_redaction import anonymize_claim_pii
from claim_agent.services.dsar_verification import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    claimant_identifiers_match,
)


DSAR_REQUEST_ACCESS = "access"
DSAR_REQUEST_DELETION = "deletion"
DSAR_STATUS_PENDING = "pending"
DSAR_STATUS_IN_PROGRESS = "in_progress"
DSAR_STATUS_COMPLETED = "completed"
DSAR_STATUS_REJECTED = "rejected"


def claim_ids_from_verification_dict(conn: Any, verification: dict[str, Any]) -> list[str]:
    """Resolve claim IDs from ``claim_id`` and/or ``policy_number`` + ``vin``."""
    claim_ids: list[str] = []
    if verification.get("claim_id"):
        claim_ids.append(str(verification["claim_id"]))
    if verification.get("policy_number") and verification.get("vin"):
        rows = conn.execute(
            text("SELECT id FROM claims WHERE policy_number = :pn AND vin = :vin"),
            {
                "pn": verification["policy_number"],
                "vin": verification["vin"],
            },
        ).fetchall()
        for r in rows:
            cid = r[0] if hasattr(r, "__getitem__") else r["id"]
            if cid not in claim_ids:
                claim_ids.append(str(cid))
    return claim_ids


def assert_self_service_party_binding(
    claimant_identifier: str,
    channel: str,
    verification_data: dict[str, Any],
    *,
    db_path: str | None = None,
) -> None:
    """Require that *claimant_identifier* appears on a party row for resolved claims.

    Used after OTP verification so a user cannot request DSAR data for arbitrary
    ``claim_id`` / policy+VIN pairs.

    Raises:
        ValueError: If claims cannot be resolved or no party matches the verified channel.
    """
    if channel not in (CHANNEL_EMAIL, CHANNEL_SMS):
        raise ValueError(f"Invalid OTP channel {channel!r}.")
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        claim_ids = claim_ids_from_verification_dict(conn, verification_data)
        if not claim_ids:
            raise ValueError(
                "No claim found for the supplied verification (claim_id or policy_number and vin)."
            )
        for claim_id in claim_ids:
            rows = conn.execute(
                text("SELECT email, phone FROM claim_parties WHERE claim_id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchall()
            for row in rows:
                party = row_to_dict(row)
                email = party.get("email")
                phone = party.get("phone")
                if channel == CHANNEL_EMAIL and email and claimant_identifiers_match(
                    claimant_identifier, email, CHANNEL_EMAIL
                ):
                    return
                if channel == CHANNEL_SMS and phone and claimant_identifiers_match(
                    claimant_identifier, phone, CHANNEL_SMS
                ):
                    return
        raise ValueError(
            "Verified contact is not associated with this claim. "
            "Use the email or phone on file for the claim, or contact support."
        )


def submit_access_request(
    claimant_identifier: str,
    verification_data: dict[str, Any],
    *,
    db_path: str | None = None,
    actor_id: str = "claimant",
    state: str | None = None,
) -> str:
    """Submit a DSAR access request. Returns request_id.

    Args:
        claimant_identifier: Email or hashed policy+vin identifier.
        verification_data: Dict with claim_id and/or policy_number, vin for verification.
        db_path: Optional DB path. Uses default when None.
        actor_id: Actor submitting the request.
        state: Consumer's state of residence (e.g., ``"California"``). When provided,
            state-specific response metadata is embedded in the fulfilled export.

    Returns:
        Unique request_id (UUID string) for tracking.
    """
    request_id = str(uuid.uuid4())
    path = db_path or get_db_path()
    vdata = dict(verification_data) if verification_data else {}
    if state:
        vdata["state"] = state
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
                "verification_data": json.dumps(vdata) if vdata else None,
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
    Collects: claims, claim_parties, party_relationships (structural edge
    metadata), claim_audit_log (action, dates, actor_id), claim_notes,
    documents metadata.

    Party relationships contain no PII (only party ids, relationship_type, and
    timestamps) and are exported unchanged even for anonymized/redacted claims.

    Args:
        request_id: DSAR request ID from submit_access_request.
        db_path: Optional DB path.
        actor_id: Actor fulfilling the request.

    Returns:
        Dict with claims, parties, party_relationships, audit_entries, notes for
        the claimant.

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

        verification = {}
        if req.get("verification_data"):
            try:
                verification = json.loads(req["verification_data"])
            except (json.JSONDecodeError, TypeError):
                pass

        claim_ids = claim_ids_from_verification_dict(conn, verification)

        # Also match by claimant_identifier (email) in claim_parties when verification not required
        if not claim_ids and req.get("claimant_identifier"):
            if not get_settings().privacy.dsar_verification_required:
                rows = conn.execute(
                    text(
                        "SELECT DISTINCT claim_id FROM claim_parties WHERE email = :email"
                    ),
                    {"email": req["claimant_identifier"]},
                ).fetchall()
                for r in rows:
                    cid = r[0] if hasattr(r, "__getitem__") else row_to_dict(r).get("claim_id")
                    if cid not in claim_ids:
                        claim_ids.append(str(cid))
            else:
                _reject_dsar_request(conn, request_id, actor_id)
                raise ValueError(
                    "Verification required: provide claim_id or policy_number+vin. "
                    "claimant_identifier-only lookup is disabled when DSAR_VERIFICATION_REQUIRED=true."
                )

        # Mark in progress only after validation succeeds
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

        state_from_verification = verification.get("state")
        export: dict[str, Any] = {
            "request_id": request_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "state_response_info": get_state_response_metadata(state_from_verification),
            "claims": [],
            "parties": [],
            "party_relationships": [],
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

            # Party relationships are structural metadata (no PII); export unchanged
            # even after anonymization — redacted party rows still have valid IDs.
            rel_rows = conn.execute(
                text(
                    "SELECT DISTINCT cpr.id, cpr.from_party_id, cpr.to_party_id, "
                    "cpr.relationship_type, cpr.created_at "
                    "FROM claim_party_relationships cpr "
                    "WHERE cpr.from_party_id IN "
                    "(SELECT id FROM claim_parties WHERE claim_id = :claim_id) "
                    "OR cpr.to_party_id IN "
                    "(SELECT id FROM claim_parties WHERE claim_id = :claim_id)"
                ),
                {"claim_id": claim_id},
            ).fetchall()
            for rr in rel_rows:
                export["party_relationships"].append(row_to_dict(rr))

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

        _log_dsar_audit(
            conn,
            DSAR_AUDIT_ACCESS_FULFILL,
            actor_id,
            request_id=request_id,
            details={"claim_count": len(claim_ids)},
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


DSAR_AUDIT_ACCESS_FULFILL = "access_fulfill"
DSAR_AUDIT_DELETION_FULFILL = "deletion_fulfill"
DSAR_AUDIT_CONSENT_REVOKE = "consent_revoke"


def _reject_dsar_request(conn: Any, request_id: str, actor_id: str) -> None:
    """Mark a DSAR request as rejected (e.g. validation failed before fulfillment)."""
    conn.execute(
        text(
            "UPDATE dsar_requests SET status = :status, completed_at = :completed_at, actor_id = :actor_id "
            "WHERE request_id = :request_id"
        ),
        {
            "status": DSAR_STATUS_REJECTED,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor_id,
            "request_id": request_id,
        },
    )


def _log_dsar_audit(
    conn: Any,
    action: str,
    actor_id: str,
    *,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an audit entry for DSAR operations."""
    details_json = json.dumps(details) if details else None
    conn.execute(
        text("""
            INSERT INTO dsar_audit_log (request_id, action, actor_id, details)
            VALUES (:request_id, :action, :actor_id, :details)
        """),
        {
            "request_id": request_id,
            "action": action,
            "actor_id": actor_id,
            "details": details_json,
        },
    )


def submit_deletion_request(
    claimant_identifier: str,
    verification_data: dict[str, Any],
    *,
    db_path: str | None = None,
    actor_id: str = "claimant",
    state: str | None = None,
) -> str:
    """Submit a DSAR deletion request. Returns request_id.

    Args:
        claimant_identifier: Email or hashed policy+vin identifier.
        verification_data: Dict with claim_id and/or policy_number, vin for verification.
        db_path: Optional DB path. Uses default when None.
        actor_id: Actor submitting the request.
        state: Consumer's state of residence (e.g., ``"California"``). Stored for
            audit and state-specific processing.
    """
    request_id = str(uuid.uuid4())
    path = db_path or get_db_path()
    vdata = dict(verification_data) if verification_data else {}
    if state:
        vdata["state"] = state
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
                "verification_data": json.dumps(vdata) if vdata else None,
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

        verification = {}
        if req.get("verification_data"):
            try:
                verification = json.loads(req["verification_data"])
            except (json.JSONDecodeError, TypeError):
                pass

        claim_ids = claim_ids_from_verification_dict(conn, verification)

        if not claim_ids and req.get("claimant_identifier"):
            if get_settings().privacy.dsar_verification_required:
                _reject_dsar_request(conn, request_id, actor_id)
                raise ValueError(
                    "Verification required: provide claim_id or policy_number+vin. "
                    "claimant_identifier-only lookup is disabled when DSAR_VERIFICATION_REQUIRED=true."
                )
            rows = conn.execute(
                text("SELECT DISTINCT claim_id FROM claim_parties WHERE email = :email"),
                {"email": req["claimant_identifier"]},
            ).fetchall()
            for r in rows:
                cid = r[0] if hasattr(r, "__getitem__") else row_to_dict(r).get("claim_id")
                if cid not in claim_ids:
                    claim_ids.append(str(cid))

        # Mark in progress only after validation succeeds
        conn.execute(
            text("UPDATE dsar_requests SET status = :status, actor_id = :actor_id WHERE request_id = :request_id"),
            {"status": DSAR_STATUS_IN_PROGRESS, "actor_id": actor_id, "request_id": request_id},
        )

        blocks_deletion = get_settings().privacy.litigation_hold_blocks_deletion
        anonymized_claims = 0
        anonymized_parties = 0
        skipped_litigation = 0

        for claim_id in claim_ids:
            if blocks_deletion:
                hold_row = conn.execute(
                    text("SELECT litigation_hold FROM claims WHERE id = :claim_id"),
                    {"claim_id": claim_id},
                ).fetchone()
                if hold_row and (hold_row[0] if hasattr(hold_row, "__getitem__") else hold_row.get("litigation_hold")):
                    skipped_litigation += 1
                    continue

            now_iso = datetime.now(timezone.utc).isoformat()
            _, n_parties = anonymize_claim_pii(
                conn,
                claim_id,
                now_iso=now_iso,
                notes_redaction_text="[REDACTED - DSAR deletion]",
            )
            anonymized_claims += 1
            anonymized_parties += n_parties

        # Note: claim_audit_log (details, before_state, after_state) is preserved for
        # legal/regulatory requirements; audit trail is typically retained per compliance practice.
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

        _log_dsar_audit(
            conn,
            DSAR_AUDIT_DELETION_FULFILL,
            actor_id,
            request_id=request_id,
            details={
                "anonymized_claims": anonymized_claims,
                "anonymized_parties": anonymized_parties,
                "skipped_litigation_hold": skipped_litigation,
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
        count = result.rowcount if hasattr(result, "rowcount") else 0
        _log_dsar_audit(
            conn,
            DSAR_AUDIT_CONSENT_REVOKE,
            actor_id,
            details={"email": email, "parties_updated": count},
        )
        return count


def list_dsar_requests(
    *,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List DSAR requests, optionally filtered by status and/or request_type.

    Returns:
        Tuple of (items, total_count).
    """
    path = db_path or get_db_path()
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    if status:
        where += " AND status = :status"
        params["status"] = status
    if request_type:
        where += " AND request_type = :request_type"
        params["request_type"] = request_type

    with get_connection(path) as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) FROM dsar_requests {where}"),
            params,
        ).fetchone()
        total = count_row[0] if count_row and hasattr(count_row, "__getitem__") else 0

        params["limit"] = limit
        params["offset"] = offset
        rows = conn.execute(
            text(f"SELECT * FROM dsar_requests {where} ORDER BY requested_at DESC LIMIT :limit OFFSET :offset"),
            params,
        ).fetchall()
        return [row_to_dict(r) for r in rows], total
