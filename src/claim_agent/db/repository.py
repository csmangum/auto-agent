"""Claim repository: CRUD, audit logging, and search."""

import uuid
from typing import Any

from claim_agent.db.constants import (
    STATUS_FAILED,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from claim_agent.db.database import get_connection
from claim_agent.models.claim import ClaimInput


def _generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class ClaimRepository:
    """Repository for claim persistence and audit logging."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def create_claim(self, claim_input: ClaimInput) -> str:
        """Insert new claim, generate ID, log 'created' audit entry. Returns claim_id."""
        claim_id = _generate_claim_id()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    claim_input.policy_number,
                    claim_input.vin,
                    claim_input.vehicle_year,
                    claim_input.vehicle_make,
                    claim_input.vehicle_model,
                    claim_input.incident_date,
                    claim_input.incident_description,
                    claim_input.damage_description,
                    claim_input.estimated_damage,
                    None,
                    STATUS_PENDING,
                ),
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, new_status, details)
                VALUES (?, 'created', ?, ?)
                """,
                (claim_id, STATUS_PENDING, "Claim record created"),
            )
        return claim_id

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
    ) -> None:
        """Update status, optionally claim_type and payout_amount; log state change to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            updates = ["status = ?", "updated_at = datetime('now')"]
            params: list[Any] = [new_status]
            if claim_type is not None:
                updates.append("claim_type = ?")
                params.append(claim_type)
            if payout_amount is not None:
                updates.append("payout_amount = ?")
                params.append(payout_amount)
            params.append(claim_id)
            conn.execute(
                f"UPDATE claims SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.execute(
                """
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details)
                VALUES (?, 'status_changed', ?, ?, ?)
                """,
                (claim_id, old_status, new_status, details or ""),
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

    def get_claim_history(self, claim_id: str) -> list[dict[str, Any]]:
        """Get audit log entries for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, claim_id, action, old_status, new_status, details, created_at
                FROM claim_audit_log
                WHERE claim_id = ?
                ORDER BY id ASC
                """,
                (claim_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_claims(
        self,
        vin: str | None = None,
        incident_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claims by VIN and/or incident_date. Both optional; if both None, returns []."""
        vin = None if vin is None else str(vin).strip()
        incident_date = None if incident_date is None else str(incident_date).strip()
        if not vin and not incident_date:
            return []
        with get_connection(self._db_path) as conn:
            if vin and incident_date:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE vin = ? AND incident_date = ?",
                    (vin, incident_date),
                ).fetchall()
            elif vin:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE vin = ?", (vin,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE incident_date = ?",
                    (incident_date,),
                ).fetchall()
        return [dict(r) for r in rows]
