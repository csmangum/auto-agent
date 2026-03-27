"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only for updates: it only
inserts new audit entries and does not UPDATE rows. DELETE is used only by
purge_audit_log_for_claims when AUDIT_LOG_PURGE_ENABLED is true (after DB
migration removing the delete trigger).

The focused sub-repositories below handle specific concerns and are composed
by ClaimRepository to maintain backward-compatible delegation:

- NoteRepository          – claim_notes CRUD
- FollowUpRepository      – follow_up_messages CRUD
- TaskRepository          – claim_tasks CRUD
- SubrogationRepository   – subrogation_cases CRUD
- WorkflowRepository      – workflow_runs + task_checkpoints
- ClaimPartyRepository    – claim_parties + claim_party_relationships
- ClaimSearchRepository   – search and fraud-detection relationship graph
- ClaimRetentionRepository– retention lifecycle (archive / purge / cold-storage)
"""

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from claim_agent.models.claim import Attachment

from claim_agent.compliance.ucspa import (
    compute_communication_response_due,
    payment_due_iso_after_settlement_moment,
)
from claim_agent.compliance.state_rules import get_prompt_payment_base_date

from claim_agent.db.audit_events import (
    ACTOR_RETENTION,
    ACTOR_SYSTEM,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_ACKNOWLEDGED,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_ASSIGN,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
    AUDIT_EVENT_CLAIM_REVIEW,
    AUDIT_EVENT_CLAIMANT_COMMUNICATION,
    AUDIT_EVENT_COVERAGE_VERIFICATION,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_DOCUMENT_ACCESSED,
    AUDIT_EVENT_DOCUMENT_DOWNLOADED,
    AUDIT_EVENT_DENIAL_LETTER,
    AUDIT_EVENT_ESCALATE_TO_SIU,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REQUEST_INFO,
    AUDIT_EVENT_RESERVE_ADJUSTED,
    AUDIT_EVENT_RESERVE_ADEQUACY_GATE,
    AUDIT_EVENT_RESERVE_SET,
    AUDIT_EVENT_SIU_CASE_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
    AUDIT_EVENT_TASK_UPDATED,
)
from claim_agent.db.constants import (
    RETENTION_TIER_ACTIVE,
    RETENTION_TIER_COLD,
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_SETTLED,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.db.reserve_adequacy import compute_reserve_adequacy_details
from claim_agent.config.settings import get_reserve_config
from claim_agent.db.database import get_connection, is_postgres_backend, row_to_dict
from claim_agent.db.state_machine import validate_transition
from claim_agent.exceptions import (
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    DomainValidationError,
    InvalidClaimTransitionError,
    ReserveAuthorityError,
)
from claim_agent.utils.sanitization import (
    sanitize_actor_id,
    sanitize_denial_reason,
    sanitize_note,
    truncate_audit_json,
)
from claim_agent.events import ClaimEvent, emit_claim_event
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from claim_agent.notifications.claimant import notify_claimant

# ---------------------------------------------------------------------------
# Focused sub-repositories (imported for composition inside ClaimRepository)
# ---------------------------------------------------------------------------
from claim_agent.db.note_repository import NoteRepository
from claim_agent.db.follow_up_repository import FollowUpRepository
from claim_agent.db.task_repository import TaskRepository
from claim_agent.db.subrogation_repository import SubrogationRepository
from claim_agent.db.workflow_repository import WorkflowRepository
from claim_agent.db.claim_party_repository import ClaimPartyRepository
from claim_agent.db.claim_search_repository import (
    ClaimSearchRepository,
    # Re-export RELATION_SHARED_* constants for backward compatibility  # noqa: F401
    RELATION_SHARED_VIN,  # noqa: F401
    RELATION_SHARED_ADDRESS,  # noqa: F401
    RELATION_SHARED_PROVIDER,  # noqa: F401
    RELATION_SHARED_PHONE,  # noqa: F401
    RELATION_SHARED_EMAIL,  # noqa: F401
    _HIGH_RISK_RELATIONS,  # noqa: F401
    resolve_edge_relations as _resolve_edge_relations_fn,
)
from claim_agent.db.claim_retention_repository import (
    ClaimRetentionRepository,
    # Re-export helper functions for backward compatibility  # noqa: F401
    _add_calendar_years,  # noqa: F401
    _is_claim_past_retention,  # noqa: F401
    _is_archived_past_purge_period,  # noqa: F401
    _is_purged_past_audit_retention_period,  # noqa: F401
    _sql_in_params,  # noqa: F401
)


# _resolve_edge_relations is now provided by ClaimSearchRepository (see resolve_edge_relations).
# Keep a module-level alias for backward compatibility with any code that references it directly.
def _resolve_edge_relations(
    src_vins: list[str],
    src_addresses: list[str],
    src_providers: list[str],
    src_phones: list[str],
    src_emails: list[str],
    tgt_claim: dict[str, Any],
    tgt_parties: list[dict[str, Any]],
) -> list[str]:
    """Delegate to ClaimSearchRepository.resolve_edge_relations (backward-compat alias)."""
    return _resolve_edge_relations_fn(
        src_vins, src_addresses, src_providers, src_phones, src_emails, tgt_claim, tgt_parties
    )


# Matches ``auto_created_from`` for FNOL UCSPA prompt-payment tasks (see ucspa.create_ucspa_compliance_tasks).
_UCSPA_PROMPT_PAYMENT_TASK_MARKER = "ucspa:prompt_payment"


def _generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


_DENIAL_LETTER_DELIVERY_METHODS = {"mail", "email", "certified_mail"}
# Tracking IDs are external carrier references; cap to a conservative varchar-like size.
_MAX_DENIAL_LETTER_TRACKING_ID = 255


def _normalize_denial_letter_delivery_method(method: str | None) -> str | None:
    """Normalize optional denial letter delivery method.

    Returns lowercase method for accepted values (mail, email, certified_mail).
    Returns ``None`` when value is missing or empty after trimming.
    Raises ``ValueError`` for any non-empty unsupported value.
    """
    if not isinstance(method, str):
        return None
    normalized = method.strip().lower()
    # Empty strings are treated as "not provided" for optional metadata.
    if not normalized:
        return None
    if normalized not in _DENIAL_LETTER_DELIVERY_METHODS:
        raise ValueError(
            "denial_letter_delivery_method must be one of: mail, email, certified_mail"
        )
    return normalized


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


# ---------------------------------------------------------------------------
# The helper functions _is_claim_past_retention, _add_calendar_years,
# _is_archived_past_purge_period, _is_purged_past_audit_retention_period,
# and _sql_in_params are now defined in claim_retention_repository and
# imported above for backward compatibility.
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class ClaimRepository:
    """Repository for claim persistence and audit logging.

    Composes focused sub-repositories for specific concerns while preserving
    the original public API via delegation methods.  New code should prefer
    importing the focused repository directly (e.g. TaskRepository) rather
    than going through this class.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        # Focused sub-repositories composed via delegation
        self._note_repo = NoteRepository(db_path)
        self._follow_up_repo = FollowUpRepository(db_path)
        self._task_repo = TaskRepository(db_path)
        self._subrogation_repo = SubrogationRepository(db_path)
        self._workflow_repo = WorkflowRepository(db_path)
        self._party_repo = ClaimPartyRepository(db_path)
        self._search_repo = ClaimSearchRepository(db_path)
        self._retention_repo = ClaimRetentionRepository(db_path)

    @property
    def db_path(self) -> str | None:
        """SQLite path override from construction, or None for configured default."""
        return self._db_path

    @staticmethod
    def _normalize_loss_state(loss_state: str | None) -> str | None:
        """Normalize a loss_state value: strip whitespace and coerce empty strings to ``None``."""
        if loss_state is None:
            return None
        return str(loss_state).strip() or None

    def _resolve_policy_for_fnol(
        self,
        claim_input: ClaimInput,
        policy: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return the policy dict to use for the FNOL policyholder merge.

        Returns *policy* unchanged when it is already provided or when the
        intake already contains a policyholder party.  Otherwise queries the
        configured policy adapter (external I/O).
        """
        intake_has_policyholder = any(
            getattr(p, "party_type", None) == "policyholder" for p in (claim_input.parties or [])
        )
        if intake_has_policyholder or policy is not None:
            return policy
        try:
            from claim_agent.adapters.registry import get_policy_adapter

            return get_policy_adapter().get_policy(claim_input.policy_number)
        except Exception:
            logging.getLogger(__name__).debug(
                "fnol_policy_lookup_failed policy_number=%s",
                claim_input.policy_number,
                exc_info=True,
            )
            return None

    def create_claim_in_transaction(
        self,
        conn: Any,
        claim_input: ClaimInput,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        policy: dict[str, Any] | None = None,
    ) -> str:
        """Insert a new claim within an existing connection/transaction.

        Unlike :meth:`create_claim`, this method reuses *conn* for all database
        operations instead of opening a new connection.  The caller is
        responsible for committing or rolling back *conn*.

        *policy* should be pre-fetched **before** opening the enclosing
        transaction so that external I/O (the policy adapter) is not performed
        while the transaction is open.  Use :meth:`_resolve_policy_for_fnol`
        for that lookup.  When *policy* is ``None`` and the intake parties
        contain no policyholder, the named-insured merge step is skipped.

        UCSPA deadline setting and :func:`emit_claim_event` are **not**
        performed by this method; the caller must invoke them after the
        enclosing transaction commits.

        Returns:
            The new claim's ID (e.g. ``"CLM-XXXXXXXX"``).
        """
        claim_id = _generate_claim_id()
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in claim_input.attachments],
            default=str,
        )
        loss_state_val = self._normalize_loss_state(claim_input.loss_state)
        incident_id_val = claim_input.incident_id
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text("""
            INSERT INTO claims (
                id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                incident_date, incident_description, damage_description, estimated_damage,
                claim_type, loss_state, status, attachments, incident_id, retention_tier,
                incident_latitude, incident_longitude
            ) VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                     :incident_date, :incident_description, :damage_description, :estimated_damage,
                     :claim_type, :loss_state, :status, :attachments, :incident_id, :retention_tier,
                     :incident_latitude, :incident_longitude)
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
                "incident_latitude": claim_input.incident_latitude,
                "incident_longitude": claim_input.incident_longitude,
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
        # Merge policyholder from pre-fetched policy (no external I/O inside transaction).
        from claim_agent.services.fnol_policyholder import (
            merge_fnol_parties_with_named_insured_policyholder,
        )

        effective_parties = merge_fnol_parties_with_named_insured_policyholder(
            claim_input.parties, policy
        )
        for p in effective_parties:
            self._party_repo.add_claim_party_core(conn, claim_id, p)

        return claim_id

    def _add_claim_party_core(self, conn: Any, claim_id: str, party: ClaimPartyInput) -> int:
        """Insert a claim party using an existing connection. Does not commit.

        Delegates to ClaimPartyRepository.add_claim_party_core.
        """
        return self._party_repo.add_claim_party_core(conn, claim_id, party)

    def create_claim(
        self,
        claim_input: ClaimInput,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        policy: dict[str, Any] | None = None,
    ) -> str:
        """Insert new claim, generate ID, log 'created' audit entry. Returns claim_id.

        When *policy* is omitted, the configured policy adapter is queried for
        ``claim_input.policy_number`` to optionally merge a policyholder party from
        ``named_insured`` (see ``merge_fnol_parties_with_named_insured_policyholder``).
        Pass a pre-fetched policy dict to avoid a duplicate lookup or to override.
        """
        # Resolve policy before opening the connection (external I/O must not run
        # inside the transaction).
        policy_for_fnol = self._resolve_policy_for_fnol(claim_input, policy)
        loss_state_val = self._normalize_loss_state(claim_input.loss_state)

        with get_connection(self._db_path) as conn:
            claim_id = self.create_claim_in_transaction(
                conn, claim_input, actor_id=actor_id, policy=policy_for_fnol
            )

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
        return self._party_repo.add_claim_party(claim_id, party)

    def add_claim_party_relationship(
        self,
        claim_id: str,
        from_party_id: int,
        to_party_id: int,
        relationship_type: str,
    ) -> int:
        """Insert a party-to-party edge. Validates both parties belong to claim_id.

        Returns new relationship row id.
        """
        return self._party_repo.add_claim_party_relationship(
            claim_id, from_party_id, to_party_id, relationship_type
        )

    def delete_claim_party_relationship(self, claim_id: str, relationship_id: int) -> bool:
        """Delete a party edge if it exists and both endpoints belong to claim_id."""
        return self._party_repo.delete_claim_party_relationship(claim_id, relationship_id)

    def get_claim_parties(
        self, claim_id: str, party_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch parties for a claim, optionally filtered by party_type.

        Each party dict includes ``relationships``: outgoing edges from claim_party_relationships
        (ordered by relationship id ascending; first ``represented_by`` wins for contact routing).
        """
        return self._party_repo.get_claim_parties(claim_id, party_type)

    def get_claim_party_by_type(self, claim_id: str, party_type: str) -> dict[str, Any] | None:
        """Get first party of given type for a claim."""
        return self._party_repo.get_claim_party_by_type(claim_id, party_type)

    def update_claim_party(self, party_id: int, updates: dict[str, Any]) -> None:
        """Update a claim party by id. Only provided keys are updated."""
        return self._party_repo.update_claim_party(party_id, updates)

    def get_primary_contact_for_user_type(
        self, claim_id: str, user_type: str
    ) -> dict[str, Any] | None:
        """Resolve contact for user_type. If claimant has attorney, return attorney.
        Maps: claimant->claimant or attorney; policyholder->policyholder.
        repair_shop/siu/adjuster/other: no party record, return None."""
        return self._party_repo.get_primary_contact_for_user_type(claim_id, user_type)

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

    def get_claims_by_ids(self, claim_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch claims by ID. Omitted keys are not in the returned map."""
        if not claim_ids:
            return {}
        placeholders, params = _sql_in_params("gcid_", claim_ids)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(f"SELECT * FROM claims WHERE id IN ({placeholders})"),
                params,
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            d = row_to_dict(row)
            cid = d.get("id")
            if cid is not None:
                out[str(cid)] = d
        return out

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
        warn_details = (
            f"Reserve inadequate at status={new_status} (warn mode allows transition); "
            f"warning_codes={','.join(codes)}; " + "; ".join(warnings[:5])
        )
        if mode == "warn":
            details = warn_details
        elif mode == "block" and skip_adequacy_check and elevated:
            details = (
                f"Reserve adequacy waived (role={role}); "
                f"warning_codes={','.join(codes)}; " + "; ".join(warnings[:5])
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

        When ``skip_validation=True``, the state machine is not run: **all** transition
        rules are skipped, including the reserve adequacy gate, the close guard, and
        claim-type guards. No ``reserve_adequacy_gate`` audit row is written for an
        inadequate reserve in ``block`` mode (there is no waiver without an elevated
        ``skip_adequacy_check``). Use only for migrations, recovery, or tests.
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT status, claim_type, payout_amount, "
                    "repair_ready_for_settlement, total_loss_settlement_authorized, "
                    "reserve_amount, estimated_damage, loss_state, settlement_agreed_at, "
                    "payment_due "
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

            final_payment_due = row_d.get("payment_due")
            final_settlement_agreed_at = row_d.get("settlement_agreed_at")
            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
                "repair_ready_for_settlement": old_rr,
                "total_loss_settlement_authorized": old_tla,
                "payment_due": final_payment_due,
                "settlement_agreed_at": final_settlement_agreed_at,
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

            if (
                new_status == STATUS_SETTLED
                and old_status != STATUS_SETTLED
                and row_d.get("settlement_agreed_at") is None
            ):
                loss_state_val = row_d.get("loss_state")
                conn.execute(
                    text("""
                    UPDATE claims
                    SET settlement_agreed_at = :sa, updated_at = :now_u
                    WHERE id = :claim_id
                    """),
                    {"sa": now, "now_u": now, "claim_id": claim_id},
                )
                final_settlement_agreed_at = now
                new_pd = None
                if get_prompt_payment_base_date(loss_state_val) == "settlement_agreement":
                    new_pd = payment_due_iso_after_settlement_moment(now, loss_state_val)
                if new_pd:
                    conn.execute(
                        text("""
                        UPDATE claims SET payment_due = :pd, updated_at = :now_u
                        WHERE id = :claim_id
                        """),
                        {"pd": new_pd, "now_u": now, "claim_id": claim_id},
                    )
                    final_payment_due = new_pd
                    task_rows = conn.execute(
                        text("""
                        SELECT id FROM claim_tasks
                        WHERE claim_id = :claim_id
                          AND auto_created_from = :marker
                          AND status NOT IN ('completed', 'cancelled')
                        """),
                        {
                            "claim_id": claim_id,
                            "marker": _UCSPA_PROMPT_PAYMENT_TASK_MARKER,
                        },
                    ).fetchall()
                    for tr in task_rows:
                        tid = int(tr[0])
                        conn.execute(
                            text("""
                            UPDATE claim_tasks SET due_date = :due, updated_at = CURRENT_TIMESTAMP
                            WHERE id = :tid
                            """),
                            {"due": new_pd, "tid": tid},
                        )
                        conn.execute(
                            text("""
                            INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                            VALUES (:claim_id, :action, :details, :actor_id)
                            """),
                            {
                                "claim_id": claim_id,
                                "action": AUDIT_EVENT_TASK_UPDATED,
                                "details": json.dumps({"task_id": tid, "due_date": new_pd}),
                                "actor_id": actor_id,
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

            after_state = {
                "status": new_status,
                "claim_type": claim_type if claim_type is not None else old_claim_type,
                "payout_amount": payout_amount if payout_amount is not None else old_payout,
                "repair_ready_for_settlement": new_rr,
                "total_loss_settlement_authorized": new_tla,
                "payment_due": final_payment_due,
                "settlement_agreed_at": final_settlement_agreed_at,
            }
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

    def acquire_processing_lock(
        self,
        claim_id: str,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Atomically acquire a processing lock by transitioning claim to ``processing``.

        Uses an optimistic-locking ``UPDATE … WHERE id = :id AND status = :old_status``
        to eliminate the TOCTOU window: the UPDATE only succeeds when the row still holds
        the exact status we read and validated.  This is safe for both SQLite WAL and
        PostgreSQL.

        Raises:
            ClaimNotFoundError: if the claim does not exist.
            ClaimAlreadyProcessingError: if the claim is already in ``processing`` status.
            InvalidClaimTransitionError: if the current status cannot transition to
                ``processing`` according to the state machine, or if the row was
                modified concurrently to another status (optimistic lock lost).
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")

            old_status = row[0]
            if old_status == STATUS_PROCESSING:
                raise ClaimAlreadyProcessingError(claim_id)

            # Validate the transition using the status we just read.
            validate_transition(claim_id, old_status, STATUS_PROCESSING, actor_id=actor_id)

            # Optimistic-lock UPDATE: only succeeds when status hasn't changed since our
            # SELECT.  If a concurrent request already updated the row (to 'processing' or
            # any other value), rowcount will be 0 and we raise appropriately.
            result = conn.execute(
                text(
                    "UPDATE claims SET status = :new_status, updated_at = :now "
                    "WHERE id = :claim_id AND status = :old_status"
                ),
                {
                    "new_status": STATUS_PROCESSING,
                    "now": now,
                    "claim_id": claim_id,
                    "old_status": old_status,
                },
            )
            if result.rowcount == 0:
                # Status changed concurrently — re-read to decide the right exception.
                current_row = conn.execute(
                    text("SELECT status FROM claims WHERE id = :claim_id"),
                    {"claim_id": claim_id},
                ).fetchone()
                if current_row is not None and current_row[0] == STATUS_PROCESSING:
                    raise ClaimAlreadyProcessingError(claim_id)
                concurrent = current_row[0] if current_row is not None else None
                raise InvalidClaimTransitionError(
                    claim_id,
                    old_status,
                    STATUS_PROCESSING,
                    reason=(
                        f"claim status changed concurrently to {concurrent!r}; "
                        "retry the operation"
                    ),
                )

            conn.execute(
                text("""
                INSERT INTO claim_audit_log
                    (claim_id, action, old_status, new_status, details, actor_id,
                     before_state, after_state)
                VALUES
                    (:claim_id, :action, :old_status, :new_status, :details, :actor_id,
                     :before_state, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_STATUS_CHANGE,
                    "old_status": old_status,
                    "new_status": STATUS_PROCESSING,
                    "details": "Processing lock acquired",
                    "actor_id": actor_id,
                    "before_state": json.dumps({"status": old_status}),
                    "after_state": json.dumps({"status": STATUS_PROCESSING}),
                },
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_PROCESSING,
                summary="Processing lock acquired",
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
        return self._workflow_repo.save_workflow_result(
            claim_id, claim_type, router_output, workflow_output
        )

    def get_workflow_runs(
        self,
        claim_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch workflow run records for a claim, most recent first."""
        return self._workflow_repo.get_workflow_runs(claim_id, limit)

    def save_task_checkpoint(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_key: str,
        output: str,
    ) -> None:
        """Persist a stage checkpoint. Replaces any existing checkpoint for the same key."""
        return self._workflow_repo.save_task_checkpoint(
            claim_id, workflow_run_id, stage_key, output
        )

    def get_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
    ) -> dict[str, str]:
        """Load all checkpoints for a workflow run. Returns {stage_key: output_json}."""
        return self._workflow_repo.get_task_checkpoints(claim_id, workflow_run_id)

    def delete_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
        stage_keys: list[str] | None = None,
    ) -> None:
        """Delete checkpoints. If stage_keys given, only those; if None, all for the run.
        Empty list deletes nothing."""
        return self._workflow_repo.delete_task_checkpoints(claim_id, workflow_run_id, stage_keys)

    def get_latest_checkpointed_run_id(self, claim_id: str) -> str | None:
        """Return the most recent workflow_run_id that has checkpoints for this claim."""
        return self._workflow_repo.get_latest_checkpointed_run_id(claim_id)

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
        return self._note_repo.add_note(claim_id, note, actor_id)

    def get_notes(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all notes for a claim, ordered by created_at ascending. Raises ClaimNotFoundError if claim does not exist."""
        return self._note_repo.get_notes(claim_id)

    def create_follow_up_message(
        self,
        claim_id: str,
        user_type: str,
        message_content: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        topic: str | None = None,
    ) -> int:
        """Create a follow-up message record. Returns the message id. Raises ClaimNotFoundError if claim does not exist."""
        return self._follow_up_repo.create_follow_up_message(
            claim_id, user_type, message_content, actor_id=actor_id, topic=topic
        )

    def mark_follow_up_sent(self, message_id: int) -> None:
        """Mark a follow-up message as sent (status=sent) and log audit."""
        return self._follow_up_repo.mark_follow_up_sent(message_id)

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
        return self._follow_up_repo.record_follow_up_response(
            message_id, response_content, actor_id=actor_id, expected_claim_id=expected_claim_id
        )

    def get_pending_follow_ups(
        self,
        claim_id: str,
        *,
        user_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending or sent (not yet responded) follow-up messages for a claim."""
        return self._follow_up_repo.get_pending_follow_ups(claim_id, user_type=user_type)

    def get_follow_up_messages(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all follow-up messages for a claim."""
        return self._follow_up_repo.get_follow_up_messages(claim_id)

    def get_follow_up_message_by_id(self, message_id: int) -> dict[str, Any] | None:
        """Return a single follow-up message row by id, or None if missing."""
        return self._follow_up_repo.get_follow_up_message_by_id(message_id)

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

    def insert_document_download_audit(
        self,
        claim_id: str,
        *,
        storage_key: str,
        actor_id: str,
        channel: str,
    ) -> None:
        """Append audit row when an attachment file is served (chain of custody).

        ``channel`` should distinguish caller surface (e.g. ``adjuster_api``, ``portal``).
        Structured fields are stored in ``after_state`` JSON for querying.

        Raises if the audit row cannot be inserted; callers must not serve the file without it.
        """
        payload = truncate_audit_json({"storage_key": storage_key, "channel": channel})
        self.insert_audit_entry(
            claim_id,
            AUDIT_EVENT_DOCUMENT_DOWNLOADED,
            actor_id=sanitize_actor_id(actor_id),
            details="",
            after_state=payload,
        )

    def insert_document_accessed_audit(
        self,
        claim_id: str,
        *,
        storage_key: str,
        actor_id: str,
        channel: str,
    ) -> None:
        """Append audit row when a presigned (or equivalent) document URL is issued.

        ``channel`` distinguishes caller surface (e.g. ``adjuster_api``, ``portal``).
        Raises if the audit row cannot be inserted; callers must not return the URL without it.
        """
        payload = truncate_audit_json({"storage_key": storage_key, "channel": channel})
        self.insert_audit_entry(
            claim_id,
            AUDIT_EVENT_DOCUMENT_ACCESSED,
            actor_id=sanitize_actor_id(actor_id),
            details="",
            after_state=payload,
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
        return self._subrogation_repo.create_subrogation_case(
            claim_id,
            case_id,
            amount_sought,
            opposing_carrier=opposing_carrier,
            liability_percentage=liability_percentage,
            liability_basis=liability_basis,
        )

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
        return self._subrogation_repo.update_subrogation_case(
            case_id,
            arbitration_status=arbitration_status,
            arbitration_forum=arbitration_forum,
            dispute_date=dispute_date,
            opposing_carrier=opposing_carrier,
            status=status,
            recovery_amount=recovery_amount,
        )

    def get_subrogation_cases_by_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Fetch all subrogation cases for a claim."""
        return self._subrogation_repo.get_subrogation_cases_by_claim(claim_id)

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
        if newly_set:
            self._notify_claimant_best_effort(claim_id=claim_id, event="receipt_acknowledged")
        return newly_set

    def record_denial_letter(
        self,
        claim_id: str,
        denial_reason: str,
        denial_letter_body: str,
        denial_letter_delivery_method: str | None = None,
        denial_letter_tracking_id: str | None = None,
        denial_letter_delivered_at: str | None = None,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Record UCSPA-compliant denial letter (written, specific, with appeal rights)."""
        safe_reason = sanitize_denial_reason(denial_reason) or "Coverage denied"
        safe_actor = sanitize_actor_id(actor_id)
        delivery_method = _normalize_denial_letter_delivery_method(denial_letter_delivery_method)
        tracking_id_raw = (denial_letter_tracking_id or "").strip()
        tracking_id = tracking_id_raw[:_MAX_DENIAL_LETTER_TRACKING_ID] if tracking_id_raw else None
        delivered_at_raw = (denial_letter_delivered_at or "").strip()
        delivered_at = delivered_at_raw if delivered_at_raw else None
        if delivered_at:
            try:
                datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("denial_letter_delivered_at must be a valid ISO-8601 timestamp") from exc
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                UPDATE claims SET denial_reason = :reason, denial_letter_sent_at = :now,
                    denial_letter_body = :body, denial_letter_delivery_method = :delivery_method,
                    denial_letter_tracking_id = :tracking_id, denial_letter_delivered_at = :delivered_at,
                    updated_at = :now WHERE id = :claim_id
                """),
                {
                    "reason": safe_reason,
                    "now": now,
                    "body": denial_letter_body[:65535],
                    "delivery_method": delivery_method,
                    "tracking_id": tracking_id,
                    "delivered_at": delivered_at,
                    "claim_id": claim_id,
                },
            )
            if result.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            after_state = {
                "denial_reason": safe_reason,
                "denial_letter_sent_at": now,
            }
            if delivery_method:
                after_state["denial_letter_delivery_method"] = delivery_method
            if tracking_id:
                after_state["denial_letter_tracking_id"] = tracking_id
            if delivered_at:
                after_state["denial_letter_delivered_at"] = delivered_at
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
                    "after_state": json.dumps(after_state),
                },
            )
        self._notify_claimant_best_effort(
            claim_id=claim_id,
            event="denial_letter",
            template_data={"denial_reason": safe_reason},
        )

    def _notify_claimant_best_effort(
        self,
        *,
        claim_id: str,
        event: str,
        template_data: dict[str, Any] | None = None,
    ) -> None:
        try:
            contact = self.get_primary_contact_for_user_type(claim_id, "claimant") or {}
            if not contact:
                logger.debug(
                    "No claimant contact found for notification: claim_id=%s event=%s",
                    claim_id,
                    event,
                )
                return
            notify_claimant(
                event,
                claim_id,
                email=contact.get("email"),
                phone=contact.get("phone"),
                template_data=template_data,
            )
        except Exception as e:
            logger.warning(
                "Claimant notification failed (best-effort): claim_id=%s event=%s error_type=%s error=%s",
                claim_id,
                event,
                type(e).__name__,
                e,
            )

    def record_claimant_communication(
        self,
        claim_id: str,
        *,
        description: str = "Claimant communication received",
        actor_id: str = ACTOR_WORKFLOW,
        communication_at: str | None = None,
    ) -> str | None:
        """Record a claimant inbound communication and refresh the response deadline.

        Sets ``last_claimant_communication_at`` to ``communication_at`` (or UTC now)
        and recomputes ``communication_response_due`` from the state-specific
        ``communication_response_days``. A compliance task is created for the
        response deadline.

        Args:
            claim_id: Claim identifier.
            description: Short description of the communication (for audit trail).
            actor_id: Actor recording the communication (default: workflow).
            communication_at: ISO timestamp of the communication. Defaults to UTC now.

        Returns:
            ``communication_response_due`` ISO date string (YYYY-MM-DD), or ``None``
            if no deadline could be computed (e.g. invalid timestamp or state rules
            explicitly set no requirement).

        Raises:
            ClaimNotFoundError: If the claim does not exist.
        """
        safe_actor = sanitize_actor_id(actor_id)
        now_ts = communication_at or datetime.now(timezone.utc).isoformat()

        with get_connection(self._db_path) as conn:
            # Fetch loss_state to compute state-specific response deadline.
            row = conn.execute(
                text("SELECT loss_state FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            loss_state = row_to_dict(row).get("loss_state")

            response_due = compute_communication_response_due(now_ts, loss_state)

            conn.execute(
                text("""
                UPDATE claims
                SET last_claimant_communication_at = :comm_at,
                    communication_response_due = :due,
                    updated_at = :now_u
                WHERE id = :claim_id
                """),
                {
                    "comm_at": now_ts,
                    "due": response_due,
                    "now_u": datetime.now(timezone.utc).isoformat(),
                    "claim_id": claim_id,
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                VALUES (:claim_id, :action, :details, :actor_id, :after_state)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_CLAIMANT_COMMUNICATION,
                    "details": description[:500],
                    "actor_id": safe_actor,
                    "after_state": json.dumps({
                        "last_claimant_communication_at": now_ts,
                        "communication_response_due": response_due,
                    }),
                },
            )

        # Create a compliance task for the response deadline.
        if response_due:
            try:
                state_label = f" ({loss_state})" if loss_state else ""
                self.create_task(
                    claim_id,
                    f"Respond to claimant communication{state_label}",
                    "follow_up_claimant",
                    description=description[:500],
                    priority="high",
                    created_by="ucspa_system",
                    due_date=response_due,
                    auto_created_from="ucspa:communication_response",
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "ucspa_comm_response_task_failed claim_id=%s: %s",
                    claim_id,
                    e,
                )

        return response_due

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

    def get_stuck_processing_claims(self, stuck_after_minutes: int) -> list[dict[str, Any]]:
        """Return claims that have been in 'processing' status for longer than stuck_after_minutes.

        Used by the startup recovery scan to detect in-flight claims that were lost
        when the server was restarted mid-processing.
        """
        if stuck_after_minutes < 1:
            raise ValueError("stuck_after_minutes must be at least 1")
        cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=stuck_after_minutes)
        cutoff_iso = cutoff_dt.isoformat()
        cutoff_space = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        with get_connection(self._db_path) as conn:
            if is_postgres_backend():
                rows = conn.execute(
                    text(
                        "SELECT * FROM claims WHERE status = :status AND updated_at <= :cutoff"
                    ),
                    {"status": STATUS_PROCESSING, "cutoff": cutoff_iso},
                ).fetchall()
            else:
                # SQLite stores updated_at as TEXT; values may be ISO-8601 (e.g. from
                # .isoformat()) or space-separated (e.g. datetime('now')). Compare using
                # the appropriate lexical form so both match the cutoff.
                rows = conn.execute(
                    text(
                        "SELECT * FROM claims WHERE status = :status AND ("
                        "(instr(COALESCE(updated_at, ''), 'T') > 0 AND updated_at <= :cutoff_iso) OR "
                        "(instr(COALESCE(updated_at, ''), 'T') = 0 AND updated_at <= :cutoff_space)"
                        ")"
                    ),
                    {
                        "status": STATUS_PROCESSING,
                        "cutoff_iso": cutoff_iso,
                        "cutoff_space": cutoff_space,
                    },
                ).fetchall()
        return [row_to_dict(r) for r in rows]

    def search_claims(
        self,
        vin: str | None = None,
        incident_date: str | None = None,
        policy_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claims by VIN, policy_number and/or incident_date. All optional; if all None, returns []."""
        return self._search_repo.search_claims(vin, incident_date, policy_number)

    def get_claims_by_party_address(
        self,
        address: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to parties at a matching address."""
        return self._search_repo.get_claims_by_party_address(address, limit=limit)

    def get_claims_by_provider_name(
        self,
        provider_name: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to provider parties with matching name."""
        return self._search_repo.get_claims_by_provider_name(provider_name, limit=limit)

    def _extract_graph_link_keys(
        self,
        claim: dict[str, Any],
        parties: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        """Extract (vins, addresses, provider_names, phones, emails) link keys from a claim."""
        return self._search_repo.extract_graph_link_keys(claim, parties)

    def _query_related_ids_on_conn(
        self,
        conn: Any,
        *,
        vins: list[str],
        addresses: list[str],
        provider_names: list[str],
        phones_unique: list[str],
        emails_unique: list[str],
        exclude_ids: set[str],
        limit: int,
    ) -> set[str]:
        """Batch-query claim IDs related by any shared link key on the given connection."""
        return self._search_repo.query_related_ids_on_conn(
            conn,
            vins=vins,
            addresses=addresses,
            provider_names=provider_names,
            phones_unique=phones_unique,
            emails_unique=emails_unique,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    def build_relationship_snapshot(
        self,
        *,
        claim_id: str,
        max_nodes: int = 100,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        """Build an in-memory bounded relationship graph snapshot from existing claims/parties.

        Performs BFS traversal up to depth 2. At each depth, related claims are found
        by shared VIN, party address, provider name, normalized phone, or normalized
        email. A strict node budget (``max_nodes``) limits the total related nodes;
        when the budget would be exceeded, nodes are selected deterministically by
        ascending claim ID (BFS-level order).

        All DB lookups use batch IN-clause queries on a single connection to avoid
        N+1 connection churn.

        This is a migration-ready compatibility layer. It derives graph signals from
        existing tables without requiring dedicated graph persistence.
        """
        return self._search_repo.build_relationship_snapshot(
            claim_id=claim_id, max_nodes=max_nodes, max_depth=max_depth
        )

    def get_relationship_index_snapshot(self, *, claim_id: str) -> dict[str, Any]:
        """Placeholder for future durable graph index implementation.

        Returns a migration-ready shape while current implementation derives data
        from normalized claims/parties tables.
        """
        return self._search_repo.get_relationship_index_snapshot(claim_id=claim_id)

    def list_claims_for_retention(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List closed claims older than retention period that are not yet archived."""
        return self._retention_repo.list_claims_for_retention(retention_period_years, retention_by_state=retention_by_state, exclude_litigation_hold=exclude_litigation_hold)

    def set_litigation_hold(
        self,
        claim_id: str,
        litigation_hold: bool,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Set or clear litigation hold on a claim. Logs to audit."""
        return self._retention_repo.set_litigation_hold(claim_id, litigation_hold, actor_id=actor_id)

    def retention_report(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        purge_after_archive_years: int = 2,
        purge_by_state: dict[str, int] | None = None,
        audit_log_retention_years_after_purge: int | None = None,
        exclude_litigation_hold_from_audit_eligibility: bool = True,
    ) -> dict[str, Any]:
        """Produce retention audit report: counts by tier, litigation hold, pending archive/purge."""
        return self._retention_repo.retention_report(retention_period_years, retention_by_state=retention_by_state, purge_after_archive_years=purge_after_archive_years, purge_by_state=purge_by_state, audit_log_retention_years_after_purge=audit_log_retention_years_after_purge, exclude_litigation_hold_from_audit_eligibility=exclude_litigation_hold_from_audit_eligibility)

    def archive_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Archive a claim (soft delete for retention). Sets archived_at and status=archived."""
        return self._retention_repo.archive_claim(claim_id, actor_id=actor_id)

    def list_claims_for_purge(
        self,
        purge_after_archive_years: int,
        *,
        purge_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List archived claims past purge horizon (archived_at + N calendar years)."""
        return self._retention_repo.list_claims_for_purge(purge_after_archive_years, purge_by_state=purge_by_state, exclude_litigation_hold=exclude_litigation_hold)

    def purge_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Purge for retention: anonymize PII, status purged, retention_tier purged."""
        return self._retention_repo.purge_claim(claim_id, actor_id=actor_id)

    # ------------------------------------------------------------------
    # Cold-storage export helpers
    # ------------------------------------------------------------------

    def get_cold_storage_export_key(self, claim_id: str) -> str | None:
        """Return the S3 key if this claim has already been exported, else None."""
        return self._retention_repo.get_cold_storage_export_key(claim_id)

    def list_claims_for_export(
        self,
        purge_after_archive_years: int,
        *,
        purge_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List archived claims eligible for cold-storage export."""
        return self._retention_repo.list_claims_for_export(purge_after_archive_years, purge_by_state=purge_by_state, exclude_litigation_hold=exclude_litigation_hold)

    def mark_claim_exported(
        self,
        claim_id: str,
        export_key: str,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Record that a claim has been exported to cold storage."""
        return self._retention_repo.mark_claim_exported(claim_id, export_key, actor_id=actor_id)

    def list_claim_ids_eligible_for_audit_log_retention(
        self,
        audit_retention_years_after_purge: int,
        *,
        exclude_litigation_hold: bool = True,
    ) -> list[str]:
        """Claim IDs (status purged) past purged_at + N calendar years for audit export/purge."""
        return self._retention_repo.list_claim_ids_eligible_for_audit_log_retention(audit_retention_years_after_purge, exclude_litigation_hold=exclude_litigation_hold)

    def fetch_audit_log_rows_for_claim_ids(
        self, claim_ids: list[str], *, chunk_size: int = 400
    ) -> list[dict[str, Any]]:
        """Return audit log rows for the given claim IDs (ordered by claim_id, id)."""
        return self._retention_repo.fetch_audit_log_rows_for_claim_ids(claim_ids, chunk_size=chunk_size)

    def count_audit_log_rows_for_claim_ids(
        self, claim_ids: list[str], *, chunk_size: int = 400
    ) -> int:
        """Count claim_audit_log rows whose claim_id is in claim_ids."""
        return self._retention_repo.count_audit_log_rows_for_claim_ids(claim_ids, chunk_size=chunk_size)

    def purge_audit_log_for_claim_ids(
        self,
        claim_ids: list[str],
        *,
        audit_purge_enabled: bool,
        chunk_size: int = 400,
    ) -> int:
        """Delete claim_audit_log rows for claim_ids. Requires AUDIT_LOG_PURGE_ENABLED."""
        return self._retention_repo.purge_audit_log_for_claim_ids(claim_ids, audit_purge_enabled=audit_purge_enabled, chunk_size=chunk_size)

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
        """Create a task for a claim. Returns the task id. Raises ClaimNotFoundError if claim does not exist."""
        return self._task_repo.create_task(claim_id, title, task_type, description=description, priority=priority, assigned_to=assigned_to, created_by=created_by, due_date=due_date, document_request_id=document_request_id, document_type=document_type, requested_from=requested_from, recurrence_rule=recurrence_rule, recurrence_interval=recurrence_interval, parent_task_id=parent_task_id, auto_created_from=auto_created_from)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Fetch a single task by ID."""
        return self._task_repo.get_task(task_id)

    def get_tasks_for_claim(
        self,
        claim_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks for a claim with optional status filter. Returns (tasks, total)."""
        return self._task_repo.get_tasks_for_claim(claim_id, status=status, limit=limit, offset=offset)

    def list_overdue_tasks(
        self,
        *,
        max_escalation_level: int | None = None,
        min_escalation_level: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List overdue tasks (due_date < today, status not completed/cancelled)."""
        return self._task_repo.list_overdue_tasks(max_escalation_level=max_escalation_level, min_escalation_level=min_escalation_level, limit=limit)

    def mark_task_overdue_notified(self, task_id: int) -> None:
        """Mark task as overdue notification sent (escalation_level=1)."""
        return self._task_repo.mark_task_overdue_notified(task_id)

    def mark_task_supervisor_escalated(self, task_id: int) -> None:
        """Mark task as escalated to supervisor (escalation_level=2)."""
        return self._task_repo.mark_task_supervisor_escalated(task_id)

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
        """Update a task. Returns the updated task dict.

        Raises:
            DomainValidationError: If the task does not exist or validation fails.
        """
        return self._task_repo.update_task(task_id, title=title, description=description, status=status, priority=priority, assigned_to=assigned_to, due_date=due_date, resolution_notes=resolution_notes, actor_id=actor_id)

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
        return self._task_repo.list_all_tasks(status=status, task_type=task_type, assigned_to=assigned_to, due_date_from=due_date_from, due_date_to=due_date_to, limit=limit, offset=offset)

    def get_task_stats(self) -> dict[str, Any]:
        """Get aggregate task statistics."""
        return self._task_repo.get_task_stats()
