"""Payment repository: CRUD for claim_payments, authority checks, status transitions."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.config.settings import get_payment_config
from claim_agent.db.audit_events import (
    ACTOR_SYSTEM,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_PAYMENT_AUTHORIZED,
    AUDIT_EVENT_PAYMENT_CLEARED,
    AUDIT_EVENT_PAYMENT_ISSUED,
    AUDIT_EVENT_PAYMENT_VOIDED,
)
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import (
    ClaimNotFoundError,
    DomainValidationError,
    PaymentAuthorityError,
    PaymentNotFoundError,
)
from claim_agent.models.payment import (
    ClaimPaymentCreate,
    PaymentStatus,
)
from claim_agent.utils.sanitization import sanitize_actor_id, sanitize_payee

_STATUS_AUTHORIZED = PaymentStatus.AUTHORIZED.value
_STATUS_ISSUED = PaymentStatus.ISSUED.value
_STATUS_CLEARED = PaymentStatus.CLEARED.value
_STATUS_VOIDED = PaymentStatus.VOIDED.value

_EXTERNAL_REF_MAX = 200


def normalize_payment_external_ref(external_ref: str | None) -> str | None:
    """Strip and truncate external_ref the same way as ``create_payment`` persistence."""
    return (external_ref or "").strip()[:_EXTERNAL_REF_MAX] or None


def settlement_payee_and_party_id_from_claim_data(claim_data: dict) -> tuple[str, int | None]:
    """Primary payee label and DB party id for automated settlement disbursement.

    Returns (payee, claim_party_id) from the same matched party to maintain referential integrity.
    Prefers claimant, then policyholder. Returns ("Claimant", None) if no valid party is found.
    """
    parties = claim_data.get("parties") or []
    if not isinstance(parties, list):
        return ("Claimant", None)
    for pref in ("claimant", "policyholder"):
        for p in parties:
            if not isinstance(p, dict):
                continue
            if (p.get("party_type") or "").lower() != pref:
                continue
            name = (p.get("name") or "").strip()
            raw_id = p.get("id")
            sanitized = sanitize_payee(name) if name else None
            if sanitized:
                party_id: int | None = None
                if raw_id is not None:
                    try:
                        party_id = int(raw_id)
                    except (TypeError, ValueError):
                        pass
                return (sanitized, party_id)
    return ("Claimant", None)


def settlement_payee_from_claim_data(claim_data: dict) -> str:
    """Primary payee label for automated settlement disbursement rows."""
    payee, _ = settlement_payee_and_party_id_from_claim_data(claim_data)
    return payee


def settlement_claim_party_id_from_claim_data(claim_data: dict) -> int | None:
    """DB party id for automated settlement disbursement, if present on embedded parties."""
    _, party_id = settlement_payee_and_party_id_from_claim_data(claim_data)
    return party_id


_VALID_TRANSITIONS: dict[str, set[str]] = {
    _STATUS_AUTHORIZED: {_STATUS_ISSUED, _STATUS_VOIDED},
    _STATUS_ISSUED: {_STATUS_CLEARED, _STATUS_VOIDED},
    _STATUS_CLEARED: set(),
    _STATUS_VOIDED: set(),
}


def _check_payment_authority(
    amount: float,
    actor_id: str,
    *,
    role: str = "adjuster",
    skip_authority_check: bool = False,
) -> None:
    """Raise PaymentAuthorityError if amount exceeds actor's limit."""
    if skip_authority_check or actor_id in (ACTOR_WORKFLOW, ACTOR_SYSTEM):
        return
    cfg = get_payment_config()
    if role in ("executive", "admin"):
        limit = cfg["executive_limit"]
    elif role in ("supervisor",):
        limit = cfg["supervisor_limit"]
    else:
        limit = cfg["adjuster_limit"]
    if amount > limit:
        raise PaymentAuthorityError(amount, limit, actor_id, role)


def _validate_status_transition(old_status: str, new_status: str) -> None:
    """Raise DomainValidationError if transition is invalid."""
    allowed = _VALID_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise DomainValidationError(
            f"Invalid payment status transition: {old_status} -> {new_status}"
        )


class PaymentRepository:
    """Repository for claim payment persistence and audit logging."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def _reconcile_idempotent_party_id(
        self,
        conn: Any,
        payment_id: int,
        existing_party_id: int | None,
        new_party_id: int | None,
        claim_id: str,
    ) -> int:
        """Reconcile claim_party_id on an existing idempotent payment.

        If *new_party_id* is provided and *existing_party_id* is NULL, validates that the
        party belongs to *claim_id* and backfills the column. If *existing_party_id* already
        has a different non-NULL value, raises DomainValidationError to surface the conflict.
        Returns *payment_id* in all success cases.
        """
        if new_party_id is None or new_party_id == existing_party_id:
            # When IDs match, we trust the FK constraint already enforces referential integrity;
            # re-validating ownership on every idempotent retry would add unnecessary overhead.
            return payment_id
        if existing_party_id is not None:
            raise DomainValidationError(
                f"claim_party_id mismatch on idempotent payment {payment_id}: "
                f"existing={existing_party_id}, provided={new_party_id}"
            )
        # existing_party_id is None – validate and backfill
        prow = conn.execute(
            text("SELECT id FROM claim_parties WHERE id = :pid AND claim_id = :claim_id"),
            {"pid": new_party_id, "claim_id": claim_id},
        ).fetchone()
        if prow is None:
            raise DomainValidationError(
                f"claim_party_id {new_party_id} does not belong to claim {claim_id}"
            )
        conn.execute(
            text("UPDATE claim_payments SET claim_party_id = :pid WHERE id = :payment_id"),
            {"pid": new_party_id, "payment_id": payment_id},
        )
        return payment_id

    def create_payment(
        self,
        data: ClaimPaymentCreate,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        role: str = "adjuster",
        skip_authority_check: bool = False,
    ) -> int:
        """Create a new payment in authorized status. Returns payment id."""
        _check_payment_authority(
            data.amount, actor_id, role=role, skip_authority_check=skip_authority_check
        )
        safe_actor = sanitize_actor_id(actor_id)
        safe_payee = sanitize_payee(data.payee)
        if not safe_payee:
            raise DomainValidationError(
                "Primary payee name is required and must not be empty after sanitization"
            )
        if data.payee_secondary:
            safe_payee_secondary = sanitize_payee(data.payee_secondary) or None
        else:
            safe_payee_secondary = None
        ext_ref = normalize_payment_external_ref(data.external_ref)
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": data.claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {data.claim_id}")
            if ext_ref is not None:
                existing = conn.execute(
                    text(
                        "SELECT id, claim_party_id FROM claim_payments WHERE claim_id = :claim_id "
                        "AND external_ref = :external_ref"
                    ),
                    {"claim_id": data.claim_id, "external_ref": ext_ref},
                ).fetchone()
                if existing is not None:
                    return self._reconcile_idempotent_party_id(
                        conn, int(existing[0]), existing[1], data.claim_party_id, data.claim_id
                    )
            party_id: int | None = data.claim_party_id
            if party_id is not None:
                prow = conn.execute(
                    text(
                        "SELECT id FROM claim_parties WHERE id = :pid AND claim_id = :claim_id"
                    ),
                    {"pid": party_id, "claim_id": data.claim_id},
                ).fetchone()
                if prow is None:
                    raise DomainValidationError(
                        f"claim_party_id {party_id} does not belong to claim {data.claim_id}"
                    )
            insert_params = {
                "claim_id": data.claim_id,
                "amount": data.amount,
                "payee": safe_payee,
                "payee_type": data.payee_type.value,
                "payment_method": data.payment_method.value,
                "check_number": data.check_number,
                "status": _STATUS_AUTHORIZED,
                "authorized_by": safe_actor,
                "payee_secondary": safe_payee_secondary,
                "payee_secondary_type": data.payee_secondary_type.value
                if data.payee_secondary_type
                else None,
                "external_ref": ext_ref,
                "claim_party_id": party_id,
            }
            insert_sql = text("""
                INSERT INTO claim_payments
                    (claim_id, amount, payee, payee_type, payment_method, check_number,
                     status, authorized_by, payee_secondary, payee_secondary_type, external_ref,
                     claim_party_id)
                VALUES (:claim_id, :amount, :payee, :payee_type, :payment_method, :check_number,
                        :status, :authorized_by, :payee_secondary, :payee_secondary_type, :external_ref,
                        :claim_party_id)
                RETURNING id
                """)
            try:
                result = conn.execute(insert_sql, insert_params)
            except IntegrityError:
                conn.rollback()
                if ext_ref is None:
                    raise
                existing = conn.execute(
                    text(
                        "SELECT id, claim_party_id FROM claim_payments WHERE claim_id = :claim_id "
                        "AND external_ref = :external_ref"
                    ),
                    {"claim_id": data.claim_id, "external_ref": ext_ref},
                ).fetchone()
                if existing is not None:
                    return self._reconcile_idempotent_party_id(
                        conn, int(existing[0]), existing[1], data.claim_party_id, data.claim_id
                    )
                raise
            rid = result.fetchone()
            payment_id = int(rid[0]) if rid else 0
            audit_payload: dict[str, Any] = {
                "payment_id": payment_id,
                "amount": data.amount,
                "payee": safe_payee,
                "payee_type": data.payee_type.value,
                "payment_method": data.payment_method.value,
            }
            if party_id is not None:
                audit_payload["claim_party_id"] = party_id
            details = json.dumps(audit_payload)
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": data.claim_id,
                    "action": AUDIT_EVENT_PAYMENT_AUTHORIZED,
                    "details": details,
                    "actor_id": safe_actor,
                },
            )
        return payment_id

    def get_payment(self, payment_id: int) -> dict[str, Any] | None:
        """Fetch payment by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_payment_by_claim_external_ref(
        self, claim_id: str, external_ref: str | None
    ) -> dict[str, Any] | None:
        """Find a payment by (claim_id, external_ref). Returns None if not found."""
        normalized_ref = normalize_payment_external_ref(external_ref)
        if normalized_ref is None:
            return None
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM claim_payments "
                    "WHERE claim_id = :claim_id AND external_ref = :external_ref"
                ),
                {"claim_id": claim_id, "external_ref": normalized_ref},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_payments_for_claim(
        self,
        claim_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List payments for a claim. Returns (payments, total)."""
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
                text(f"SELECT COUNT(*) as cnt FROM claim_payments WHERE {where}"),
                count_params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""
                SELECT * FROM claim_payments WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def issue_payment(
        self,
        payment_id: int,
        *,
        check_number: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> dict[str, Any]:
        """Transition payment from authorized to issued. Optionally set check_number."""
        safe_actor = sanitize_actor_id(actor_id)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
            if row is None:
                raise PaymentNotFoundError(f"Payment not found: {payment_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            _validate_status_transition(old_status, _STATUS_ISSUED)
            claim_id = row_d["claim_id"]
            safe_check_number = check_number.strip()[:100] if check_number is not None else None
            params: dict[str, Any] = {"status": _STATUS_ISSUED, "now": now, "id": payment_id}
            if safe_check_number is not None:
                conn.execute(
                    text("""
                    UPDATE claim_payments
                    SET status = :status, issued_at = :now, updated_at = :now, check_number = :check_number
                    WHERE id = :id
                    """),
                    {**params, "check_number": safe_check_number},
                )
            else:
                conn.execute(
                    text("""
                    UPDATE claim_payments
                    SET status = :status, issued_at = :now, updated_at = :now
                    WHERE id = :id
                    """),
                    params,
                )
            details = json.dumps({"payment_id": payment_id, "check_number": safe_check_number})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_PAYMENT_ISSUED,
                    "details": details,
                    "actor_id": safe_actor,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
        return row_to_dict(updated)

    def clear_payment(
        self,
        payment_id: int,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> dict[str, Any]:
        """Transition payment from issued to cleared."""
        safe_actor = sanitize_actor_id(actor_id)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
            if row is None:
                raise PaymentNotFoundError(f"Payment not found: {payment_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            _validate_status_transition(old_status, _STATUS_CLEARED)
            claim_id = row_d["claim_id"]
            conn.execute(
                text("""
                UPDATE claim_payments
                SET status = :status, cleared_at = :now, updated_at = :now
                WHERE id = :id
                """),
                {"status": _STATUS_CLEARED, "now": now, "id": payment_id},
            )
            details = json.dumps({"payment_id": payment_id})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_PAYMENT_CLEARED,
                    "details": details,
                    "actor_id": safe_actor,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
        return row_to_dict(updated)

    def void_payment(
        self,
        payment_id: int,
        *,
        reason: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> dict[str, Any]:
        """Void a payment (authorized or issued). Reversal workflow."""
        safe_actor = sanitize_actor_id(actor_id)
        safe_reason = (reason or "").strip()[:500] if reason else None
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
            if row is None:
                raise PaymentNotFoundError(f"Payment not found: {payment_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            _validate_status_transition(old_status, _STATUS_VOIDED)
            claim_id = row_d["claim_id"]
            conn.execute(
                text("""
                UPDATE claim_payments
                SET status = :status, voided_at = :now, void_reason = :reason, updated_at = :now
                WHERE id = :id
                """),
                {"status": _STATUS_VOIDED, "now": now, "reason": safe_reason, "id": payment_id},
            )
            details = json.dumps({"payment_id": payment_id, "void_reason": safe_reason})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_PAYMENT_VOIDED,
                    "details": details,
                    "actor_id": safe_actor,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM claim_payments WHERE id = :id"),
                {"id": payment_id},
            ).fetchone()
        return row_to_dict(updated)
