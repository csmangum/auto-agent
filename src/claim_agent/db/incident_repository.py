"""Incident and claim-link repository: CRUD for incidents and related claims."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from claim_agent.db.audit_events import ACTOR_SYSTEM
from claim_agent.db.constants import STATUS_PENDING
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.db.repository import ClaimRepository, _apply_ucspa_at_fnol
from claim_agent.events import ClaimEvent, emit_claim_event
from claim_agent.models.claim import ClaimInput
from claim_agent.models.incident import IncidentInput, VehicleClaimInput


def _is_unique_constraint_violation(exc: IntegrityError) -> bool:
    """True if the IntegrityError is from a unique constraint (duplicate), not FK/NOT NULL etc."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    # PostgreSQL: pgcode 23505 = unique_violation
    if hasattr(orig, "pgcode") and orig.pgcode == "23505":
        return True
    # SQLite: message contains "UNIQUE constraint failed"
    msg = str(orig).lower()
    return "unique constraint failed" in msg or "unique constraint" in msg


logger = logging.getLogger(__name__)


def _generate_incident_id(prefix: str = "INC") -> str:
    """Generate a unique incident ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class IncidentRepository:
    """Repository for incident and claim-link persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._claim_repo = ClaimRepository(db_path)

    def create_incident(
        self,
        incident_input: IncidentInput,
        *,
        actor_id: str = ACTOR_SYSTEM,
    ) -> tuple[str, list[str]]:
        """Create incident and one claim per vehicle. Returns (incident_id, claim_ids).

        All database writes (incident insert, claim inserts including audit log,
        initial reserve, and party inserts, and claim links) execute inside a
        **single transaction**.  If any step raises an exception the entire
        transaction is rolled back automatically, leaving no partial state.

        External I/O (policy adapter look-ups) is performed **before** the
        transaction opens so it does not hold the database lock during network
        calls.  UCSPA deadline setting and claim-submitted events run **after**
        the transaction commits.  Missing UCSPA schema columns are tolerated
        (warning only); other UCSPA failures propagate like :meth:`ClaimRepository.create_claim`.
        """
        incident_id = _generate_incident_id()
        incident_date_str = incident_input.incident_date.isoformat()
        loss_state = incident_input.loss_state
        if loss_state is not None:
            loss_state = str(loss_state).strip() or None

        # Pre-fetch policies before opening the transaction (external I/O).
        vehicle_policies = self._prefetch_vehicle_policies(incident_input.vehicles)

        # Accumulate (claim_id, effective_loss_state) for post-transaction work.
        claim_details: list[tuple[str, str | None]] = []
        claim_ids: list[str] = []

        with get_connection(self._db_path) as conn:
            # 1. Insert the incident row.
            conn.execute(
                text("""
                INSERT INTO incidents (id, incident_date, incident_description, loss_state)
                VALUES (:id, :incident_date, :description, :loss_state)
                """),
                {
                    "id": incident_id,
                    "incident_date": incident_date_str,
                    "description": incident_input.incident_description,
                    "loss_state": loss_state,
                },
            )

            # 2. Create one claim per vehicle, then link to all previous claims.
            for vehicle, policy in zip(incident_input.vehicles, vehicle_policies):
                claim_input = self._vehicle_to_claim_input(
                    vehicle,
                    incident_input.incident_date,
                    incident_input.incident_description,
                    incident_input.loss_state,
                    incident_id,
                )
                claim_id = self._claim_repo.create_claim_in_transaction(
                    conn, claim_input, actor_id=actor_id, policy=policy
                )
                # Link this claim to every previously created claim in the same incident.
                for other_id in claim_ids:
                    self._create_link_in_conn(conn, claim_id, other_id, "same_incident", None, None)
                claim_ids.append(claim_id)

                effective_loss = ClaimRepository._normalize_loss_state(claim_input.loss_state)
                claim_details.append((claim_id, effective_loss))

            # All writes committed atomically on successful context exit.

        # Post-transaction: apply UCSPA deadlines and emit events (best-effort).
        for claim_id, effective_loss in claim_details:
            try:
                _apply_ucspa_at_fnol(self._claim_repo, claim_id, effective_loss)
            except (OperationalError, ProgrammingError) as e:
                logger.warning(
                    "ucspa_at_fnol_failed claim_id=%s: %s (run alembic upgrade head if UCSPA columns missing)",
                    claim_id,
                    e,
                )
            except Exception:
                logger.exception("ucspa_at_fnol_unexpected_error claim_id=%s", claim_id)
                raise
            emit_claim_event(
                ClaimEvent(claim_id=claim_id, status=STATUS_PENDING, summary="Claim submitted")
            )

        return incident_id, claim_ids

    def _prefetch_vehicle_policies(
        self, vehicles: list[VehicleClaimInput]
    ) -> list[dict[str, Any] | None]:
        """Pre-fetch policy data for each vehicle before opening a transaction.

        This performs external I/O (policy adapter) outside the transaction so
        the database lock is not held during network calls.  Returns a list
        parallel to *vehicles* where each element is the fetched policy dict or
        ``None`` when the intake already includes a policyholder party or when
        the adapter call fails.
        """
        from claim_agent.adapters.registry import get_policy_adapter

        results: list[dict[str, Any] | None] = []
        for vehicle in vehicles:
            intake_has_policyholder = any(
                getattr(p, "party_type", None) == "policyholder"
                for p in (vehicle.parties or [])
            )
            if intake_has_policyholder:
                results.append(None)
                continue
            try:
                results.append(get_policy_adapter().get_policy(vehicle.policy_number))
            except Exception:
                logger.debug(
                    "fnol_policy_lookup_failed policy_number=%s",
                    vehicle.policy_number,
                    exc_info=True,
                )
                results.append(None)
        return results

    def _rollback_incident(self, incident_id: str, claim_ids: list[str]) -> None:
        """Remove incident and associated claims on partial failure (compensating cleanup).

        .. deprecated::
            :meth:`create_incident` now uses a single database transaction, so
            this method is no longer called for incident creation failures.
            It is retained for callers that may have used it directly.

        Note: Cannot delete claims with audit log entries due to foreign key
        constraints and append-only triggers.  Instead, marks them as failed
        and archived.
        """
        try:
            with get_connection(self._db_path) as conn:
                for claim_id in claim_ids:
                    conn.execute(
                        text("DELETE FROM claim_links WHERE claim_id_a = :cid OR claim_id_b = :cid"),
                        {"cid": claim_id},
                    )
                    conn.execute(
                        text("UPDATE claims SET status = 'failed', archived_at = :now, incident_id = NULL WHERE id = :cid"),
                        {"cid": claim_id, "now": datetime.now(timezone.utc).isoformat()},
                    )
                conn.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
        except Exception:
            logger.exception(
                "Failed to fully roll back incident %s (claims: %s); database may be inconsistent",
                incident_id,
                claim_ids,
            )

    def _vehicle_to_claim_input(
        self,
        vehicle: VehicleClaimInput,
        incident_date: Any,
        incident_description: str,
        loss_state: str | None,
        incident_id: str,
    ) -> ClaimInput:
        """Convert VehicleClaimInput to ClaimInput with incident context."""
        return ClaimInput(
            policy_number=vehicle.policy_number,
            vin=vehicle.vin,
            vehicle_year=vehicle.vehicle_year,
            vehicle_make=vehicle.vehicle_make,
            vehicle_model=vehicle.vehicle_model,
            incident_date=incident_date,
            incident_description=incident_description,
            damage_description=vehicle.damage_description,
            estimated_damage=vehicle.estimated_damage,
            attachments=vehicle.attachments,
            loss_state=vehicle.loss_state or loss_state,
            parties=vehicle.parties,
            incident_id=incident_id,
        )

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        """Fetch incident by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM incidents WHERE id = :id"),
                {"id": incident_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_claims_by_incident(self, incident_id: str) -> list[dict[str, Any]]:
        """Fetch all claims linked to an incident."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("SELECT * FROM claims WHERE incident_id = :id ORDER BY created_at ASC"),
                {"id": incident_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def create_claim_link(
        self,
        claim_id_a: str,
        claim_id_b: str,
        link_type: str,
        *,
        opposing_carrier: str | None = None,
        notes: str | None = None,
    ) -> int | None:
        """Create a link between two claims. Returns link id, or None if duplicate. Normalizes order for uniqueness."""
        return self._create_link_internal(
            claim_id_a, claim_id_b, link_type, opposing_carrier, notes
        )

    def _create_link_internal(
        self,
        claim_id_a: str,
        claim_id_b: str,
        link_type: str,
        opposing_carrier: str | None,
        notes: str | None,
    ) -> int | None:
        """Create claim link. Ensures canonical order (a < b) for uniqueness.

        Returns the new link's ID, or None if the link already exists.
        """
        with get_connection(self._db_path) as conn:
            return self._create_link_in_conn(
                conn, claim_id_a, claim_id_b, link_type, opposing_carrier, notes
            )

    def _create_link_in_conn(
        self,
        conn: Any,
        claim_id_a: str,
        claim_id_b: str,
        link_type: str,
        opposing_carrier: str | None,
        notes: str | None,
    ) -> int | None:
        """Create claim link using an existing connection. Does not commit.

        Ensures canonical order (a < b) for uniqueness.  Returns the new
        link's ID, or ``None`` if the link already exists.
        """
        a, b = (claim_id_a, claim_id_b) if claim_id_a <= claim_id_b else (claim_id_b, claim_id_a)
        try:
            with conn.begin_nested():
                result = conn.execute(
                    text("""
                    INSERT INTO claim_links
                        (claim_id_a, claim_id_b, link_type, opposing_carrier, notes)
                    VALUES (:a, :b, :link_type, :opposing_carrier, :notes)
                    RETURNING id
                    """),
                    {"a": a, "b": b, "link_type": link_type, "opposing_carrier": opposing_carrier, "notes": notes},
                )
                row = result.fetchone()
                return int(row[0]) if row else None
        except IntegrityError as e:
            if _is_unique_constraint_violation(e):
                return None  # Duplicate link
            raise

    def get_claim_links(
        self,
        claim_id: str,
        *,
        link_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all links for a claim (as claim_id_a or claim_id_b)."""
        with get_connection(self._db_path) as conn:
            if link_type:
                rows = conn.execute(
                    text("""
                    SELECT * FROM claim_links
                    WHERE (claim_id_a = :cid OR claim_id_b = :cid) AND link_type = :link_type
                    ORDER BY created_at DESC
                    """),
                    {"cid": claim_id, "link_type": link_type},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("""
                    SELECT * FROM claim_links
                    WHERE claim_id_a = :cid OR claim_id_b = :cid
                    ORDER BY created_at DESC
                    """),
                    {"cid": claim_id},
                ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_related_claims(
        self,
        claim_id: str,
        *,
        link_type: str | None = None,
    ) -> list[str]:
        """Return claim IDs related to the given claim (excluding the claim itself)."""
        links = self.get_claim_links(claim_id, link_type=link_type)
        related: set[str] = set()
        for link in links:
            a, b = link.get("claim_id_a"), link.get("claim_id_b")
            if a and a != claim_id:
                related.add(a)
            if b and b != claim_id:
                related.add(b)
        return sorted(related)
