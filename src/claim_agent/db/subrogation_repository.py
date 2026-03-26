"""Subrogation repository: CRUD for subrogation_cases table."""

from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import DomainValidationError


class SubrogationRepository:
    """Repository for subrogation case persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

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
