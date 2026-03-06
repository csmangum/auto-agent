"""Claim repository: CRUD, audit logging, and search.

This repository treats claim_audit_log as append-only: it only inserts new
audit entries and does not perform UPDATE or DELETE operations on that table.
"""

import json
import uuid
from typing import Any

from claim_agent.models.claim import Attachment

from claim_agent.db.audit_events import (
    ACTOR_WORKFLOW,
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
)
from claim_agent.db.constants import STATUS_PENDING
from claim_agent.db.database import get_connection
from claim_agent.models.claim import ClaimInput


def _generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


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
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, status, attachments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    STATUS_PENDING,
                    attachments_json,
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
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Update status, optionally claim_type and payout_amount; log state change to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_type, payout_amount FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Claim not found: {claim_id}")
            old_status = row["status"]
            old_claim_type = row["claim_type"]
            old_payout = row["payout_amount"]

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

    def update_claim_attachments(
        self,
        claim_id: str,
        attachments: list[Attachment],
    ) -> None:
        """Update attachments for a claim (e.g. after file upload)."""
        attachments_json = json.dumps(
            [a.model_dump(mode="json") for a in attachments],
            default=str,
        )
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE claims SET attachments = ?, updated_at = datetime('now') WHERE id = ?",
                (attachments_json, claim_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Claim not found: {claim_id}")

    def get_claim_history(self, claim_id: str) -> list[dict[str, Any]]:
        """Get audit log entries for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, claim_id, action, old_status, new_status, details,
                       actor_id, before_state, after_state, created_at
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
