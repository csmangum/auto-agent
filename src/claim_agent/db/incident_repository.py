"""Incident and claim-link repository: CRUD for incidents and related claims."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.db.audit_events import ACTOR_SYSTEM
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.incident import IncidentInput, VehicleClaimInput

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

        The operation is made as atomic as possible: if any claim creation fails,
        the incident row and any already-created claims are removed before re-raising.
        """
        incident_id = _generate_incident_id()
        incident_date_str = incident_input.incident_date.isoformat()
        loss_state = incident_input.loss_state
        if loss_state is not None:
            loss_state = str(loss_state).strip() or None

        with get_connection(self._db_path) as conn:
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

        claim_ids: list[str] = []
        try:
            for vehicle in incident_input.vehicles:
                claim_input = self._vehicle_to_claim_input(
                    vehicle,
                    incident_input.incident_date,
                    incident_input.incident_description,
                    incident_input.loss_state,
                    incident_id,
                )
                claim_id = self._claim_repo.create_claim(claim_input, actor_id=actor_id)
                claim_ids.append(claim_id)

                # Link claims within same incident
                for other_id in claim_ids:
                    if other_id != claim_id:
                        self._create_link_internal(
                            claim_id, other_id, "same_incident", None, None
                        )
        except Exception:
            # Compensating cleanup: remove any created claims and the incident row
            self._rollback_incident(incident_id, claim_ids)
            raise

        return incident_id, claim_ids

    def _rollback_incident(self, incident_id: str, claim_ids: list[str]) -> None:
        """Remove incident and associated claims on partial failure (compensating cleanup).
        
        Note: Cannot delete claims with audit log entries due to foreign key constraints
        and append-only triggers. Instead, we mark them as failed and archived.
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
        a, b = (claim_id_a, claim_id_b) if claim_id_a <= claim_id_b else (claim_id_b, claim_id_a)
        try:
            with get_connection(self._db_path) as conn:
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
        except IntegrityError:
            return None

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
