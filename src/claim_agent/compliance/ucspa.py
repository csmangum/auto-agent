"""UCSPA (Unfair Claims Settlement Practices Act) compliance.

Implements NAIC Model Unfair Claims Settlement Practices Act requirements:
- Acknowledgment deadlines (must acknowledge receipt within X days)
- Investigation completion deadlines
- Payment deadlines: stored ``payment_due`` on the claim is FNOL-based until the
  claim first reaches ``settled``; :func:`get_ucspa_deadlines` reflects that at
  FNOL. On first transition to settled, ``ClaimRepository.update_claim_status``
  sets ``settlement_agreed_at`` and recomputes ``payment_due`` via
  :func:`payment_due_iso_after_settlement_moment` (state prompt-payment days
  from the settlement instant's UTC calendar date).
- Denial explanation requirements (written, specific, with appeal rights)
- Communication response deadlines

State-specific deadlines are sourced from state_rules.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from claim_agent.compliance.state_rules import get_compliance_due_date

logger = logging.getLogger(__name__)


def get_ucspa_deadlines(
    base_date: date,
    state: str | None,
) -> dict[str, str | None]:
    """Return UCSPA deadline dates for a claim.

    All deadlines are computed from ``base_date`` (the FNOL/claim-receipt
    date). ``payment_due`` is an FNOL-based SLA until the claim first reaches
    ``settled``; ``ClaimRepository.update_claim_status`` then sets
    ``settlement_agreed_at`` and recomputes ``payment_due`` using
    ``payment_due_iso_after_settlement_moment``.

    Args:
        base_date: Reference date (claim receipt / FNOL date).
        state: Loss state/jurisdiction.

    Returns:
        Dict with acknowledgment_due, investigation_due, payment_due (ISO date strings).
    """
    ack = get_compliance_due_date(base_date, "acknowledgment", state)
    inv = get_compliance_due_date(base_date, "investigation", state)
    pay = get_compliance_due_date(base_date, "prompt_payment", state)
    return {
        "acknowledgment_due": ack.isoformat() if ack else None,
        "investigation_due": inv.isoformat() if inv else None,
        "payment_due": pay.isoformat() if pay else None,
    }


def payment_due_iso_after_settlement_moment(
    settlement_timestamp_iso: str,
    loss_state: str | None,
) -> str | None:
    """ISO date (YYYY-MM-DD) for prompt-payment deadline from settlement agreement time.

    Uses the UTC calendar date of ``settlement_timestamp_iso`` as day zero, then adds
    state-specific ``prompt_payment`` days (see :func:`get_compliance_due_date`).
    """
    raw = (settlement_timestamp_iso or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    base_date = dt.astimezone(timezone.utc).date()
    due = get_compliance_due_date(base_date, "prompt_payment", loss_state)
    return due.isoformat() if due else None


def create_ucspa_compliance_tasks(
    repo: "ClaimRepository",
    claim_id: str,
    loss_state: str | None,
    base_date: date | None = None,
) -> int:
    """Create UCSPA compliance tasks at FNOL (First Notice of Loss).

    Creates state-specific claim_tasks for acknowledgment, investigation,
    and prompt payment deadlines. Returns count of tasks created.

    Args:
        repo: ClaimRepository instance.
        claim_id: Claim ID.
        loss_state: Loss state for jurisdiction.
        base_date: Reference date (default: today).

    Returns:
        Number of tasks created.
    """
    from claim_agent.diary.templates import get_compliance_deadline_templates

    base = base_date or date.today()
    templates = get_compliance_deadline_templates(loss_state)
    created = 0

    for t in templates:
        due_date = get_compliance_due_date(base, t.deadline_type, loss_state)
        if due_date is None:
            continue
        due_str = due_date.isoformat()
        try:
            repo.create_task(
                claim_id,
                t.title,
                t.task_type,
                description=t.description,
                priority="high" if t.deadline_type == "acknowledgment" else "medium",
                created_by="ucspa_system",
                due_date=due_str,
                auto_created_from=f"ucspa:{t.deadline_type}",
            )
            created += 1
            logger.info(
                "ucspa_task_created claim_id=%s deadline_type=%s due=%s",
                claim_id,
                t.deadline_type,
                due_str,
            )
        except Exception as e:
            logger.warning(
                "ucspa_task_create_failed claim_id=%s deadline_type=%s: %s",
                claim_id,
                t.deadline_type,
                e,
            )

    return created


def claims_with_deadlines_approaching(
    repo: "ClaimRepository",
    days_ahead: int = 3,
) -> list[dict]:
    """Return claims with UCSPA deadlines in the next N days.

    Used for deadline-approaching alerts. Checks acknowledgment_due,
    investigation_due, payment_due on claims.

    Args:
        repo: ClaimRepository instance.
        days_ahead: days from today to look ahead.

    Returns:
        List of dicts with claim_id, deadline_type, due_date, loss_state.
    """
    from sqlalchemy import text

    from claim_agent.db.database import get_connection, row_to_dict

    today = date.today()
    cutoff = (today + timedelta(days=days_ahead)).isoformat()

    results: list[dict] = []
    db_path = getattr(repo, "_db_path", None)
    with get_connection(db_path) as conn:
        for col, deadline_type in [
            ("acknowledgment_due", "acknowledgment"),
            ("investigation_due", "investigation"),
            ("payment_due", "prompt_payment"),
        ]:
            try:
                cursor = conn.execute(
                    text(f"""
                    SELECT id, loss_state, {col} as due_date
                    FROM claims
                    WHERE {col} IS NOT NULL
                      AND {col} >= :today
                      AND {col} <= :cutoff
                      AND status NOT IN ('closed', 'denied', 'duplicate', 'archived', 'purged')
                    """),
                    {"today": today.isoformat(), "cutoff": cutoff},
                )
                for row in cursor:
                    d = row_to_dict(row)
                    if d.get("due_date"):
                        due_date_val = d["due_date"]
                        if hasattr(due_date_val, "isoformat"):
                            due_date_str = due_date_val.isoformat()
                        else:
                            due_date_str = str(due_date_val)
                        results.append(
                            {
                                "claim_id": d["id"],
                                "deadline_type": deadline_type,
                                "due_date": due_date_str,
                                "loss_state": d.get("loss_state"),
                            }
                        )
            except Exception as e:
                # Columns may not exist if migration 026 not applied
                logger.debug("ucspa_deadline_query_failed col=%s: %s", col, e)

    return results


if TYPE_CHECKING:
    from claim_agent.db.repository import ClaimRepository
