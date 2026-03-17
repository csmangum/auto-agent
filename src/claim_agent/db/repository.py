"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only: it only inserts new
audit entries and does not perform UPDATE or DELETE operations on that table.
"""

import json
import logging
import uuid
from typing import Any, cast

from claim_agent.models.claim import Attachment

from claim_agent.db.audit_events import (
    ACTOR_RETENTION,
    ACTOR_SYSTEM,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_ASSIGN,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
    AUDIT_EVENT_CLAIM_REVIEW,
    AUDIT_EVENT_COVERAGE_VERIFICATION,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_ESCALATE_TO_SIU,
    AUDIT_EVENT_FOLLOW_UP_RESPONSE,
    AUDIT_EVENT_FOLLOW_UP_SENT,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REQUEST_INFO,
    AUDIT_EVENT_RESERVE_ADJUSTED,
    AUDIT_EVENT_RESERVE_SET,
    AUDIT_EVENT_RETENTION,
    AUDIT_EVENT_SIU_CASE_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
    AUDIT_EVENT_TASK_CREATED,
    AUDIT_EVENT_TASK_UPDATED,
)
from claim_agent.db.constants import (
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.config.settings import get_reserve_config
from claim_agent.db.database import get_connection
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


def _check_reserve_authority(
    amount: float,
    actor_id: str,
    *,
    role: str = "adjuster",
    skip_authority_check: bool = False,
) -> None:
    """Raise ReserveAuthorityError if amount exceeds actor's limit. Workflow/system bypass."""
    if skip_authority_check or actor_id in (ACTOR_WORKFLOW, ACTOR_SYSTEM):
        return
    cfg = get_reserve_config()
    limit = cfg["supervisor_limit"] if role in ("supervisor", "admin") else cfg["adjuster_limit"]
    if amount > limit:
        raise ReserveAuthorityError(amount, limit, actor_id, role)


class ClaimRepository:
    """Repository for claim persistence and audit logging."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

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
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, loss_state, status, attachments, incident_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    claim_input.policy_number,
                    claim_input.vin,
                    claim_input.vehicle_year,
                    claim_input.vehicle_make,
                    claim_input.vehicle_model,
                    claim_input.incident_date.isoformat(),
                    claim_input.incident_description,
                    claim_input.damage_description,
                    claim_input.estimated_damage,
                    None,
                    loss_state_val,
                    STATUS_PENDING,
                    attachments_json,
                    incident_id_val,
                ),
            )
            after_state = json.dumps({"status": STATUS_PENDING, "claim_type": None, "payout_amount": None})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_CREATED, STATUS_PENDING, "Claim record created", actor_id, after_state),
            )
            # Set initial reserve from estimated_damage at FNOL if configured.
            # FNOL auto-reserve is always treated as a system operation regardless of
            # the calling actor; no authority-limit check applies.
            cfg = get_reserve_config()
            est = claim_input.estimated_damage
            if cfg.get("initial_reserve_from_estimated_damage", True) and est is not None and est > 0:
                conn.execute(
                    "UPDATE claims SET reserve_amount = ?, updated_at = datetime('now') WHERE id = ?",
                    (est, claim_id),
                )
                conn.execute(
                    """
                    INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (claim_id, None, est, "Initial reserve from estimated_damage at FNOL", ACTOR_SYSTEM),
                )
                reserve_state = json.dumps({"reserve_amount": est})
                conn.execute(
                    """
                    INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (claim_id, AUDIT_EVENT_RESERVE_SET, "Initial reserve set from estimated_damage", ACTOR_SYSTEM, reserve_state),
                )
        if claim_input.parties:
            for p in claim_input.parties:
                self.add_claim_party(claim_id, p)

        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_PENDING, summary="Claim submitted")
        )
        return claim_id

    def add_claim_party(self, claim_id: str, party: ClaimPartyInput) -> int:
        """Insert a claim party. Returns party id."""
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO claim_parties (
                    claim_id, party_type, name, email, phone, address, role,
                    represented_by_id, consent_status, authorization_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    party.party_type,
                    party.name,
                    party.email,
                    party.phone,
                    party.address,
                    party.role,
                    party.represented_by_id,
                    party.consent_status or "pending",
                    party.authorization_status or "pending",
                ),
            )
            return int(cursor.lastrowid)

    def get_claim_parties(
        self, claim_id: str, party_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch parties for a claim, optionally filtered by party_type."""
        with get_connection(self._db_path) as conn:
            if party_type:
                rows = conn.execute(
                    "SELECT * FROM claim_parties WHERE claim_id = ? AND party_type = ?",
                    (claim_id, party_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM claim_parties WHERE claim_id = ?", (claim_id,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_claim_party_by_type(
        self, claim_id: str, party_type: str
    ) -> dict[str, Any] | None:
        """Get first party of given type for a claim."""
        parties = self.get_claim_parties(claim_id, party_type=party_type)
        return parties[0] if parties else None

    def update_claim_party(
        self, party_id: int, updates: dict[str, Any]
    ) -> None:
        """Update a claim party by id. Only provided keys are updated."""
        allowed = {
            "name", "email", "phone", "address", "role",
            "represented_by_id", "consent_status", "authorization_status",
        }
        to_set = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not to_set:
            return
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        values = list(to_set.values()) + [party_id]
        with get_connection(self._db_path) as conn:
            conn.execute(
                f"UPDATE claim_parties SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                values,
            )

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
                        "SELECT * FROM claim_parties WHERE id = ? AND claim_id = ?",
                        (claimant["represented_by_id"], claim_id),
                    ).fetchone()
                if row:
                    attorney = dict(row)
                    if attorney.get("email") or attorney.get("phone"):
                        return attorney
            return claimant if (claimant and (claimant.get("email") or claimant.get("phone"))) else None
        if user_type == "policyholder":
            ph = self.get_claim_party_by_type(claim_id, "policyholder")
            return ph if (ph and (ph.get("email") or ph.get("phone"))) else None
        return None

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch claim by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_claim_status(
        self,
        claim_id: str,
        new_status: str,
        details: str | None = None,
        claim_type: str | None = None,
        payout_amount: float | None = None,
        *,
        actor_id: str = ACTOR_WORKFLOW,
        skip_validation: bool = False,
    ) -> None:
        """Update status, optionally claim_type and payout_amount; log state change to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]

            if not skip_validation:
                claim_dict = dict(row)
                validate_transition(
                    claim_id,
                    old_status,
                    new_status,
                    claim=claim_dict,
                    payout_amount=payout_amount,
                    actor_id=actor_id,
                )

            before_state = {
                "status": old_status,
                "claim_type": old_claim_type,
                "payout_amount": old_payout,
            }
            after_state = {
                "status": new_status,
                "claim_type": claim_type if claim_type is not None else old_claim_type,
                "payout_amount": payout_amount if payout_amount is not None else old_payout,
            }

            # Explicit parameterized queries (no dynamic SQL)
            if claim_type is not None and payout_amount is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, claim_type = ?, payout_amount = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_type, payout_amount, claim_id),
                )
            elif claim_type is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, claim_type = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_type, claim_id),
                )
            elif payout_amount is not None:
                conn.execute(
                    """UPDATE claims SET status = ?, payout_amount = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, payout_amount, claim_id),
                )
            else:
                conn.execute(
                    """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                    (new_status, claim_id),
                )

            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_STATUS_CHANGE,
                    old_status,
                    new_status,
                    details or "",
                    actor_id,
                    json.dumps(before_state),
                    json.dumps(after_state),
                ),
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
                """
                INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, claim_type, router_output, workflow_output),
            )

    def get_workflow_runs(
        self,
        claim_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch workflow run records for a claim, most recent first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT claim_type, router_output, workflow_output, created_at
                FROM workflow_runs
                WHERE claim_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (claim_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

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
                """
                INSERT OR REPLACE INTO task_checkpoints
                    (claim_id, workflow_run_id, stage_key, output)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, workflow_run_id, stage_key, output),
            )

    def get_task_checkpoints(
        self,
        claim_id: str,
        workflow_run_id: str,
    ) -> dict[str, str]:
        """Load all checkpoints for a workflow run. Returns {stage_key: output_json}."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT stage_key, output FROM task_checkpoints
                WHERE claim_id = ? AND workflow_run_id = ?
                """,
                (claim_id, workflow_run_id),
            ).fetchall()
        return {row["stage_key"]: row["output"] for row in rows}

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
                placeholders = ",".join("?" for _ in stage_keys)
                conn.execute(
                    f"""
                    DELETE FROM task_checkpoints
                    WHERE claim_id = ? AND workflow_run_id = ? AND stage_key IN ({placeholders})
                    """,
                    [claim_id, workflow_run_id, *stage_keys],
                )
            else:
                conn.execute(
                    """
                    DELETE FROM task_checkpoints
                    WHERE claim_id = ? AND workflow_run_id = ?
                    """,
                    (claim_id, workflow_run_id),
                )

    def get_latest_checkpointed_run_id(self, claim_id: str) -> str | None:
        """Return the most recent workflow_run_id that has checkpoints for this claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT workflow_run_id FROM task_checkpoints
                WHERE claim_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
        return row["workflow_run_id"] if row else None

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
                "SELECT attachments FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            before_attachments = row["attachments"] or "[]"
            cursor = conn.execute(
                "UPDATE claims SET attachments = ?, updated_at = datetime('now') WHERE id = ?",
                (attachments_json, claim_id),
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            before_state = before_attachments  # already a serialized JSON array
            after_state = attachments_json      # already a serialized JSON array
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_ATTACHMENTS_UPDATED,
                    f"Attachments updated: {len(attachments)} file(s)",
                    actor_id,
                    before_state,
                    after_state,
                ),
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
        _check_reserve_authority(amount, actor_id, role=role, skip_authority_check=skip_authority_check)
        safe_actor = sanitize_actor_id(actor_id)
        safe_reason = sanitize_note(reason) if reason else ""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT reserve_amount, status FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_amount = row["reserve_amount"]
            claim_status = row["status"]
            conn.execute(
                "UPDATE claims SET reserve_amount = ?, updated_at = datetime('now') WHERE id = ?",
                (amount, claim_id),
            )
            conn.execute(
                """
                INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, old_amount, amount, safe_reason or "Reserve set", safe_actor),
            )
            before_state = json.dumps({"reserve_amount": old_amount})
            after_state = json.dumps({"reserve_amount": amount})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_RESERVE_SET, safe_reason or "Reserve set", safe_actor, before_state, after_state),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=claim_status, summary=f"Reserve set to ${amount:,.2f}")
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
        _check_reserve_authority(new_amount, actor_id, role=role, skip_authority_check=skip_authority_check)
        safe_actor = sanitize_actor_id(actor_id)
        safe_reason = sanitize_note(reason) if reason else ""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT reserve_amount, status FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_amount = row["reserve_amount"]
            claim_status = row["status"]
            audit_event = AUDIT_EVENT_RESERVE_SET if old_amount is None else AUDIT_EVENT_RESERVE_ADJUSTED
            default_reason = "Reserve set" if old_amount is None else "Reserve adjusted"
            conn.execute(
                "UPDATE claims SET reserve_amount = ?, updated_at = datetime('now') WHERE id = ?",
                (new_amount, claim_id),
            )
            conn.execute(
                """
                INSERT INTO reserve_history (claim_id, old_amount, new_amount, reason, actor_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, old_amount, new_amount, safe_reason or default_reason, safe_actor),
            )
            before_state = json.dumps({"reserve_amount": old_amount})
            after_state = json.dumps({"reserve_amount": new_amount})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    audit_event,
                    safe_reason or default_reason,
                    safe_actor,
                    before_state,
                    after_state,
                ),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=claim_status, summary=f"Reserve adjusted to ${new_amount:,.2f}")
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
                """
                SELECT id, claim_id, old_amount, new_amount, reason, actor_id, created_at
                FROM reserve_history
                WHERE claim_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (claim_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def check_reserve_adequacy(self, claim_id: str) -> dict[str, Any]:
        """Check reserve adequacy vs estimated_damage and payout_amount.

        Returns:
            adequate: True if reserve >= max(estimated_damage, payout or 0)
            reserve, estimated_damage, payout_amount: values from claim
            warnings: list of adequacy warnings
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
        warnings: list[str] = []
        # Benchmark: reserve should be >= estimated_damage, and if payout is set, >= payout
        benchmark = None
        if payout_val is not None and payout_val > 0:
            benchmark = payout_val
        if est_val is not None and est_val > 0:
            benchmark = max(benchmark or 0, est_val)
        if reserve_val is None:
            if benchmark is not None and benchmark > 0:
                warnings.append("No reserve set; reserve should be set for actuarial tracking")
            adequate = benchmark is None or benchmark <= 0
        else:
            if benchmark is not None and reserve_val < benchmark:
                if est_val is not None and est_val == benchmark and (
                    payout_val is None or payout_val <= 0 or payout_val < benchmark
                ):
                    warnings.append(
                        f"Reserve ${reserve_val:,.2f} is below estimated damage ${benchmark:,.2f}"
                    )
                elif payout_val is not None and payout_val == benchmark and (
                    est_val is None or est_val <= 0 or est_val < benchmark
                ):
                    warnings.append(
                        f"Reserve ${reserve_val:,.2f} is below payout ${benchmark:,.2f}"
                    )
                else:
                    parts = []
                    if est_val is not None:
                        parts.append(f"estimated damage ${est_val:,.2f}")
                    if payout_val is not None:
                        parts.append(f"payout ${payout_val:,.2f}")
                    suffix = f" ({', '.join(parts)})" if parts else ""
                    warnings.append(
                        f"Reserve ${reserve_val:,.2f} is below benchmark ${benchmark:,.2f}{suffix}"
                    )
            adequate = benchmark is None or reserve_val >= benchmark
        return {
            "adequate": adequate,
            "reserve": reserve_val,
            "estimated_damage": est_val,
            "payout_amount": payout_val,
            "warnings": warnings,
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
            query = """
                SELECT id, claim_id, action, old_status, new_status, details,
                       actor_id, before_state, after_state, created_at
                FROM claim_audit_log
                WHERE claim_id = ?
                ORDER BY id ASC
            """
            params: tuple[Any, ...] = (claim_id,)
            if limit is not None:
                # Only run COUNT(*) when paginating; fetching a page doesn't
                # give us the total for free.
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM claim_audit_log WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                total = count_row[0] if count_row else 0
                query += " LIMIT ? OFFSET ?"
                params = (claim_id, limit, offset)
            rows = conn.execute(query, params).fetchall()
        result = [dict(r) for r in rows]
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
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_CLAIM_REVIEW, report_json, sanitize_actor_id(actor_id)),
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
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_notes (claim_id, note, actor_id)
                VALUES (?, ?, ?)
                """,
                (claim_id, sanitize_note(note), sanitize_actor_id(actor_id)),
            )

    def get_notes(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all notes for a claim, ordered by created_at ascending. Raises ClaimNotFoundError if claim does not exist."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                """
                SELECT id, claim_id, note, actor_id, created_at
                FROM claim_notes
                WHERE claim_id = ?
                ORDER BY created_at ASC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

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
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            cursor = conn.execute(
                """
                INSERT INTO follow_up_messages (claim_id, user_type, message_content, status, actor_id)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (claim_id, user_type, sanitize_note(message_content), actor_id),
            )
            msg_id = cursor.lastrowid
        return int(msg_id)

    def mark_follow_up_sent(self, message_id: int) -> None:
        """Mark a follow-up message as sent (status=sent) and log audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT claim_id, user_type, actor_id FROM follow_up_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            claim_id = row["claim_id"]
            user_type = row["user_type"]
            actor_id = row["actor_id"]
            conn.execute(
                "UPDATE follow_up_messages SET status = 'sent' WHERE id = ?",
                (message_id,),
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_FOLLOW_UP_SENT, details, actor_id),
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
                "SELECT claim_id, user_type FROM follow_up_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Follow-up message not found: {message_id}")
            claim_id = row["claim_id"]
            user_type = row["user_type"]
            if expected_claim_id is not None and claim_id != expected_claim_id:
                raise ValueError(
                    f"Follow-up message {message_id} does not belong to claim {expected_claim_id}"
                )
            conn.execute(
                """
                UPDATE follow_up_messages
                SET status = 'responded', response_content = ?, responded_at = datetime('now')
                WHERE id = ?
                """,
                (sanitize_note(response_content), message_id),
            )
            details = json.dumps({"user_type": user_type, "message_id": message_id})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_FOLLOW_UP_RESPONSE, details, actor_id),
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
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if user_type:
                rows = conn.execute(
                    """
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = ? AND user_type = ? AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """,
                    (claim_id, user_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                    FROM follow_up_messages
                    WHERE claim_id = ? AND status IN ('pending', 'sent')
                    ORDER BY created_at DESC
                    """,
                    (claim_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_follow_up_messages(self, claim_id: str) -> list[dict[str, Any]]:
        """Get all follow-up messages for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            rows = conn.execute(
                """
                SELECT id, claim_id, user_type, message_content, status, response_content, created_at, responded_at
                FROM follow_up_messages
                WHERE claim_id = ?
                ORDER BY created_at DESC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

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
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, action, old_status, new_status, details or "", actor_id, before_state, after_state),
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
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE claims SET siu_case_id = ?, updated_at = datetime('now') WHERE id = ?
                """,
                (siu_case_id, claim_id),
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_SIU_CASE_CREATED, f"SIU case created: {siu_case_id}", actor_id),
            )

    def update_claim_review_metadata(
        self,
        claim_id: str,
        *,
        priority: str | None = None,
        due_at: str | None = None,
        review_started_at: str | None = None,
    ) -> None:
        """Update review metadata (priority, due_at, review_started_at) on a claim."""
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if due_at is not None:
            updates.append("due_at = ?")
            params.append(due_at)
        if review_started_at is not None:
            updates.append("review_started_at = ?")
            params.append(review_started_at)
        if not params:
            return
        params.append(claim_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                f"UPDATE claims SET {', '.join(updates)} WHERE id = ?",
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
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if liability_percentage is not None:
            updates.append("liability_percentage = ?")
            params.append(liability_percentage)
        if liability_basis is not None:
            updates.append("liability_basis = ?")
            params.append(liability_basis)
        if not params:
            return
        params.append(claim_id)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE claims SET {', '.join(updates)} WHERE id = ?",
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
                "UPDATE claims SET total_loss_metadata = ?, updated_at = datetime('now') WHERE id = ?",
                (meta_json, claim_id),
            )
            if cursor.rowcount == 0:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    def get_claim_total_loss_metadata(self, claim_id: str) -> dict[str, Any] | None:
        """Get total_loss_metadata for a claim, or None if not set."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT total_loss_metadata FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
        if not row or row[0] is None:
            return None
        try:
            return cast(dict[str, Any], json.loads(row[0]))
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
                """
                INSERT INTO subrogation_cases
                    (claim_id, case_id, amount_sought, opposing_carrier,
                     liability_percentage, liability_basis, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    claim_id,
                    case_id,
                    amount_sought,
                    opposing_carrier,
                    liability_percentage,
                    liability_basis,
                ),
            )
            row = conn.execute(
                "SELECT * FROM subrogation_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return dict(row) if row else {}

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
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if arbitration_status is not None:
            updates.append("arbitration_status = ?")
            params.append(arbitration_status)
        if arbitration_forum is not None:
            updates.append("arbitration_forum = ?")
            params.append(arbitration_forum)
        if dispute_date is not None:
            updates.append("dispute_date = ?")
            params.append(dispute_date)
        if opposing_carrier is not None:
            updates.append("opposing_carrier = ?")
            params.append(opposing_carrier)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if recovery_amount is not None:
            updates.append("recovery_amount = ?")
            params.append(recovery_amount)
        if not params:
            return
        params.append(case_id)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE subrogation_cases SET {', '.join(updates)} WHERE case_id = ?",
                params,
            )
            if cursor.rowcount == 0:
                raise DomainValidationError(
                    f"Subrogation case not found for case_id={case_id}"
                )

    def get_subrogation_cases_by_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Fetch all subrogation cases for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM subrogation_cases
                WHERE claim_id = ?
                ORDER BY created_at DESC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def assign_claim(
        self,
        claim_id: str,
        assignee_id: str,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Assign claim to an adjuster. Sets review_started_at if not already set.
        Only claims with status needs_review can be assigned."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT assignee, status FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            if row["status"] != STATUS_NEEDS_REVIEW:
                raise ValueError(
                    f"Claim {claim_id} is not in needs_review (status={row['status']}); "
                    "only claims in the review queue can be assigned"
                )
            old_assignee = row["assignee"]
            conn.execute(
                """
                UPDATE claims SET assignee = ?,
                    review_started_at = COALESCE(review_started_at, datetime('now')),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (assignee_id, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_ASSIGN,
                    f"Assigned to {assignee_id}",
                    actor_id,
                    json.dumps({"assignee": old_assignee}),
                    json.dumps({"assignee": assignee_id}),
                ),
            )

    def _ensure_claim_needs_review(self, conn: Any, claim_id: str) -> Any:
        """Fetch claim row and ensure status is needs_review. Raises if not found or wrong status."""
        row = conn.execute(
            "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        if row["status"] != STATUS_NEEDS_REVIEW:
            raise ValueError(
                f"Claim {claim_id} is not in needs_review (status={row['status']}); "
                "adjuster actions only apply to claims in the review queue"
            )
        return row

    def _ensure_claim_processing(self, conn: Any, claim_id: str) -> Any:
        """Fetch claim row and ensure status is processing. For FNOL denial."""
        row = conn.execute(
            "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        if row["status"] != STATUS_PROCESSING:
            raise ValueError(
                f"Claim {claim_id} is not in processing (status={row['status']}); "
                "FNOL denial only applies to claims in processing"
            )
        return row

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
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_APPROVAL, row["status"], None, "Approved for continued processing", actor_id, None, None),
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
                claim=dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_DENIED, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_DENIED, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_DENIED, safe_reason, actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_REJECTION, old_status, STATUS_DENIED, safe_reason, actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_DENIED, summary=safe_reason)
        )

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
                claim=dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_DENIED, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_DENIED, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_DENIED, safe_reason, actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_REJECTION, old_status, STATUS_DENIED, safe_reason, actor_id, None, None),
            )
            if coverage_verification_details:
                merged = {"outcome": "denied", **coverage_verification_details}
                conn.execute(
                    """
                    INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        AUDIT_EVENT_COVERAGE_VERIFICATION,
                        truncate_audit_json(coverage_verification_details),
                        actor_id,
                        truncate_audit_json(merged),
                    ),
                )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_DENIED, summary=safe_reason)
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
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id, after_state)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_COVERAGE_VERIFICATION,
                    truncate_audit_json(details),
                    actor_id,
                    truncate_audit_json(merged),
                ),
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
                claim=dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_PENDING_INFO, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_PENDING_INFO, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_PENDING_INFO, note or "Requested more information", actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_REQUEST_INFO, old_status, STATUS_PENDING_INFO, note or "", actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_PENDING_INFO, summary=note or "Requested more information")
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
                claim=dict(row),
                actor_id=actor_id,
            )
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]
            before_state = {"status": old_status, "claim_type": old_claim_type, "payout_amount": old_payout}
            after_state = {"status": STATUS_UNDER_INVESTIGATION, "claim_type": old_claim_type, "payout_amount": old_payout}
            conn.execute(
                """UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?""",
                (STATUS_UNDER_INVESTIGATION, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_STATUS_CHANGE, old_status, STATUS_UNDER_INVESTIGATION, "Escalated to SIU", actor_id, json.dumps(before_state), json.dumps(after_state)),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_ESCALATE_TO_SIU, old_status, STATUS_UNDER_INVESTIGATION, "Referred to Special Investigations Unit", actor_id, None, None),
            )
        emit_claim_event(
            ClaimEvent(claim_id=claim_id, status=STATUS_UNDER_INVESTIGATION, summary="Escalated to SIU")
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
        conditions = ["status = ?"]
        params: list[Any] = [STATUS_NEEDS_REVIEW]
        if assignee is not None:
            conditions.append("assignee = ?")
            params.append(assignee)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        if older_than_hours is not None:
            if older_than_hours < 0:
                raise ValueError("older_than_hours must be non-negative")
            conditions.append("review_started_at IS NOT NULL AND datetime(review_started_at) <= datetime('now', ?)")
            params.append(f"-{older_than_hours} hours")
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM claims WHERE {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"SELECT * FROM claims WHERE {where} ORDER BY "
                "CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, "
                "COALESCE(due_at, '9999-12-31') ASC, created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

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
            params = []
            if vin:
                conditions.append("vin = ?")
                params.append(vin)
            if incident_date:
                conditions.append("incident_date = ?")
                params.append(incident_date)
            if policy_number:
                conditions.append("policy_number = ?")
                params.append(policy_number)
            where_clause = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM claims WHERE {where_clause}",
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

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
                """
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE lower(trim(cp.address)) = lower(trim(?))
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (addr, limit),
            ).fetchall()
        return [dict(r) for r in rows]

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
                """
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE cp.party_type = 'provider'
                  AND lower(trim(cp.name)) = lower(trim(?))
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (name, limit),
            ).fetchall()
        return [dict(r) for r in rows]

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
                placeholders = ",".join("?" * len(addresses))
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.id
                    FROM claim_parties cp
                    JOIN claims c ON c.id = cp.claim_id
                    WHERE lower(trim(cp.address)) IN ({placeholders})
                    ORDER BY c.created_at DESC
                    LIMIT ?
                    """,
                    (*addresses, max_nodes * len(addresses)),
                ).fetchall()
                for r in rows:
                    rid = str(r[0] if r else "").strip()
                    if rid and rid != claim_id:
                        related_ids.add(rid)
            if provider_names:
                placeholders = ",".join("?" * len(provider_names))
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.id
                    FROM claim_parties cp
                    JOIN claims c ON c.id = cp.claim_id
                    WHERE cp.party_type = 'provider'
                      AND lower(trim(cp.name)) IN ({placeholders})
                    ORDER BY c.created_at DESC
                    LIMIT ?
                    """,
                    (*provider_names, max_nodes * len(provider_names)),
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
            placeholders = ",".join("?" * len(sorted_related))
            with get_connection(self._db_path) as conn:
                claim_rows = conn.execute(
                    f"SELECT * FROM claims WHERE id IN ({placeholders})",
                    sorted_related,
                ).fetchall()
                party_rows = conn.execute(
                    f"SELECT * FROM claim_parties WHERE claim_id IN ({placeholders})",
                    sorted_related,
                ).fetchall()
            related_claims_by_id = {dict(r)["id"]: dict(r) for r in claim_rows}
            parties_by_claim_id: dict[str, list[dict[str, Any]]] = {}
            for row in party_rows:
                p = dict(row)
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
                if RELATION_SHARED_PROVIDER in relation_types or RELATION_SHARED_ADDRESS in relation_types:
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
    ) -> list[dict[str, Any]]:
        """List closed claims older than retention period that are not yet archived.

        Uses created_at for cutoff. Only returns claims with status closed
        (archiving requires closed->archived transition). Excludes claims
        with status archived or a non-null archived_at.
        """
        if retention_period_years < 0:
            raise ValueError("retention_period_years must be non-negative")
        cutoff = f"-{retention_period_years} years"
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM claims
                WHERE datetime(created_at) <= datetime('now', ?)
                  AND archived_at IS NULL
                  AND status = ?
                ORDER BY created_at ASC
                """,
                (cutoff, STATUS_CLOSED),
            ).fetchall()
        return [dict(r) for r in rows]

    def archive_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Archive a claim (soft delete for retention). Sets archived_at and status=archived."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            if old_status == STATUS_ARCHIVED:
                return
            validate_transition(
                claim_id,
                old_status,
                STATUS_ARCHIVED,
                claim=dict(row),
                actor_id=actor_id,
            )
            conn.execute(
                """
                UPDATE claims SET status = ?, archived_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?
                """,
                (STATUS_ARCHIVED, claim_id),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    AUDIT_EVENT_RETENTION,
                    old_status,
                    STATUS_ARCHIVED,
                    "Archived for retention (claim older than retention period)",
                    actor_id,
                ),
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_ARCHIVED,
                summary="Archived for retention",
                claim_type=row["claim_type"],
                payout_amount=row["payout_amount"],
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
            from claim_agent.diary.recurrence import VALID_RECURRENCE_RULES, RECURRENCE_INTERVAL_DAYS
            if recurrence_rule not in VALID_RECURRENCE_RULES:
                raise ValueError(
                    f"Invalid recurrence_rule '{recurrence_rule}'. "
                    f"Must be one of: {', '.join(sorted(VALID_RECURRENCE_RULES))}"
                )
            if recurrence_rule == RECURRENCE_INTERVAL_DAYS:
                if recurrence_interval is None:
                    raise ValueError("recurrence_interval is required when recurrence_rule is 'interval_days'")
                if recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
            else:
                # daily/weekly: default interval to 1
                if recurrence_interval is None:
                    recurrence_interval = 1
                elif recurrence_interval < 1:
                    raise ValueError("recurrence_interval must be >= 1")
        doc_req_id = document_request_id
        if doc_req_id is None and document_type and task_type in ("request_documents", "obtain_police_report"):
            from claim_agent.db.document_repository import DocumentRepository
            doc_repo = DocumentRepository(db_path=self._db_path)
            doc_req_id = doc_repo.create_document_request(
                claim_id, document_type, requested_from=requested_from
            )
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            cursor = conn.execute(
                """
                INSERT INTO claim_tasks
                    (claim_id, title, task_type, description, status, priority, assigned_to, created_by, due_date, document_request_id, recurrence_rule, recurrence_interval, parent_task_id, auto_created_from)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id, title, task_type, description, priority, assigned_to, created_by, due_date,
                    doc_req_id, recurrence_rule, recurrence_interval, parent_task_id, auto_created_from,
                ),
            )
            task_id = cursor.lastrowid
            details = json.dumps({
                "task_id": task_id,
                "title": title,
                "task_type": task_type,
                "priority": priority,
                "assigned_to": assigned_to,
            })
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, AUDIT_EVENT_TASK_CREATED, details, created_by),
            )
        return int(task_id)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Fetch a single task by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM claim_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_tasks_for_claim(
        self,
        claim_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks for a claim with optional status filter. Returns (tasks, total)."""
        conditions = ["claim_id = ?"]
        params: list[Any] = [claim_id]
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM claim_tasks WHERE {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"""SELECT * FROM claim_tasks WHERE {where}
                    ORDER BY
                        CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

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
        conditions = [
            "due_date IS NOT NULL",
            "date(due_date) < date('now')",
            "status NOT IN ('completed', 'cancelled')",
        ]
        params: list[Any] = []
        if max_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) <= ?")
            params.append(max_escalation_level)
        if min_escalation_level is not None:
            conditions.append("COALESCE(escalation_level, 0) >= ?")
            params.append(min_escalation_level)
        where = " AND ".join(conditions)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM claim_tasks WHERE {where}
                ORDER BY due_date ASC
                LIMIT ?
                """,
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_task_overdue_notified(self, task_id: int) -> None:
        """Mark task as overdue notification sent (escalation_level=1)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE claim_tasks SET
                    escalation_level = 1,
                    escalation_notified_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (task_id,),
            )

    def mark_task_supervisor_escalated(self, task_id: int) -> None:
        """Mark task as escalated to supervisor (escalation_level=2)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE claim_tasks SET
                    escalation_level = 2,
                    escalation_escalated_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (task_id,),
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
                "SELECT * FROM claim_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Task not found: {task_id}")

            updates: list[str] = ["updated_at = datetime('now')"]
            params: list[Any] = []
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
                    updates.append(f"{field} = ?")
                    params.append(value)
                    changes[field] = value

            if not changes:
                return dict(row)

            params.append(task_id)
            conn.execute(
                f"UPDATE claim_tasks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            details = json.dumps({"task_id": task_id, **changes})
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (?, ?, ?, ?)
                """,
                (row["claim_id"], AUDIT_EVENT_TASK_UPDATED, details, actor_id),
            )
            updated = conn.execute(
                "SELECT * FROM claim_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(updated)

    def list_all_tasks(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        assigned_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List tasks across all claims with optional filters. Returns (tasks, total)."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("ct.status = ?")
            params.append(status)
        if task_type is not None:
            conditions.append("ct.task_type = ?")
            params.append(task_type)
        if assigned_to is not None:
            conditions.append("ct.assigned_to = ?")
            params.append(assigned_to)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection(self._db_path) as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM claim_tasks ct {where}",
                params,
            ).fetchone()
            total = count_row["cnt"]
            rows = conn.execute(
                f"""SELECT ct.* FROM claim_tasks ct {where}
                    ORDER BY
                        CASE ct.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                        CASE ct.status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
                        ct.created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def get_task_stats(self) -> dict[str, Any]:
        """Get aggregate task statistics."""
        with get_connection(self._db_path) as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM claim_tasks").fetchone()["cnt"]
            by_status = {
                r["status"]: r["cnt"]
                for r in conn.execute(
                    "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt FROM claim_tasks GROUP BY status"
                ).fetchall()
            }
            by_type = {
                r["task_type"]: r["cnt"]
                for r in conn.execute(
                    "SELECT COALESCE(task_type, 'unknown') as task_type, COUNT(*) as cnt FROM claim_tasks GROUP BY task_type"
                ).fetchall()
            }
            by_priority = {
                r["priority"]: r["cnt"]
                for r in conn.execute(
                    "SELECT COALESCE(priority, 'unknown') as priority, COUNT(*) as cnt FROM claim_tasks GROUP BY priority"
                ).fetchall()
            }
            overdue = conn.execute(
                "SELECT COUNT(*) as cnt FROM claim_tasks WHERE due_date IS NOT NULL AND date(due_date) < date('now') AND status NOT IN ('completed', 'cancelled')"
            ).fetchone()["cnt"]
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_priority": by_priority,
            "overdue": overdue,
        }
