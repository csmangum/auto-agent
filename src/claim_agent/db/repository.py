"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only: it only inserts new
audit entries and does not perform UPDATE or DELETE operations on that table.
"""

import calendar
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from claim_agent.models.claim import Attachment

from claim_agent.db.audit_events import (
    ACTOR_RETENTION,
    ACTOR_SYSTEM,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_ACKNOWLEDGED,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_ASSIGN,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
    AUDIT_EVENT_CLAIM_REVIEW,
    AUDIT_EVENT_COVERAGE_VERIFICATION,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_DENIAL_LETTER,
    AUDIT_EVENT_ESCALATE_TO_SIU,
    AUDIT_EVENT_FOLLOW_UP_RESPONSE,
    AUDIT_EVENT_FOLLOW_UP_SENT,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REQUEST_INFO,
    AUDIT_EVENT_RESERVE_ADJUSTED,
    AUDIT_EVENT_RESERVE_ADEQUACY_GATE,
    AUDIT_EVENT_RESERVE_SET,
    AUDIT_EVENT_LITIGATION_HOLD,
    AUDIT_EVENT_RETENTION,
    AUDIT_EVENT_RETENTION_PURGED,
    AUDIT_EVENT_SIU_CASE_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
    AUDIT_EVENT_TASK_CREATED,
    AUDIT_EVENT_TASK_UPDATED,
)
from claim_agent.db.constants import (
    RETENTION_TIER_ACTIVE,
    RETENTION_TIER_ARCHIVED,
    RETENTION_TIER_COLD,
    RETENTION_TIER_PURGED,
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_PURGED,
    STATUS_SETTLED,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.db.reserve_adequacy import compute_reserve_adequacy_details
from claim_agent.config.settings import get_reserve_config
from claim_agent.rag.constants import normalize_state
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.db.pii_redaction import anonymize_claim_pii
from claim_agent.db.state_machine import validate_transition
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError, ReserveAuthorityError
from claim_agent.utils.sanitization import (
    sanitize_actor_id,
    sanitize_denial_reason,
    sanitize_note,
    sanitize_resolution_notes,
    sanitize_task_description,
    sanitize_task_title,
    truncate_audit_json,
)
from claim_agent.events import ClaimEvent, emit_claim_event
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput

# Relation types for build_relationship_snapshot edges
RELATION_SHARED_VIN = "shared_vin"
RELATION_SHARED_ADDRESS = "shared_address"
RELATION_SHARED_PROVIDER = "shared_provider"


def _generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _claim_row_for_status_validation(row_d: dict[str, Any]) -> dict[str, Any]:
    """Subset of claim row for validate_transition; normalizes 0/1 DB flags to bool."""
    out = dict(row_d)
    for key in ("repair_ready_for_settlement", "total_loss_settlement_authorized"):
        if key not in out:
            continue
        val = out.get(key)
        if val is None:
            del out[key]
        else:
            out[key] = bool(val)
    return out


def _apply_ucspa_at_fnol(
    repo: "ClaimRepository",
    claim_id: str,
    loss_state: str | None,
) -> None:
    """Set UCSPA deadlines on claim and create compliance tasks at FNOL."""
    from claim_agent.compliance.ucspa import create_ucspa_compliance_tasks, get_ucspa_deadlines

    base_date = date.today()  # receipt date = FNOL date
    deadlines = get_ucspa_deadlines(base_date, loss_state)
    with get_connection(repo._db_path) as conn:
        updates: list[str] = []
        params: dict[str, Any] = {"id": claim_id}
        for col in ("acknowledgment_due", "investigation_due", "payment_due"):
            val = deadlines.get(col)
            if val:
                updates.append(f"{col} = :{col}")
                params[col] = val
        if updates:
            conn.execute(
                text(f"UPDATE claims SET {', '.join(updates)} WHERE id = :id"),
                params,
            )
    create_ucspa_compliance_tasks(repo, claim_id, loss_state, base_date)


def _check_reserve_authority(
    amount: float,
    actor_id: str,
    *,
    role: str = "adjuster",
    skip_authority_check: bool = False,
) -> None:
    """Enforce reserve amount vs configured role limits.

    No check (returns immediately) when ``skip_authority_check`` is true or when
    ``actor_id`` is the workflow or system actor.

    Otherwise: adjusters use ``adjuster_limit``; supervisors and admins use
    ``supervisor_limit``; executives use ``executive_limit`` if it is positive,
    or are unconstrained when that limit is not configured (<= 0).

    Raises ``ReserveAuthorityError`` when ``amount`` exceeds the applicable limit.
    """
    if skip_authority_check or actor_id in (ACTOR_WORKFLOW, ACTOR_SYSTEM):
        return
    r = (role or "adjuster").lower()
    cfg = get_reserve_config()
    exec_cap = float(cfg.get("executive_limit", 0.0))
    if r == "executive":
        if exec_cap <= 0:
            return
        if amount > exec_cap:
            raise ReserveAuthorityError(amount, exec_cap, actor_id, role)
        return
    if r in ("supervisor", "admin"):
        limit = cfg["supervisor_limit"]
    else:
        limit = cfg["adjuster_limit"]
    if amount > limit:
        raise ReserveAuthorityError(amount, limit, actor_id, role)


def _reserve_audit_reason(
    safe_reason: str,
    default_label: str,
    *,
    skip_authority_check: bool,
) -> str:
    """Human-readable reason for reserve_history and claim_audit_log."""
    core = safe_reason.strip() or default_label
    if skip_authority_check:
        return sanitize_note(core + " [authority check bypassed]")
    return core


def _is_claim_past_retention(
    row_d: dict[str, Any],
    now: datetime,
    retention_period_years: int,
    retention_by_state: dict[str, int],
) -> bool:
    """Return True if claim's created_at is past its retention cutoff.

    Uses loss_state to pick per-state retention when retention_by_state is non-empty;
    falls back to retention_period_years when state is missing or not in map.
    """
    raw_state = (row_d.get("loss_state") or "").strip()
    lookup_state: str | None = None
    if raw_state:
        try:
            lookup_state = normalize_state(raw_state)
        except ValueError:
            pass
    years = (
        retention_by_state.get(lookup_state) if lookup_state else None
    ) or retention_period_years
    cutoff_dt = now - timedelta(days=years * 365)
    created_raw = row_d.get("created_at")
    if not created_raw:
        return True
    created_dt: datetime
    if isinstance(created_raw, datetime):
        created_dt = created_raw
    elif isinstance(created_raw, str):
        try:
            created_dt = datetime.fromisoformat(created_raw)
        except ValueError:
            try:
                created_dt = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return True
    else:
        return True

    def _to_utc_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    cutoff_norm = _to_utc_aware(cutoff_dt)
    created_norm = _to_utc_aware(created_dt)
    return created_norm <= cutoff_norm


def _add_calendar_years(dt: datetime, years: int) -> datetime:
    """Return ``dt`` plus ``years`` calendar years (clamp day for short months, e.g. Feb 29)."""
    new_year = dt.year + years
    month = dt.month
    last_day = calendar.monthrange(new_year, month)[1]
    new_day = min(dt.day, last_day)
    return dt.replace(year=new_year, month=month, day=new_day)


def _is_archived_past_purge_period(
    row_d: dict[str, Any],
    now: datetime,
    purge_after_archive_years: int,
) -> bool:
    """True if ``now`` is on or after the calendar anniversary of archived_at + N years."""
    if purge_after_archive_years < 0:
        raise ValueError("purge_after_archive_years must be non-negative")
    archived_raw = row_d.get("archived_at")
    if not archived_raw:
        return False

    def _to_utc_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    archived_dt: datetime
    if isinstance(archived_raw, datetime):
        archived_dt = archived_raw
    elif isinstance(archived_raw, str):
        try:
            archived_dt = datetime.fromisoformat(archived_raw)
        except ValueError:
            try:
                archived_dt = datetime.strptime(archived_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return False
    else:
        return False

    cutoff = _add_calendar_years(_to_utc_aware(archived_dt), purge_after_archive_years)
    return _to_utc_aware(now) >= cutoff


class ClaimRepository:
    """Repository for claim persistence and audit logging."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    @property
    def db_path(self) -> str | None:
        """SQLite path override from construction, or None for configured default."""
        return self._db_path

    def create_claim(
        self,
        claim_input: ClaimInput,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> str:
        """Insert new claim, generate ID, log 'created' audit entry. Returns claim_id."""
        claim_id = _generate_claim_id()
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in claim_input.attachments],
            default=str,
        )
        loss_state_val = claim_input.loss_state
        if loss_state_val is not None:
            loss_state_val = str(loss_state_val).strip() or None
        incident_id_val = claim_input.incident_id
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, loss_state, status, attachments, incident_id, retention_tier
                ) VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                         :incident_date, :incident_description, :damage_description, :estimated_damage,
                         :claim_type, :loss_state, :status, :attachments, :incident_id, :retention_tier)
                """),
                {
                    "id": claim_id,
                    "policy_number": claim_input.policy_number,
                    "vin": claim_input.vin,
                    "vehicle_year": claim_input.vehicle_year,
                    "vehicle_make": claim_input.vehicle_make,
                    "vehicle_model": claim_input.vehicle_model,
                    "incident_date": claim_input.incident_date.isoformat(),
                    "incident_description": claim_input.incident_description,
                    "damage_description": claim_input.damage_description,
                    "estimated_damage": claim_input.estimated_damage,
                    "claim_type": None,
                    "loss_state": loss_state_val,
                    "status": STATUS_PENDING,
                    "attachments": attachments_json,
                    "incident_id": incident_id_val,
                    "retention_tier": RETENTION_TIER_ACTIVE,
                },
            )
            after_state = json.dumps(
                {"status": STATUS_PENDING, "claim_type": None, "payout_amount": None}
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state)
                VALUES (:claim_id, :action, :new_status, :details, :actor_id, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_CREATED,
                    "new_status": STATUS_PENDING,
                    "details": "Claim record created",
                    "actor_id": actor_id,
                    "after_state": after_state,
                },
            )
            # Set initial reserve from estimated_damage at FNOL if configured.
            cfg = get_reserve_config()
            est = claim_input.estimated_damage
            if (
                cfg.get("initial_reserve_from_estimated_damage", True)
                and est is not None
                and est > 0
            ):
                conn.execute(
                    text(
                        "UPDATE claims SET reserve_amount = :est, updated_at = :now WHERE id = :id"
                    ),
                    {"est": est, "now": now, "id": claim_id},
                )
                conn.execute(
                    text("""
                    INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                    VALUES (:claim_id, :old_amount, :new_amount, :reason, :actor_id)
                    """),
                    {
                        "claim_id": claim_id,
                        "old_amount": None,
                        "new_amount": est,
                        "reason": "Initial reserve from estimated_damage at FNOL",
                        "actor_id": ACTOR_SYSTEM,
                    },
                )
                reserve_state = json.dumps({"reserve_amount": est})
                conn.execute(
                    text("""
                    INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                    VALUES (:claim_id, :action, :details, :actor_id, :after_state)
                    """),
                    {
                        "claim_id": claim_id,
                        "action": AUDIT_EVENT_RESERVE_SET,
                        "details": "Initial reserve set from estimated_damage",
                        "actor_id": ACTOR_SYSTEM,
                        "after_state": reserve_state,
                    },
                )
        if claim_input.parties:
            for p in claim_input.parties:
                self.add_claim_party(claim_id, p)

        # UCSPA: set state-specific deadlines and create compliance tasks at FNOL
        try:
            _apply_ucspa_at_fnol(self, claim_id, loss_state_val)
        except (OperationalError, ProgrammingError) as e:
            # Columns absent if migration 026 has not been applied yet; warn and continue.
            logging.getLogger(__name__).warning(
                "ucspa_at_fnol_failed claim_id=%s: %s (run alembic upgrade head if UCSPA columns missing)",
                claim_id,
                e,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "ucspa_at_fnol_unexpected_error claim_id=%s", claim_id
            )
            raise

        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_PENDING, summary="Claim submitted")
        )
        return claim_id

    def add_claim_party(self, claim_id: str, party: ClaimPartyInput) -> int:
        """Insert a claim party. Returns party id."""
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                INSERT INTO claim_parties (
                    claim_id, party_type, name, email, phone, address, role,
                    represented_by_id, consent_status, authorization_status
                ) VALUES (:claim_id, :party_type, :name, :email, :phone, :address, :role,
                         :represented_by_id, :consent_status, :authorization_status)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "party_type": party.party_type,
                    "name": party.name,
                    "email": party.email,
                    "phone": party.phone,
                    "address": party.address,
                    "role": party.role,
                    "represented_by_id": party.represented_by_id,
                    "consent_status": party.consent_status or "pending",
                    "authorization_status": party.authorization_status or "pending",
                },
            )
            rid = result.fetchone()
            return int(rid[0]) if rid else 0

    def get_claim_parties(
        self, claim_id: str, party_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch parties for a claim, optionally filtered by party_type."""
        with get_connection(self._db_path) as conn:
            if party_type:
                rows = conn.execute(
                    text(
                        "SELECT * FROM claim_parties WHERE claim_id = :claim_id AND party_type = :party_type"
                    ),
                    {"claim_id": claim_id, "party_type": party_type},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("SELECT * FROM claim_parties WHERE claim_id = :claim_id"),
                    {"claim_id": claim_id},
                ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_claim_party_by_type(self, claim_id: str, party_type: str) -> dict[str, Any] | None:
        """Get first party of given type for a claim."""
        parties = self.get_claim_parties(claim_id, party_type=party_type)
        return parties[0] if parties else None

    def update_claim_party(self, party_id: int, updates: dict[str, Any]) -> None:
        """Update a claim party by id. Only provided keys are updated."""
        allowed = {
            "name",
            "email",
            "phone",
            "address",
            "role",
            "represented_by_id",
            "consent_status",
            "authorization_status",
        }
        to_set = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not to_set:
            return
        now = datetime.now(timezone.utc).isoformat()
        set_parts = [f"{k} = :{k}" for k in to_set] + ["updated_at = :now"]
        set_clause = ", ".join(set_parts)
        params: dict[str, Any] = dict(to_set)
        params["now"] = now
        params["id"] = party_id
        with get_connection(self._db_path) as conn:
            conn.execute(text(f"UPDATE claim_parties SET {set_clause} WHERE id = :id"), params)

    def get_primary_contact_for_user_type(
        self, claim_id: str, user_type: str
    ) -> dict[str, Any] | None:
        """Resolve contact for user_type. If claimant has attorney, return attorney.
        Maps: claimant->claimant or attorney; policyholder->policyholder.
        repair_shop/siu/adjuster/other: no party record, return None."""
        user_type = str(user_type).strip().lower()
        if user_type == "claimant":
            claimant = self.get_claim_party_by_type(claim_id, "claimant")
            if claimant and claimant.get("represented_by_id"):
                with get_connection(self._db_path) as conn:
                    row = conn.execute(
                        text("SELECT * FROM claim_parties WHERE id = :id AND claim_id = :claim_id"),
                        {"id": claimant["represented_by_id"], "claim_id": claim_id},
                    ).fetchone()
                if row:
                    attorney = row_to_dict(row)
                    if attorney.get("email") or attorney.get("phone"):
                        return attorney
            return (
                claimant
                if (claimant and (claimant.get("email") or claimant.get("phone")))
                else None
            )
        if user_type == "policyholder":
            ph = self.get_claim_party_by_type(claim_id, "policyholder")
            return ph if (ph and (ph.get("email") or ph.get("phone"))) else None
        return None

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch claim by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    def _append_reserve_adequacy_gate_audit(
        self,
        conn: Any,
        claim_id: str,
        new_status: str,
        claim_row: dict[str, Any],
        payout_amount: float | None,
        *,
        skip_adequacy_check: bool,
        role: str,
        actor_id: str,
    ) -> None:
        """Log reserve adequacy gate when closing/settling with inadequate reserve (warn or waiver)."""
        if new_status not in (STATUS_CLOSED, STATUS_SETTLED):
            return
        mode = (get_reserve_config().get("close_settle_adequacy_gate") or "warn").strip().lower()
        if mode not in ("off", "block", "warn"):
            mode = "warn"
        if mode == "off":
            return

        reserve = claim_row.get("reserve_amount")
        est = claim_row.get("estimated_damage")
        pay = payout_amount if payout_amount is not None else claim_row.get("payout_amount")

        def _f(v: Any) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        adequate, warnings, codes = compute_reserve_adequacy_details(_f(reserve), _f(est), _f(pay))
        if adequate:
            return

        r = (role or "adjuster").strip().lower()
        elevated = r in ("supervisor", "admin", "executive")
        if mode == "block" and not (skip_adequacy_check and elevated):
            return
        if skip_adequacy_check and elevated:
            details = (
                f"Reserve adequacy waived (role={role}); "
                f"warning_codes={','.join(codes)}; "
                + "; ".join(warnings[:5])
            )
        elif mode == "warn":
            details = (
                f"Reserve inadequate at status={new_status} (warn mode allows transition); "
                f"warning_codes={','.join(codes)}; "
                + "; ".join(warnings[:5])
            )
        else:
            return

        conn.execute(
            text("""
            INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
            VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id)
            """),
            {
                "claim_id": claim_id,
                "action": AUDIT_EVENT_RESERVE_ADEQUACY_GATE,
                "old_status": claim_row.get("status"),
                "new_status": new_status,
                "details": sanitize_note(details)[:2000],
                "actor_id": sanitize_actor_id(actor_id),
            },
        )

    def update_claim_status(
        self,
        claim_id: str,
        new_status: str,
        details: str | None = None,
        claim_type: str | None = None,
        payout_amount: float | None = None,
        *,
        repair_ready_for_settlement: bool | None = None,
        total_loss_settlement_authorized: bool | None = None,
        actor_id: str = ACTOR_WORKFLOW,
        skip_validation: bool = False,
        skip_adequacy_check: bool = False,
        role: str = "adjuster",
    ) -> None:
        """Update status, optionally claim_type, payout_amount, and settlement flags; audit.

        For transitions to ``closed`` or ``settled``, reserve adequacy may block or warn
        (``RESERVE_CLOSE_SETTLE_ADEQUACY_GATE``). Supervisor, admin, or executive may set
        ``skip_adequacy_check=True`` when the gate mode is ``block``.
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT status, claim_type, payout_amount, "
                    "repair_ready_for_settlement, total_loss_settlement_authorized, "
                    "reserve_amount, estimated_damage "
                    "FROM claims WHERE id = :claim_id"
                ),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            old_claim_type = row_d["claim_type"]
            old_payout = row_d["payout_amount"]
            old_rr = row_d.get("repair_ready_for_settlement")
            old_tla = row_d.get("total_loss_settlement_authorized")

            if not skip_validation:
                claim_dict = _claim_row_for_status_validation(row_d)
                if repair_ready_for_settlement is not None:
                    claim_dict["repair_ready_for_settlement"] = repair_ready_for_settlement
                if total_loss_settlement_authorized is not None:
                    claim_dict["total_loss_settlement_authorized"] = (
                        total_loss_settlement_authorized
                    )
                validation_claim_type = (
                    claim_type if claim_type is not None else row_d.get("claim_type")
                )
                validate_transition(
                    claim_id,
                    old_status,
                    new_status,
                    claim=claim_dict,
                    payout_amount=payout_amount,
                    claim_type=validation_claim_type,
                    actor_id=actor_id,
                    skip_adequacy_check=skip_adequacy_check,
                    role=role,
                )

            new_rr = (
                (1 if repair_ready_for_settlement else 0)
                if repair_ready_for_settlement is not None
                else old_rr
            )
            new_tla = (
                (1 if total_loss_settlement_authorized else 0)
                if total_loss_settlement_authorized is not None
                else old_tla
            )

            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
                "repair_ready_for_settlement": old_rr,
                "total_loss_settlement_authorized": old_tla,
            }
            after_state = {
                "status": new_status,
                "claim_type": claim_type if claim_type is not None else old_claim_type,
                "payout_amount": payout_amount if payout_amount is not None else old_payout,
                "repair_ready_for_settlement": new_rr,
                "total_loss_settlement_authorized": new_tla,
            }

            # Explicit parameterized queries (no dynamic SQL)
            if claim_type is not None and payout_amount is not None:
                conn.execute(
                    text("""UPDATE claims SET status = :status, claim_type = :claim_type, payout_amount = :payout_amount,
                       updated_at = :now WHERE id = :claim_id"""),
                    {
                        "status": new_status,
                        "claim_type": claim_type,
                        "payout_amount": payout_amount,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )
            elif claim_type is not None:
                conn.execute(
                    text("""UPDATE claims SET status = :status, claim_type = :claim_type,
                       updated_at = :now WHERE id = :claim_id"""),
                    {
                        "status": new_status,
                        "claim_type": claim_type,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )
            elif payout_amount is not None:
                conn.execute(
                    text("""UPDATE claims SET status = :status, payout_amount = :payout_amount,
                       updated_at = :now WHERE id = :claim_id"""),
                    {
                        "status": new_status,
                        "payout_amount": payout_amount,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )
            else:
                conn.execute(
                    text(
                        """UPDATE claims SET status = :status, updated_at = :now WHERE id = :claim_id"""
                    ),
                    {"status": new_status, "now": now, "claim_id": claim_id},
                )

            if repair_ready_for_settlement is not None:
                conn.execute(
                    text(
                        "UPDATE claims SET repair_ready_for_settlement = :v, "
                        "updated_at = :now WHERE id = :claim_id"
                    ),
                    {
                        "v": 1 if repair_ready_for_settlement else 0,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )
            if total_loss_settlement_authorized is not None:
                conn.execute(
                    text(
                        "UPDATE claims SET total_loss_settlement_authorized = :v, "
                        "updated_at = :now WHERE id = :claim_id"
                    ),
                    {
                        "v": 1 if total_loss_settlement_authorized else 0,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )

            if new_status == STATUS_CLOSED:
                conn.execute(
                    text(
                        "UPDATE claims SET retention_tier = :rt, updated_at = :now "
                        "WHERE id = :claim_id"
                    ),
                    {
                        "rt": RETENTION_TIER_COLD,
                        "now": now,
                        "claim_id": claim_id,
                    },
                )

            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": new_status,
                    "details": details or "",
                    "actor_id": actor_id,
                    "before_state": json.dumps(before_state),
                    "after_state": json.dumps(after_state),
                },
            )

            self._append_reserve_adequacy_gate_audit(
                conn,
                claim_id,
                new_status,
                row_d,
                payout_amount,
                skip_adequacy_check=skip_adequacy_check,
                role=role,
                actor_id=actor_id,
            )

        final_claim_type = claim_type if claim_type is not None else old_claim_type
        final_payout = payout_amount if payout_amount is not None else old_payout
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=new_status,
                summary=details,
                claim_type=final_claim_type,
                payout_amount=final_payout,
            )
        )

    def save_workflow_result(
        self,
        claim_id: str,
        claim_type: str,
        router_output: str,
        workflow_output: str,
    ) -> None:
        """Save workflow run result to workflow_runs."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
                VALUES (:claim_id, :claim_type, :router_output, :workflow_output)
                """),
                {
                    "claim_id": claim_id,
                    "claim_type": claim_type,
                    "router_output": router_output,
                    "workflow_output": workflow_output,
                },
            )

    def get_workflow_runs(
        self,
        claim_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch workflow run records for a claim, most recent first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT claim_type, router_output, workflow_output, created_at
                FROM workflow_runs
                WHERE claim_id = :claim_id
                ORDER BY created_at DESC
                LIMIT :limit
                """),
                {"claim_id": claim_id, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def save_task_checkpoint(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_key: str,
        output: str,
    ) -> None:
        """Persist a stage checkpoint. Replaces any existing checkpoint for the same key."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO task_checkpoints (claim_id, workflow_run_id, stage_key, output)
                VALUES (:claim_id, :workflow_run_id, :stage_key, :output)
                ON CONFLICT (claim_id, workflow_run_id, stage_key)
                DO UPDATE SET output = EXCLUDED.output
                """),
                {
                    "claim_id": claim_id,
                    "workflow_run_id": workflow_run_id,
                    "stage_key": stage_key,
                    "output": output,
                },
            )

    def get_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
    ) -> dict[str, str]:
        """Load all checkpoints for a workflow run. Returns {stage_key: output_json}."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT stage_key, output FROM task_checkpoints
                WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                """),
                {"claim_id": claim_id, "workflow_run_id": workflow_run_id},
            ).fetchall()
        return {(d := row_to_dict(r))["stage_key"]: d["output"] for r in rows}

    def delete_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_keys: list[str] | None = None,
    ) -> None:
        """Delete checkpoints. If stage_keys given, only those; if None, all for the run.
        Empty list deletes nothing."""
        if stage_keys is not None and not stage_keys:
            return
        with get_connection(self._db_path) as conn:
            if stage_keys is not None:
                params: dict[str, Any] = {
                    "claim_id": claim_id,
                    "workflow_run_id": workflow_run_id,
                }
                for i, sk in enumerate(stage_keys):
                    params[f"sk{i}"] = sk
                placeholders = ", ".join(f":sk{i}" for i in range(len(stage_keys)))
                conn.execute(
                    text(f"""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                    AND stage_key IN ({placeholders})
                    """),
                    params,
                )
            else:
                conn.execute(
                    text("""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = :claim_id AND workflow_run_id = :workflow_run_id
                    """),
                    {"claim_id": claim_id, "workflow_run_id": workflow_run_id},
                )

    def get_latest_checkpointed_run_id(self, claim_id: str) -> str | None:
        """Return the most recent workflow_run_id that has checkpoints for this claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT workflow_run_id FROM task_checkpoints
                WHERE claim_id = :claim_id
                ORDER BY id DESC
                LIMIT 1
                """),
                {"claim_id": claim_id},
            ).fetchone()
        return row_to_dict(row)["workflow_run_id"] if row else None

    def update_claim_attachments(
        self,
        claim_id: str,
        attachments: list[Attachment],
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Update attachments for a claim (e.g. after file upload). Logs an audit entry."""
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in attachments],
            default=str,
        )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT attachments FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            before_attachments = row_d["attachments"] or "[]"
            cursor = conn.execute(
                text(
                    "UPDATE claims SET attachments = :attachments, updated_at = CURRENT_TIMESTAMP WHERE id = :claim_id"
                ),
                {"attachments": attachments_json, "claim_id": claim_id},
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            before_state = before_attachments  # already a serialized JSON array
            after_state = attachments_json  # already a serialized JSON array
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_ATTACHMENTS_UPDATED,
                    "details": f"Attachments updated: {len(attachments)} file(s)",
                    "actor_id": actor_id,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )

    def set_reserve(
        self,
        claim_id: str,
        amount: float,
        *,
        reason: str = "",
        actor_id: str = ACTOR_WORKFLOW,
        role: str = "adjuster",
        skip_authority_check: bool = False,
    ) -> None:
        """Set reserve amount (initial or overwrite). Logs to reserve_history and claim_audit_log."""
        if amount < 0:
            raise DomainValidationError("Reserve amount cannot be negative")
        _check_reserve_authority(
            amount, actor_id, role=role, skip_authority_check=skip_authority_check
        )
        safe_actor = sanitize_actor_id(actor_id)
        safe_reason = sanitize_note(reason) if reason else ""
        audit_reason = _reserve_audit_reason(
            safe_reason, "Reserve set", skip_authority_check=skip_authority_check
        )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT reserve_amount, status FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_amount = row_d["reserve_amount"]
            claim_status = row_d["status"]
            conn.execute(
                text(
                    "UPDATE claims SET reserve_amount = :amount, updated_at = CURRENT_TIMESTAMP WHERE id = :claim_id"
                ),
                {"amount": amount, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                VALUES (:claim_id, :old_amount, :new_amount, :reason, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "old_amount": old_amount,
                    "new_amount": amount,
                    "reason": audit_reason,
                    "actor_id": safe_actor,
                },
            )
            before_state = json.dumps({"reserve_amount": old_amount})
            after_state = json.dumps({"reserve_amount": amount})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_RESERVE_SET,
                    "details": audit_reason,
                    "actor_id": safe_actor,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id, status=claim_status, summary=f"Reserve set to ${amount:,.2f}"
            )
        )

    def adjust_reserve(
        self,
        claim_id: str,
        new_amount: float,
        *,
        reason: str = "",
        actor_id: str = ACTOR_WORKFLOW,
        role: str = "adjuster",
        skip_authority_check: bool = False,
    ) -> None:
        """Adjust reserve amount. Logs to reserve_history and claim_audit_log atomically."""
        if new_amount < 0:
            raise DomainValidationError("Reserve amount cannot be negative")
        _check_reserve_authority(
            new_amount, actor_id, role=role, skip_authority_check=skip_authority_check
        )
        safe_actor = sanitize_actor_id(actor_id)
        safe_reason = sanitize_note(reason) if reason else ""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT reserve_amount, status FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_amount = row_d["reserve_amount"]
            claim_status = row_d["status"]
            audit_event = (
                AUDIT_EVENT_RESERVE_SET if old_amount is None else AUDIT_EVENT_RESERVE_ADJUSTED
            )
            default_reason = "Reserve set" if old_amount is None else "Reserve adjusted"
            audit_reason = _reserve_audit_reason(
                safe_reason, default_reason, skip_authority_check=skip_authority_check
            )
            conn.execute(
                text(
                    "UPDATE claims SET reserve_amount = :new_amount, updated_at = CURRENT_TIMESTAMP WHERE id = :claim_id"
                ),
                {"new_amount": new_amount, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                VALUES (:claim_id, :old_amount, :new_amount, :reason, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "old_amount": old_amount,
                    "new_amount": new_amount,
                    "reason": audit_reason,
                    "actor_id": safe_actor,
                },
            )
            before_state = json.dumps({"reserve_amount": old_amount})
            after_state = json.dumps({"reserve_amount": new_amount})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": audit_event,
                    "details": audit_reason,
                    "actor_id": safe_actor,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=claim_status,
                summary=f"Reserve adjusted to ${new_amount:,.2f}",
            )
        )

    def get_reserve_history(
        self,
        claim_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch reserve history for a claim, most recent first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT id, claim_id, old_amount, new_amount, reason, actor_id, created_at
                FROM reserve_history
                WHERE claim_id = :claim_id
                ORDER BY id DESC
                LIMIT :limit
                """),
                {"claim_id": claim_id, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def check_reserve_adequacy(self, claim_id: str) -> dict[str, Any]:
        """Check reserve adequacy vs estimated_damage and payout_amount.

        Positive ``estimated_damage`` and ``payout_amount`` values contribute to the
        benchmark (their maximum). Non-positive values are ignored.

        Returns:
            adequate: True if reserve >= benchmark (see above)
            reserve, estimated_damage, payout_amount: values from claim
            warnings: human-readable adequacy messages
            warning_codes: stable codes (``RESERVE_*`` from ``db.constants``)
        """
        claim = self.get_claim(claim_id)
        if claim is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        reserve = claim.get("reserve_amount")
        estimated = claim.get("estimated_damage")
        payout = claim.get("payout_amount")
        reserve_val = float(reserve) if reserve is not None else None
        est_val = float(estimated) if estimated is not None else None
        payout_val = float(payout) if payout is not None else None
        adequate, warnings, warning_codes = compute_reserve_adequacy_details(
            reserve_val, est_val, payout_val
        )
        return {
            "adequate": adequate,
            "reserve": reserve_val,
            "estimated_damage": est_val,
            "payout_amount": payout_val,
            "warnings": warnings,
            "warning_codes": warning_codes,
        }

    def get_claim_history(
        self,
        claim_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get audit log entries for a claim with optional pagination.

        Returns:
            (rows, total_count). When limit is None, returns all rows.
        """
        with get_connection(self._db_path) as conn:
            params: dict[str, Any] = {"claim_id": claim_id}
            if limit is not None:
                count_row = conn.execute(
                    text("SELECT COUNT(*) FROM claim_audit_log WHERE claim_id = :claim_id"),
                    {"claim_id": claim_id},
                ).fetchone()
                total = count_row[0] if count_row else 0
                params["limit"] = limit
                params["offset"] = offset
                query = text("""
                    SELECT id, claim_id, action, old_status, new_status, details,
                           actor_id, before_state, after_state, created_at
                    FROM claim_audit_log
                    WHERE claim_id = :claim_id
                    ORDER BY id ASC
                    LIMIT :limit OFFSET :offset
                """)
            else:
                total = 0
                query = text("""
                    SELECT id, claim_id, action, old_status, new_status, details,
                           actor_id, before_state, after_state, created_at
                    FROM claim_audit_log
                    WHERE claim_id = :claim_id
                    ORDER BY id ASC
                """)
            rows = conn.execute(query, params).fetchall()
        result = [row_to_dict(r) for r in rows]
        if limit is None:
            # All rows fetched; total is simply the list length — no extra query needed.
            total = len(result)
        return result, total

    def record_claim_review(
        self,
        claim_id: str,
        report_json: str,
        actor_id: str,
    ) -> None:
        """Record a claim review result in the audit log. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_CLAIM_REVIEW,
                    "details": report_json,
                    "actor_id": sanitize_actor_id(actor_id),
                },
            )

    def add_note(
        self,
        claim_id: str,
        note: str,
        actor_id: str,
    ) -> None:
        """Append a note to a claim. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                INSERT INTO claim_notes (claim_id, note, actor_id)
                VALUES (:claim_id, :note, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "note": sanitize_note(note),
                    "actor_id": sanitize_actor_id(actor_id),
                },
            )

    def get_notes(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all notes for a claim, ordered by created_at ascending. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                text("""
                SELECT id, claim_id, note, actor_id, created_at
                FROM claim_notes
                WHERE claim_id = :claim_id
                ORDER BY created_at ASC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def create_follow_up_message(
        self,
        claim_id: str,
        user_type: str,
        message_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> int:
        """Create a follow-up message record. Returns the message id. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO follow_up_messages (claim_id, user_type, message_content, status, actor_id)
                VALUES (:claim_id, :user_type, :message_content, 'pending', :actor_id)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "user_type": user_type,
                    "message_content": sanitize_note(message_content),
                    "actor_id": actor_id,
                },
            )
            row = result.fetchone()
            msg_id = row[0] if row else 0
        return int(msg_id)

    def mark_follow_up_sent(self, message_id: int) -> None:
        """Mark a follow-up message as sent (status=sent) and log audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT claim_id, user_type, actor_id FROM follow_up_messages WHERE id = :message_id"
                ),
                {"message_id": message_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            row_d = row_to_dict(row)
            claim_id = row_d["claim_id"]
            user_type = row_d["user_type"]
            actor_id = row_d["actor_id"]
            conn.execute(
                text("UPDATE follow_up_messages SET status = 'sent' WHERE id = :message_id"),
                {"message_id": message_id},
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_FOLLOW_UP_SENT,
                    "details": details,
                    "actor_id": actor_id,
                },
            )

    def record_follow_up_response(
        self,
        message_id: int,
        response_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        expected_claim_id: str | None = None,
    ) -> None:
        """Record a user response to a follow-up message. Updates status to responded and logs audit.

        Args:
            message_id: The follow-up message ID.
            response_content: The user's response text.
            actor_id: Who recorded the response.
            expected_claim_id: If provided, raises ValueError when the message belongs to a
                different claim (prevents cross-claim response injection).
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT claim_id, user_type FROM follow_up_messages WHERE id = :message_id"),
                {"message_id": message_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            row_d = row_to_dict(row)
            claim_id = row_d["claim_id"]
            user_type = row_d["user_type"]
            if expected_claim_id is not None and claim_id != expected_claim_id:
                raise ValueError(
                    f"Follow-up message {message_id} does not belong to claim {expected_claim_id}"
                )
            conn.execute(
                text("""
                UPDATE follow_up_messages
                SET status = 'responded', response_content = :response_content, responded_at = CURRENT_TIMESTAMP
                WHERE id = :message_id
                """),
                {"response_content": sanitize_note(response_content), "message_id": message_id},
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_FOLLOW_UP_RESPONSE,
                    "details": details,
                    "actor_id": actor_id,
                },
            )

    def get_pending_follow_ups(
        self,
        claim_id: str,
        *,
        user_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending or sent (not yet responded) follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if user_type:
                rows = conn.execute(
                    text("""
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = :claim_id AND user_type = :user_type AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """),
                    {"claim_id": claim_id, "user_type": user_type},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("""
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = :claim_id AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """),
                    {"claim_id": claim_id},
                ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_follow_up_messages(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                text("""
                SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                FROM follow_up_messages
                WHERE claim_id = :claim_id
                ORDER BY created_at DESC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def insert_audit_entry(
        self,
        claim_id: str,
        action: str,
        *,
        old_status: str | None = None,
        new_status: str | None = None,
        details: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
        before_state: str | None = None,
        after_state: str | None = None,
    ) -> None:
        """Insert an audit log entry without changing claim status."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": action,
                    "old_status": old_status,
                    "new_status": new_status,
                    "details": details or "",
                    "actor_id": actor_id,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )

    def update_claim_siu_case_id(
        self,
        claim_id: str,
        siu_case_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Store SIU case ID on claim and log siu_case_created audit entry.

        Calling this method overwrites any existing siu_case_id on the claim and
        always appends a new siu_case_created audit log entry. Retrying this call
        after a transient failure will therefore produce multiple
        siu_case_created entries for the same claim in claim_audit_log.
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text(
                    "UPDATE claims SET siu_case_id = :siu_case_id, updated_at = :now WHERE id = :claim_id"
                ),
                {"siu_case_id": siu_case_id, "now": now, "claim_id": claim_id},
            )
            if result.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_SIU_CASE_CREATED,
                    "details": f"SIU case created: {siu_case_id}",
                    "actor_id": actor_id,
                },
            )

    def record_fraud_filing(
        self,
        claim_id: str,
        filing_type: str,
        report_id: str,
        *,
        siu_case_id: str | None = None,
        state: str | None = None,
        filed_by: str = "siu_crew",
        indicators_count: int = 0,
        template_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Record a fraud report filing for compliance audit.

        Args:
            claim_id: Claim ID.
            filing_type: One of state_bureau, nicb, niss.
            report_id: External reference ID from the filing.
            siu_case_id: Optional SIU case ID.
            state: State jurisdiction (e.g., California).
            filed_by: Actor who filed (default siu_crew).
            indicators_count: Number of fraud indicators.
            template_version: Optional template version for audit.
            metadata: Optional JSON metadata.

        Returns:
            The inserted row id.

        Raises:
            ValueError: If filing_type is not one of state_bureau, nicb, niss.
        """
        if filing_type not in ("state_bureau", "nicb", "niss"):
            raise ValueError(
                f"filing_type must be one of state_bureau, nicb, niss; got {filing_type!r}"
            )
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata) if metadata else None
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                INSERT INTO fraud_report_filings
                (claim_id, siu_case_id, filing_type, state, report_id, filed_at, filed_by,
                 indicators_count, template_version, metadata)
                VALUES (:claim_id, :siu_case_id, :filing_type, :state, :report_id, :filed_at,
                        :filed_by, :indicators_count, :template_version, :metadata)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "siu_case_id": siu_case_id,
                    "filing_type": filing_type,
                    "state": state,
                    "report_id": report_id,
                    "filed_at": now,
                    "filed_by": filed_by,
                    "indicators_count": indicators_count,
                    "template_version": template_version,
                    "metadata": metadata_json,
                },
            )
            row = result.fetchone()
            return cast(int, row[0]) if row is not None else 0

    def get_fraud_filings_for_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Return all fraud report filings for a claim, newest first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT id, claim_id, siu_case_id, filing_type, state, report_id,
                       filed_at, filed_by, indicators_count, template_version, metadata
                FROM fraud_report_filings
                WHERE claim_id = :claim_id
                ORDER BY filed_at DESC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def update_claim_review_metadata(
        self,
        claim_id: str,
        *,
        priority: str | None = None,
        due_at: str | None = None,
        review_started_at: str | None = None,
    ) -> None:
        """Update review metadata (priority, due_at, review_started_at) on a claim."""
        set_parts: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: dict[str, Any] = {"claim_id": claim_id}
        if priority is not None:
            set_parts.append("priority = :priority")
            params["priority"] = priority
        if due_at is not None:
            set_parts.append("due_at = :due_at")
            params["due_at"] = due_at
        if review_started_at is not None:
            set_parts.append("review_started_at = :review_started_at")
            params["review_started_at"] = review_started_at
        if len(params) <= 1:
            return
        with get_connection(self._db_path) as conn:
            conn.execute(
                text(f"UPDATE claims SET {', '.join(set_parts)} WHERE id = :claim_id"),
                params,
            )

    def update_claim_liability(
        self,
        claim_id: str,
        *,
        liability_percentage: float | None = None,
        liability_basis: str | None = None,
    ) -> None:
        """Update liability determination fields on a claim."""
        set_parts: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: dict[str, Any] = {"claim_id": claim_id}
        if liability_percentage is not None:
            set_parts.append("liability_percentage = :liability_percentage")
            params["liability_percentage"] = liability_percentage
        if liability_basis is not None:
            set_parts.append("liability_basis = :liability_basis")
            params["liability_basis"] = liability_basis
        if len(params) <= 1:
            return
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                text(f"UPDATE claims SET {', '.join(set_parts)} WHERE id = :claim_id"),
                params,
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    def update_claim_total_loss_metadata(
        self,
        claim_id: str,
        total_loss_metadata: dict[str, Any],
    ) -> None:
        """Update total_loss_metadata JSON on a claim (ACV breakdown, DMV, salvage status)."""
        meta_json = json.dumps(total_loss_metadata, default=str)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                text(
                    "UPDATE claims SET total_loss_metadata = :meta_json, updated_at = CURRENT_TIMESTAMP WHERE id = :claim_id"
                ),
                {"meta_json": meta_json, "claim_id": claim_id},
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    def get_claim_total_loss_metadata(self, claim_id: str) -> dict[str, Any] | None:
        """Get total_loss_metadata for a claim, or None if not set."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT total_loss_metadata FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
        if not row:
            return None
        row_d = row_to_dict(row)
        val = row_d.get("total_loss_metadata")
        if val is None:
            return None
        try:
            return cast(dict[str, Any], json.loads(val))
        except json.JSONDecodeError:
            return None

    def create_subrogation_case(
        self,
        claim_id: str,
        case_id: str,
        amount_sought: float,
        *,
        opposing_carrier: str | None = None,
        liability_percentage: float | None = None,
        liability_basis: str | None = None,
    ) -> dict[str, Any]:
        """Create a subrogation case record. Returns the created row as dict."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO subrogation_cases
                    (claim_id, case_id, amount_sought, opposing_carrier,
                     liability_percentage, liability_basis, status)
                VALUES (:claim_id, :case_id, :amount_sought, :opposing_carrier,
                        :liability_percentage, :liability_basis, 'pending')
                """),
                {
                    "claim_id": claim_id,
                    "case_id": case_id,
                    "amount_sought": amount_sought,
                    "opposing_carrier": opposing_carrier,
                    "liability_percentage": liability_percentage,
                    "liability_basis": liability_basis,
                },
            )
            row = conn.execute(
                text("SELECT * FROM subrogation_cases WHERE case_id = :case_id"),
                {"case_id": case_id},
            ).fetchone()
        return row_to_dict(row) if row else {}

    def update_subrogation_case(
        self,
        case_id: str,
        *,
        arbitration_status: str | None = None,
        arbitration_forum: str | None = None,
        dispute_date: str | None = None,
        opposing_carrier: str | None = None,
        status: str | None = None,
        recovery_amount: float | None = None,
    ) -> None:
        """Update subrogation case arbitration/metadata/recovery fields."""
        set_parts: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: dict[str, Any] = {"case_id": case_id}
        if arbitration_status is not None:
            set_parts.append("arbitration_status = :arbitration_status")
            params["arbitration_status"] = arbitration_status
        if arbitration_forum is not None:
            set_parts.append("arbitration_forum = :arbitration_forum")
            params["arbitration_forum"] = arbitration_forum
        if dispute_date is not None:
            set_parts.append("dispute_date = :dispute_date")
            params["dispute_date"] = dispute_date
        if opposing_carrier is not None:
            set_parts.append("opposing_carrier = :opposing_carrier")
            params["opposing_carrier"] = opposing_carrier
        if status is not None:
            set_parts.append("status = :status")
            params["status"] = status
        if recovery_amount is not None:
            set_parts.append("recovery_amount = :recovery_amount")
            params["recovery_amount"] = recovery_amount
        if len(params) <= 1:
            return
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                text(
                    f"UPDATE subrogation_cases SET {', '.join(set_parts)} WHERE case_id = :case_id"
                ),
                params,
            )
            if cursor.rowcount == 0:
                raise DomainValidationError(f"Subrogation case not found for case_id={case_id}")

    def get_subrogation_cases_by_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Fetch all subrogation cases for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT * FROM subrogation_cases
                WHERE claim_id = :claim_id
                ORDER BY created_at DESC
                """),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def assign_claim(
        self,
        claim_id: str,
        assignee_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Assign claim to an adjuster. Sets review_started_at if not already set.
        Only claims with status needs_review can be assigned."""
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT assignee, status FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            if row_d["status"] != STATUS_NEEDS_REVIEW:
                raise ValueError(
                    f"Claim {claim_id} is not in needs_review (status={row_d['status']}); "
                    "only claims in the review queue can be assigned"
                )
            old_assignee = row_d["assignee"]
            conn.execute(
                text("""
                UPDATE claims SET assignee = :assignee,
                    review_started_at = COALESCE(review_started_at, :now),
                    updated_at = :now
                WHERE id = :claim_id
                """),
                {"assignee": assignee_id, "now": now, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_ASSIGN,
                    "details": f"Assigned to {assignee_id}",
                    "actor_id": actor_id,
                    "before_state": json.dumps({"assignee": old_assignee}),
                    "after_state": json.dumps({"assignee": assignee_id}),
                },
            )

    def _ensure_claim_needs_review(self, conn: Any, claim_id: str) -> Any:
        """Fetch claim row and ensure status is needs_review. Raises if not found or wrong status."""
        row = conn.execute(
            text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
            {"claim_id": claim_id},
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        row_d = row_to_dict(row)
        if row_d["status"] != STATUS_NEEDS_REVIEW:
            raise ValueError(
                f"Claim {claim_id} is not in needs_review (status={row_d['status']}); "
                "adjuster actions only apply to claims in the review queue"
            )
        return row_d

    def _ensure_claim_processing(self, conn: Any, claim_id: str) -> Any:
        """Fetch claim row and ensure status is processing. For FNOL denial."""
        row = conn.execute(
            text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
            {"claim_id": claim_id},
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        row_d = row_to_dict(row)
        if row_d["status"] != STATUS_PROCESSING:
            raise ValueError(
                f"Claim {claim_id} is not in processing (status={row_d['status']}); "
                "FNOL denial only applies to claims in processing"
            )
        return row_d

    def approve_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Insert approval audit. Caller must invoke run_claim_workflow."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_APPROVAL,
                    "old_status": row["status"],
                    "new_status": None,
                    "details": "Approved for continued processing",
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": None,
                },
            )

    def reject_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        reason: str | None = None,
    ) -> None:
        """Reject claim: set status to denied, insert audit, emit event."""
        safe_reason = sanitize_denial_reason(reason) or "Rejected by adjuster"
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            validate_transition(
                claim_id,
                row["status"],
                STATUS_DENIED,
                claim=row_to_dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": STATUS_DENIED,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("UPDATE claims SET status = :status, updated_at = :now WHERE id = :claim_id"),
                {"status": STATUS_DENIED, "now": now, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": STATUS_DENIED,
                    "details": safe_reason,
                    "actor_id": actor_id,
                    "before_state": json.dumps(before_state),
                    "after_state": json.dumps(after_state),
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_REJECTION,
                    "old_status": old_status,
                    "new_status": STATUS_DENIED,
                    "details": safe_reason,
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": None,
                },
            )
        emit_claim_event(ClaimEvent(claim_id=claim_id, status=STATUS_DENIED, summary=safe_reason))

    def deny_claim_at_claimant(
        self,
        claim_id: str,
        reason: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        coverage_verification_details: dict | None = None,
    ) -> None:
        """Deny claim at FNOL (coverage verification). Requires status processing."""
        safe_reason = sanitize_denial_reason(reason) or "Coverage verification failed"
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_processing(conn, claim_id)
            validate_transition(
                claim_id,
                row["status"],
                STATUS_DENIED,
                claim=row_to_dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": STATUS_DENIED,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("UPDATE claims SET status = :status, updated_at = :now WHERE id = :claim_id"),
                {"status": STATUS_DENIED, "now": now, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": STATUS_DENIED,
                    "details": safe_reason,
                    "actor_id": actor_id,
                    "before_state": json.dumps(before_state),
                    "after_state": json.dumps(after_state),
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_REJECTION,
                    "old_status": old_status,
                    "new_status": STATUS_DENIED,
                    "details": safe_reason,
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": None,
                },
            )
            if coverage_verification_details:
                merged = {"outcome": "denied", **coverage_verification_details}
                conn.execute(
                    text("""
                    INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                    VALUES (:claim_id, :action, :details, :actor_id, :after_state)
                    """),
                    {
                        "claim_id": claim_id,
                        "action": AUDIT_EVENT_COVERAGE_VERIFICATION,
                        "details": truncate_audit_json(coverage_verification_details),
                        "actor_id": actor_id,
                        "after_state": truncate_audit_json(merged),
                    },
                )
        emit_claim_event(ClaimEvent(claim_id=claim_id, status=STATUS_DENIED, summary=safe_reason))

    def record_acknowledgment(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> bool:
        """Record UCSPA claim acknowledgment (receipt acknowledged within deadline).

        Only sets ``acknowledged_at`` on the first call; subsequent calls are
        no-ops for the timestamp (but still raise :exc:`ClaimNotFoundError` if
        the claim does not exist).

        Returns:
            ``True`` if ``acknowledged_at`` was newly set, ``False`` if it was
            already recorded (idempotent no-op for the timestamp).
        """
        safe_actor = sanitize_actor_id(actor_id)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                UPDATE claims
                SET acknowledged_at = COALESCE(acknowledged_at, :now),
                    updated_at = :now
                WHERE id = :claim_id
                """),
                {"now": now, "claim_id": claim_id},
            )
            if result.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            # Determine whether acknowledged_at was newly set by reading it back.
            row = conn.execute(
                text("SELECT acknowledged_at FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            newly_set = row is not None and row_to_dict(row).get("acknowledged_at") == now
            if newly_set:
                conn.execute(
                    text("""
                    INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                    VALUES (:claim_id, :action, :details, :actor_id)
                    """),
                    {
                        "claim_id": claim_id,
                        "action": AUDIT_EVENT_ACKNOWLEDGED,
                        "details": "Claim receipt acknowledged",
                        "actor_id": safe_actor,
                    },
                )
        return newly_set

    def record_denial_letter(
        self,
        claim_id: str,
        denial_reason: str,
        denial_letter_body: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Record UCSPA-compliant denial letter (written, specific, with appeal rights)."""
        safe_reason = sanitize_denial_reason(denial_reason) or "Coverage denied"
        safe_actor = sanitize_actor_id(actor_id)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                UPDATE claims SET denial_reason = :reason, denial_letter_sent_at = :now,
                    denial_letter_body = :body, updated_at = :now WHERE id = :claim_id
                """),
                {
                    "reason": safe_reason,
                    "now": now,
                    "body": denial_letter_body[:65535],
                    "claim_id": claim_id,
                },
            )
            if result.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_DENIAL_LETTER,
                    "details": f"Denial letter sent: {safe_reason[:200]}",
                    "actor_id": safe_actor,
                    "after_state": json.dumps(
                        {"denial_reason": safe_reason, "denial_letter_sent_at": now}
                    ),
                },
            )

    def insert_coverage_verification_audit(
        self,
        claim_id: str,
        outcome: str,
        details: dict,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Insert coverage verification result into audit trail."""
        merged = {"outcome": outcome, **details}
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_COVERAGE_VERIFICATION,
                    "details": truncate_audit_json(details),
                    "actor_id": actor_id,
                    "after_state": truncate_audit_json(merged),
                },
            )

    def request_info_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        note: str | None = None,
    ) -> None:
        """Request more information: set status to pending_info, insert audit, emit event."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            validate_transition(
                claim_id,
                row["status"],
                STATUS_PENDING_INFO,
                claim=row_to_dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": STATUS_PENDING_INFO,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("UPDATE claims SET status = :status, updated_at = :now WHERE id = :claim_id"),
                {"status": STATUS_PENDING_INFO, "now": now, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": STATUS_PENDING_INFO,
                    "details": note or "Requested more information",
                    "actor_id": actor_id,
                    "before_state": json.dumps(before_state),
                    "after_state": json.dumps(after_state),
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_REQUEST_INFO,
                    "old_status": old_status,
                    "new_status": STATUS_PENDING_INFO,
                    "details": note or "",
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": None,
                },
            )
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_PENDING_INFO,
                summary=note or "Requested more information",
            )
        )

    def escalate_claim_to_siu(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Escalate to SIU: set status to under_investigation, insert audit, emit event."""
        with get_connection(self._db_path) as conn:
            row = self._ensure_claim_needs_review(conn, claim_id)
            validate_transition(
                claim_id,
                row["status"],
                STATUS_UNDER_INVESTIGATION,
                claim=row_to_dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": STATUS_UNDER_INVESTIGATION,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("UPDATE claims SET status = :status, updated_at = :now WHERE id = :claim_id"),
                {"status": STATUS_UNDER_INVESTIGATION, "now": now, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": STATUS_UNDER_INVESTIGATION,
                    "details": "Escalated to SIU",
                    "actor_id": actor_id,
                    "before_state": json.dumps(before_state),
                    "after_state": json.dumps(after_state),
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_ESCALATE_TO_SIU,
                    "old_status": old_status,
                    "new_status": STATUS_UNDER_INVESTIGATION,
                    "details": "Referred to Special Investigations Unit",
                    "actor_id": actor_id,
                    "before_state": None,
                    "after_state": None,
                },
            )
        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id, status=STATUS_UNDER_INVESTIGATION, summary="Escalated to SIU"
            )
        )

    def list_claims_needing_review(
        self,
        *,
        assignee: str | None = None,
        priority: str | None = None,
        older_than_hours: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List claims with status needs_review. Returns (claims, total_count)."""
        conditions = ["status = :status"]
        params: dict[str, Any] = {"status": STATUS_NEEDS_REVIEW, "limit": limit, "offset": offset}
        if assignee is not None:
            conditions.append("assignee = :assignee")
            params["assignee"] = assignee
        if priority is not None:
            conditions.append("priority = :priority")
            params["priority"] = priority
        if older_than_hours is not None:
            if older_than_hours < 0:
                raise ValueError("older_than_hours must be non-negative")
            # Use SQLite-compatible format (YYYY-MM-DD HH:MM:SS) for lexicographic comparison
            cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
            conditions.append("review_started_at IS NOT NULL AND review_started_at <= :cutoff")
            params["cutoff"] = cutoff
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claims WHERE {where}"),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""
                SELECT * FROM claims WHERE {where} ORDER BY
                CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                COALESCE(due_at, '9999-12-31') ASC, created_at DESC LIMIT :limit OFFSET :offset
                """),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def search_claims(
        self,
        vin: str | None = None,
        incident_date: str | None = None,
        policy_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claims by VIN, policy_number and/or incident_date. All optional; if all None, returns []."""
        vin = None if vin is None else str(vin).strip()
        incident_date = None if incident_date is None else str(incident_date).strip()
        policy_number = None if policy_number is None else str(policy_number).strip()
        if not vin and not incident_date and not policy_number:
            return []
        with get_connection(self._db_path) as conn:
            conditions = []
            params: dict[str, Any] = {}
            if vin:
                conditions.append("vin = :vin")
                params["vin"] = vin
            if incident_date:
                conditions.append("incident_date = :incident_date")
                params["incident_date"] = incident_date
            if policy_number:
                conditions.append("policy_number = :policy_number")
                params["policy_number"] = policy_number
            where_clause = " AND ".join(conditions)
            rows = conn.execute(
                text(f"SELECT * FROM claims WHERE {where_clause}"),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_claims_by_party_address(
        self,
        address: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to parties at a matching address."""
        addr = str(address).strip()
        if not addr:
            return []
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE lower(trim(cp.address)) = lower(trim(:addr))
                ORDER BY c.created_at DESC
                LIMIT :limit
                """),
                {"addr": addr, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_claims_by_provider_name(
        self,
        provider_name: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to provider parties with matching name."""
        name = str(provider_name).strip()
        if not name:
            return []
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE cp.party_type = 'provider'
                  AND lower(trim(cp.name)) = lower(trim(:name))
                ORDER BY c.created_at DESC
                LIMIT :limit
                """),
                {"name": name, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def build_relationship_snapshot(
        self,
        *,
        claim_id: str,
        max_nodes: int = 100,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        """Build an in-memory 1-hop relationship graph snapshot from existing claims/parties.

        Finds claims related to the root by shared VIN, shared party address, or shared
        provider name. Uses a single connection for all lookups to avoid N+1 churn.

        This is a migration-ready compatibility layer. It derives graph signals from
        existing tables without requiring dedicated graph persistence.

        Args:
            claim_id: Root claim ID.
            max_nodes: Maximum related claim nodes to include.
            max_depth: Graph traversal depth (reserved for future multi-hop expansion;
                currently only 1-hop is implemented).
        """
        logger = logging.getLogger(__name__)
        if max_depth > 1:
            logger.debug(
                "build_relationship_snapshot max_depth=%s > 1; only 1-hop implemented",
                max_depth,
            )

        root_claim = self.get_claim(claim_id)
        if root_claim is None:
            return {
                "claim_id": claim_id,
                "max_nodes": max_nodes,
                "node_count": 0,
                "edge_count": 0,
                "high_risk_link_count": 0,
                "dense_cluster_detected": False,
                "signals": [],
                "nodes": [],
                "edges": [],
            }

        root_vin = str(root_claim.get("vin") or "").strip()
        parties = self.get_claim_parties(claim_id)
        addresses = [
            str(p.get("address")).strip().lower()
            for p in parties
            if isinstance(p.get("address"), str) and str(p.get("address")).strip()
        ]
        provider_names = [
            str(p.get("name")).strip().lower()
            for p in parties
            if str(p.get("party_type") or "").strip() == "provider"
            and isinstance(p.get("name"), str)
            and str(p.get("name")).strip()
        ]

        related_ids: set[str] = set()
        with get_connection(self._db_path) as conn:
            if root_vin:
                for row in self.search_claims(vin=root_vin):
                    rid = str(row.get("id") or "").strip()
                    if rid and rid != claim_id:
                        related_ids.add(rid)
            if addresses:
                params: dict[str, Any] = {"limit": max_nodes * len(addresses)}
                for i, addr in enumerate(addresses):
                    params[f"addr{i}"] = addr
                placeholders = ", ".join(f":addr{i}" for i in range(len(addresses)))
                rows = conn.execute(
                    text(f"""
                    SELECT DISTINCT c.id
                    FROM claim_parties cp
                    JOIN claims c ON c.id = cp.claim_id
                    WHERE lower(trim(cp.address)) IN ({placeholders})
                    ORDER BY c.created_at DESC
                    LIMIT :limit
                    """),
                    params,
                ).fetchall()
                for r in rows:
                    rid = str(r[0] if r else "").strip()
                    if rid and rid != claim_id:
                        related_ids.add(rid)
            if provider_names:
                params = {"limit": max_nodes * len(provider_names)}
                for i, pn in enumerate(provider_names):
                    params[f"pn{i}"] = pn
                placeholders = ", ".join(f":pn{i}" for i in range(len(provider_names)))
                rows = conn.execute(
                    text(f"""
                    SELECT DISTINCT c.id
                    FROM claim_parties cp
                    JOIN claims c ON c.id = cp.claim_id
                    WHERE cp.party_type = 'provider'
                      AND lower(trim(cp.name)) IN ({placeholders})
                    ORDER BY c.created_at DESC
                    LIMIT :limit
                    """),
                    params,
                ).fetchall()
                for r in rows:
                    rid = str(r[0] if r else "").strip()
                    if rid and rid != claim_id:
                        related_ids.add(rid)

        if len(related_ids) > max_nodes:
            related_ids = set(sorted(related_ids)[:max_nodes])

        nodes = [{"id": claim_id, "type": "claim"}]
        edges: list[dict[str, Any]] = []
        high_risk_link_count = 0

        if related_ids:
            sorted_related = sorted(related_ids)
            params = {f"id{i}": rid for i, rid in enumerate(sorted_related)}
            placeholders = ", ".join(f":id{i}" for i in range(len(sorted_related)))
            with get_connection(self._db_path) as conn:
                claim_rows = conn.execute(
                    text(f"SELECT * FROM claims WHERE id IN ({placeholders})"),
                    params,
                ).fetchall()
                party_rows = conn.execute(
                    text(f"SELECT * FROM claim_parties WHERE claim_id IN ({placeholders})"),
                    params,
                ).fetchall()
            related_claims_by_id = {row_to_dict(r)["id"]: row_to_dict(r) for r in claim_rows}
            parties_by_claim_id: dict[str, list[dict[str, Any]]] = {}
            for row in party_rows:
                p = row_to_dict(row)
                parties_by_claim_id.setdefault(p["claim_id"], []).append(p)

            for related_id in sorted_related:
                related = related_claims_by_id.get(related_id)
                if related is None:
                    continue
                nodes.append({"id": related_id, "type": "claim"})
                relation_types: list[str] = []
                if root_vin and str(related.get("vin") or "").strip() == root_vin:
                    relation_types.append(RELATION_SHARED_VIN)
                related_parties = parties_by_claim_id.get(related_id, [])
                related_addresses = {
                    str(p.get("address")).strip().lower()
                    for p in related_parties
                    if isinstance(p.get("address"), str) and str(p.get("address")).strip()
                }
                related_providers = {
                    str(p.get("name")).strip().lower()
                    for p in related_parties
                    if str(p.get("party_type") or "").strip() == "provider"
                    and isinstance(p.get("name"), str)
                    and str(p.get("name")).strip()
                }
                if set(addresses) & related_addresses:
                    relation_types.append(RELATION_SHARED_ADDRESS)
                if set(provider_names) & related_providers:
                    relation_types.append(RELATION_SHARED_PROVIDER)
                if not relation_types:
                    continue
                edges.append(
                    {"from": claim_id, "to": related_id, "relations": sorted(set(relation_types))}
                )
                if (
                    RELATION_SHARED_PROVIDER in relation_types
                    or RELATION_SHARED_ADDRESS in relation_types
                ):
                    high_risk_link_count += 1

        edge_count = len(edges)
        node_count = len(nodes)
        dense_cluster_detected = edge_count >= 3 or high_risk_link_count >= 2
        signals: list[str] = []
        if dense_cluster_detected:
            signals.append("dense_cluster_detected")
        if high_risk_link_count >= 2:
            signals.append("high_risk_links")
        return {
            "claim_id": claim_id,
            "max_nodes": max_nodes,
            "node_count": node_count,
            "edge_count": edge_count,
            "high_risk_link_count": high_risk_link_count,
            "dense_cluster_detected": dense_cluster_detected,
            "signals": signals,
            "nodes": nodes,
            "edges": edges,
        }

    def get_relationship_index_snapshot(self, *, claim_id: str) -> dict[str, Any]:
        """Placeholder for future durable graph index implementation.

        Returns a migration-ready shape while current implementation derives data
        from normalized claims/parties tables.
        """
        return {
            "claim_id": claim_id,
            "source": "derived_from_claims_and_parties",
            "status": "not_materialized",
        }

    def list_claims_for_retention(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List closed claims older than retention period that are not yet archived.

        Uses created_at for cutoff. Only returns claims with status closed
        (archiving requires closed->archived transition). Excludes claims
        with status archived or a non-null archived_at.

        When exclude_litigation_hold is True (default), claims with
        litigation_hold=1 are excluded (retention suspended for litigation).

        When retention_by_state is provided, uses loss_state to pick per-claim
        retention; falls back to retention_period_years when state is missing
        or not in the map.
        """
        if retention_period_years < 0:
            raise ValueError("retention_period_years must be non-negative")
        state_map = retention_by_state or {}
        now = datetime.now(timezone.utc)
        cutoff_dt = now - timedelta(days=retention_period_years * 365)
        cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

        if state_map:
            min_state_years = min(state_map.values())
            min_retention_years = min(retention_period_years, min_state_years)
            coarse_cutoff_dt = now - timedelta(days=min_retention_years * 365)
            coarse_cutoff = coarse_cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            coarse_cutoff = cutoff

        with get_connection(self._db_path) as conn:
            if not state_map:
                rows = conn.execute(
                    text("""
                    SELECT * FROM claims
                    WHERE archived_at IS NULL
                      AND status = :status
                      AND created_at <= :cutoff
                      AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                    ORDER BY created_at ASC
                    """),
                    {
                        "status": STATUS_CLOSED,
                        "cutoff": cutoff,
                        "include_hold": 1 if not exclude_litigation_hold else 0,
                    },
                ).fetchall()
                return [row_to_dict(r) for r in rows]

            rows = conn.execute(
                text("""
                SELECT * FROM claims
                WHERE archived_at IS NULL
                  AND status = :status
                  AND created_at <= :cutoff
                  AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                ORDER BY created_at ASC
                """),
                {
                    "status": STATUS_CLOSED,
                    "cutoff": coarse_cutoff,
                    "include_hold": 1 if not exclude_litigation_hold else 0,
                },
            ).fetchall()

        result = []
        for r in rows:
            row_d = row_to_dict(r)
            if _is_claim_past_retention(row_d, now, retention_period_years, state_map):
                result.append(row_d)
        return result

    def set_litigation_hold(
        self,
        claim_id: str,
        litigation_hold: bool,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Set or clear litigation hold on a claim. Logs to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id, litigation_hold FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            current = 1 if row_d.get("litigation_hold") else 0
            new_val = 1 if litigation_hold else 0
            if current == new_val:
                return
            conn.execute(
                text("""
                UPDATE claims SET litigation_hold = :val, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {"claim_id": claim_id, "val": new_val},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_LITIGATION_HOLD,
                    "details": "Litigation hold set"
                    if litigation_hold
                    else "Litigation hold cleared",
                    "actor_id": actor_id,
                },
            )

    def retention_report(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        purge_after_archive_years: int = 2,
    ) -> dict[str, Any]:
        """Produce retention audit report: counts by tier, litigation hold, pending archive/purge."""
        state_map = retention_by_state or {}
        now = datetime.now(timezone.utc)

        with get_connection(self._db_path) as conn:
            status_rows = conn.execute(
                text("""
                SELECT status, COUNT(*) as cnt FROM claims GROUP BY status
                """)
            ).fetchall()
            status_counts = {r[0]: r[1] for r in status_rows}

            tier_rows = conn.execute(
                text("""
                SELECT retention_tier, COUNT(*) as cnt FROM claims GROUP BY retention_tier
                """)
            ).fetchall()
            claims_by_retention_tier = {r[0]: r[1] for r in tier_rows}

            litigation_hold_count = (
                conn.execute(
                    text("SELECT COUNT(*) FROM claims WHERE COALESCE(litigation_hold, 0) = 1")
                ).scalar()
                or 0
            )

            audit_count = conn.execute(text("SELECT COUNT(*) FROM claim_audit_log")).scalar() or 0

            closed_rows = conn.execute(
                text("""
                SELECT id, created_at, loss_state, litigation_hold
                FROM claims WHERE status = :status AND archived_at IS NULL
                """),
                {"status": STATUS_CLOSED},
            ).fetchall()

            archived_rows = conn.execute(
                text("""
                SELECT id, archived_at, litigation_hold FROM claims
                WHERE status = :st AND archived_at IS NOT NULL
                """),
                {"st": STATUS_ARCHIVED},
            ).fetchall()

        pending_archive = 0
        for r in closed_rows:
            row_d = row_to_dict(r)
            if row_d.get("litigation_hold"):
                continue
            if _is_claim_past_retention(row_d, now, retention_period_years, state_map):
                pending_archive += 1

        closed_with_hold = sum(1 for r in closed_rows if row_to_dict(r).get("litigation_hold"))

        pending_purge = 0
        for r in archived_rows:
            row_d = row_to_dict(r)
            if row_d.get("litigation_hold"):
                continue
            if _is_archived_past_purge_period(row_d, now, purge_after_archive_years):
                pending_purge += 1

        return {
            "retention_period_years": retention_period_years,
            "purge_after_archive_years": purge_after_archive_years,
            "retention_by_state": state_map,
            "claims_by_status": status_counts,
            "claims_by_retention_tier": claims_by_retention_tier,
            "active_count": sum(
                status_counts.get(s, 0)
                for s in (
                    STATUS_PENDING,
                    STATUS_PROCESSING,
                    STATUS_NEEDS_REVIEW,
                    STATUS_PENDING_INFO,
                )
            ),
            "closed_count": status_counts.get(STATUS_CLOSED, 0),
            "archived_count": status_counts.get(STATUS_ARCHIVED, 0),
            "purged_count": status_counts.get(STATUS_PURGED, 0),
            "litigation_hold_count": litigation_hold_count,
            "closed_with_litigation_hold": closed_with_hold,
            "pending_archive_count": pending_archive,
            "pending_purge_count": pending_purge,
            "audit_log_rows": audit_count,
        }

    def archive_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Archive a claim (soft delete for retention). Sets archived_at and status=archived."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            if old_status == STATUS_ARCHIVED:
                return
            if old_status == STATUS_PURGED:
                return
            validate_transition(
                claim_id,
                old_status,
                STATUS_ARCHIVED,
                claim=row_d,
                actor_id=actor_id,
            )
            conn.execute(
                text("""
                UPDATE claims SET status = :status, archived_at = CURRENT_TIMESTAMP,
                retention_tier = :rtier, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {
                    "status": STATUS_ARCHIVED,
                    "rtier": RETENTION_TIER_ARCHIVED,
                    "claim_id": claim_id,
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_RETENTION,
                    "old_status": old_status,
                    "new_status": STATUS_ARCHIVED,
                    "details": "Archived for retention (claim older than retention period)",
                    "actor_id": actor_id,
                },
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_ARCHIVED,
                summary="Archived for retention",
                claim_type=row_d["claim_type"],
                payout_amount=row_d["payout_amount"],
            )
        )

    def list_claims_for_purge(
        self,
        purge_after_archive_years: int,
        *,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List archived claims past purge horizon (archived_at + N calendar years)."""
        if purge_after_archive_years < 0:
            raise ValueError("purge_after_archive_years must be non-negative")
        now = datetime.now(timezone.utc)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT * FROM claims
                WHERE status = :st
                  AND archived_at IS NOT NULL
                  AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                ORDER BY archived_at ASC
                """),
                {
                    "st": STATUS_ARCHIVED,
                    "include_hold": 1 if not exclude_litigation_hold else 0,
                },
            ).fetchall()
        result = []
        for r in rows:
            row_d = row_to_dict(r)
            if _is_archived_past_purge_period(row_d, now, purge_after_archive_years):
                result.append(row_d)
        return result

    def purge_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Purge for retention: anonymize PII, status purged, retention_tier purged."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            if old_status == STATUS_PURGED:
                return
            validate_transition(
                claim_id,
                old_status,
                STATUS_PURGED,
                claim=row_d,
                actor_id=actor_id,
            )
            anonymize_claim_pii(
                conn,
                claim_id,
                now_iso=now_iso,
                notes_redaction_text="[REDACTED - retention purge]",
            )
            conn.execute(
                text("""
                UPDATE claims SET status = :status, retention_tier = :rtier,
                purged_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {
                    "status": STATUS_PURGED,
                    "rtier": RETENTION_TIER_PURGED,
                    "claim_id": claim_id,
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_RETENTION_PURGED,
                    "old_status": old_status,
                    "new_status": STATUS_PURGED,
                    "details": "Purged for retention (PII anonymized; audit trail retained)",
                    "actor_id": actor_id,
                },
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_PURGED,
                summary="Purged for retention",
                claim_type=row_d["claim_type"],
                payout_amount=row_d["payout_amount"],
            )
        )

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def create_task(
        self,
        claim_id: str,
        title: str,
        task_type: str,
        *,
        description: str = "",
        priority: str = "medium",
        assigned_to: str | None = None,
        created_by: str = ACTOR_WORKFLOW,
        due_date: str | None = None,
        document_request_id: int | None = None,
        document_type: str | None = None,
        requested_from: str | None = None,
        recurrence_rule: str | None = None,
        recurrence_interval: int | None = None,
        parent_task_id: int | None = None,
        auto_created_from: str | None = None,
    ) -> int:
        """Create a task for a claim. Returns the task id. Raises ClaimNotFoundError if claim does not exist.

        When task_type is request_documents or obtain_police_report and document_type is provided,
        creates a document_request and links it to the task.
        """
        title = sanitize_task_title(title)
        description = sanitize_task_description(description)
        created_by = sanitize_actor_id(created_by)
        if not title:
            raise ValueError("Task title must not be empty after sanitization")
        # Normalize and validate recurrence fields
        if recurrence_rule is None and recurrence_interval is not None:
            recurrence_interval = None
        if recurrence_rule is not None:
            from claim_agent.diary.recurrence import (
                VALID_RECURRENCE_RULES,
                RECURRENCE_INTERVAL_DAYS,
            )

            if recurrence_rule not in VALID_RECURRENCE_RULES:
                raise ValueError(
                    f"Invalid recurrence_rule '{recurrence_rule}'. "
                    f"Must be one of: {', '.join(sorted(VALID_RECURRENCE_RULES))}"
                )
            if recurrence_rule == RECURRENCE_INTERVAL_DAYS:
                if recurrence_interval is None:
                    raise ValueError(
                        "recurrence_interval is required when recurrence_rule is 'interval_days'"
                    )
                if recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
            else:
                # daily/weekly: default interval to 1
                if recurrence_interval is None:
                    recurrence_interval = 1
                elif recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
        doc_req_id = document_request_id
        if (
            doc_req_id is None
            and document_type
            and task_type in ("request_documents", "obtain_police_report")
        ):
            from claim_agent.db.document_repository import DocumentRepository

            doc_repo = DocumentRepository(db_path=self._db_path)
            doc_req_id = doc_repo.create_document_request(
                claim_id, document_type, requested_from=requested_from
            )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            result = conn.execute(
                text("""
                INSERT INTO claim_tasks
                    (claim_id, title, task_type, description, status, priority, assigned_to, created_by, due_date, document_request_id, recurrence_rule, recurrence_interval, parent_task_id, auto_created_from)
                VALUES (:claim_id, :title, :task_type, :description, 'pending', :priority, :assigned_to, :created_by, :due_date, :document_request_id, :recurrence_rule, :recurrence_interval, :parent_task_id, :auto_created_from)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "title": title,
                    "task_type": task_type,
                    "description": description,
                    "priority": priority,
                    "assigned_to": assigned_to,
                    "created_by": created_by,
                    "due_date": due_date,
                    "document_request_id": doc_req_id,
                    "recurrence_rule": recurrence_rule,
                    "recurrence_interval": recurrence_interval,
                    "parent_task_id": parent_task_id,
                    "auto_created_from": auto_created_from,
                },
            )
            row = result.fetchone()
            task_id = row[0] if row else 0
            details = json.dumps(
                {
                    "task_id": task_id,
                    "title": title,
                    "task_type": task_type,
                    "priority": priority,
                    "assigned_to": assigned_to,
                }
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_TASK_CREATED,
                    "details": details,
                    "actor_id": created_by,
                },
            )
        return int(task_id)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Fetch a single task by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_tasks_for_claim(
        self,
        claim_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks for a claim with optional status filter. Returns (tasks, total)."""
        conditions = ["claim_id = :claim_id"]
        params: dict[str, Any] = {"claim_id": claim_id, "limit": limit, "offset": offset}
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claim_tasks WHERE {where}"),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = conn.execute(
                text(f"""SELECT * FROM claim_tasks WHERE {where}
                    ORDER BY
                        CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        created_at DESC
                    LIMIT :limit OFFSET :offset"""),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def list_overdue_tasks(
        self,
        *,
        max_escalation_level: int | None = None,
        min_escalation_level: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List overdue tasks (due_date < today, status not completed/cancelled).

        Args:
            max_escalation_level: If set, only include tasks with escalation_level <= this.
            min_escalation_level: If set, only include tasks with escalation_level >= this.
            limit: Max tasks to return.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        conditions = [
            "due_date IS NOT NULL",
            "substr(due_date, 1, 10) < :today",
            "status NOT IN ('completed', 'cancelled')",
        ]
        params: dict[str, Any] = {"today": today, "limit": limit}
        if max_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) <= :max_escalation_level")
            params["max_escalation_level"] = max_escalation_level
        if min_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) >= :min_escalation_level")
            params["min_escalation_level"] = min_escalation_level
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(f"""
                SELECT * FROM claim_tasks WHERE {where}
                ORDER BY due_date ASC
                LIMIT :limit
                """),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def mark_task_overdue_notified(self, task_id: int) -> None:
        """Mark task as overdue notification sent (escalation_level=1)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                UPDATE claim_tasks SET
                    escalation_level = 1,
                    escalation_notified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :task_id
                """),
                {"task_id": task_id},
            )

    def mark_task_supervisor_escalated(self, task_id: int) -> None:
        """Mark task as escalated to supervisor (escalation_level=2)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                text("""
                UPDATE claim_tasks SET
                    escalation_level = 2,
                    escalation_escalated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :task_id
                """),
                {"task_id": task_id},
            )

    def update_task(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        due_date: str | None = None,
        resolution_notes: str | None = None,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> dict[str, Any]:
        """Update a task. Returns the updated task dict. Raises ValueError if task not found."""
        if title is not None:
            title = sanitize_task_title(title)
            if not title:
                raise ValueError("Task title must not be empty after sanitization")
        if description is not None:
            description = sanitize_task_description(description)
        if resolution_notes is not None:
            resolution_notes = sanitize_resolution_notes(resolution_notes)
        actor_id = sanitize_actor_id(actor_id)
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"Task not found: {task_id}")

            row_d = row_to_dict(row)
            updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: dict[str, Any] = {"task_id": task_id}
            changes: dict[str, Any] = {}

            for field, value in [
                ("title", title),
                ("description", description),
                ("status", status),
                ("priority", priority),
                ("assigned_to", assigned_to),
                ("due_date", due_date),
                ("resolution_notes", resolution_notes),
            ]:
                if value is not None:
                    updates.append(f"{field} = :{field}")
                    params[field] = value
                    changes[field] = value

            if not changes:
                return row_d

            conn.execute(
                text(f"UPDATE claim_tasks SET {', '.join(updates)} WHERE id = :task_id"),
                params,
            )
            details = json.dumps({"task_id": task_id, **changes})
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": row_d["claim_id"],
                    "action": AUDIT_EVENT_TASK_UPDATED,
                    "details": details,
                    "actor_id": actor_id,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM claim_tasks WHERE id = :task_id"),
                {"task_id": task_id},
            ).fetchone()
        return row_to_dict(updated)

    def list_all_tasks(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        assigned_to: str | None = None,
        due_date_from: str | None = None,
        due_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks across all claims with optional filters. Returns (tasks, total)."""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            conditions.append("ct.status = :status")
            params["status"] = status
        if task_type is not None:
            conditions.append("ct.task_type = :task_type")
            params["task_type"] = task_type
        if assigned_to is not None:
            conditions.append("ct.assigned_to = :assigned_to")
            params["assigned_to"] = assigned_to
        if due_date_from is not None:
            conditions.append("ct.due_date >= :due_date_from")
            params["due_date_from"] = due_date_from
        if due_date_to is not None:
            conditions.append("ct.due_date <= :due_date_to")
            params["due_date_to"] = due_date_to
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                text(f"SELECT COUNT(*) as cnt FROM claim_tasks ct {where}"),
                params,
            ).fetchone()
            total = count_row[0]
            rows = conn.execute(
                text(
                    f"""SELECT ct.* FROM claim_tasks ct {where}
                    ORDER BY
                        CASE ct.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE ct.status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        ct.created_at DESC
                    LIMIT :limit OFFSET :offset"""
                ),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows], total

    def get_task_stats(self) -> dict[str, Any]:
        """Get aggregate task statistics."""
        with get_connection(self._db_path) as conn:
            total = conn.execute(text("SELECT COUNT(*) as cnt FROM claim_tasks")).fetchone()[0]
            by_status = {
                (d := row_to_dict(r))["status"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY status"
                    )
                ).fetchall()
            }
            by_type = {
                (d := row_to_dict(r))["task_type"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(task_type, 'unknown') as task_type, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY task_type"
                    )
                ).fetchall()
            }
            by_priority = {
                (d := row_to_dict(r))["priority"]: d["cnt"]
                for r in conn.execute(
                    text(
                        "SELECT COALESCE(priority, 'unknown') as priority, COUNT(*) as cnt "
                        "FROM claim_tasks GROUP BY priority"
                    )
                ).fetchall()
            }
            overdue = conn.execute(
                text(
                    "SELECT COUNT(*) as cnt FROM claim_tasks "
                    "WHERE due_date IS NOT NULL AND date(due_date) < CURRENT_DATE "
                    "AND status NOT IN ('completed', 'cancelled')"
                )
            ).fetchone()[0]
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_priority": by_priority,
            "overdue": overdue,
        }
