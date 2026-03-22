"""Diary templates: state-specific compliance deadlines and status-transition entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from claim_agent.compliance.state_rules import get_state_rules


@dataclass
class ComplianceDeadlineTemplate:
    """Template for a state-specific compliance deadline task."""

    deadline_type: str  # acknowledgment, investigation, prompt_payment
    title: str
    task_type: str
    description: str
    days: int
    state: str


def get_compliance_deadline_templates(
    state: str | None,
) -> list[ComplianceDeadlineTemplate]:
    """Return state-specific compliance deadline templates for diary creation.

    Args:
        state: Loss state (California, Texas, etc.). Uses defaults if None.

    Returns:
        List of templates with title, task_type, description, days, state.
    """
    rules = get_state_rules(state) if state else None
    templates: list[ComplianceDeadlineTemplate] = []

    if rules:
        templates.extend([
            ComplianceDeadlineTemplate(
                deadline_type="acknowledgment",
                title=f"Acknowledge claim receipt ({rules.state})",
                task_type="follow_up_claimant",
                description=f"State requires claim acknowledgment within {rules.acknowledgment_days} days.",
                days=rules.acknowledgment_days,
                state=rules.state,
            ),
            ComplianceDeadlineTemplate(
                deadline_type="investigation",
                title=f"Complete investigation ({rules.state})",
                task_type="review_documents",
                description=f"State requires investigation complete within {rules.investigation_days} days.",
                days=rules.investigation_days,
                state=rules.state,
            ),
            ComplianceDeadlineTemplate(
                deadline_type="prompt_payment",
                title=f"Prompt payment deadline ({rules.state})",
                task_type="other",
                description=f"State requires payment within {rules.prompt_payment_days} days of acceptance.",
                days=rules.prompt_payment_days,
                state=rules.state,
            ),
        ])
    else:
        templates.extend([
            ComplianceDeadlineTemplate(
                deadline_type="acknowledgment",
                title="Acknowledge claim receipt",
                task_type="follow_up_claimant",
                description="Acknowledge claim within 15 days (default).",
                days=15,
                state="",
            ),
            ComplianceDeadlineTemplate(
                deadline_type="investigation",
                title="Complete investigation",
                task_type="review_documents",
                description="Complete investigation within 40 days (default).",
                days=40,
                state="",
            ),
            ComplianceDeadlineTemplate(
                deadline_type="prompt_payment",
                title="Prompt payment deadline",
                task_type="other",
                description="Pay within 30 days of acceptance (default).",
                days=30,
                state="",
            ),
        ])

    return templates


@dataclass
class StatusTransitionTemplate:
    """Template for auto-created diary entry at status transition."""

    from_status: str
    to_status: str
    title: str
    task_type: str
    description: str
    due_days: int  # days from transition date
    recurrence_rule: Optional[str] = None
    recurrence_interval: Optional[int] = None


# Key status transitions that should auto-create diary entries
STATUS_TRANSITION_TEMPLATES: list[StatusTransitionTemplate] = [
    StatusTransitionTemplate(
        from_status="pending",
        to_status="processing",
        title="Follow up on claim processing",
        task_type="follow_up_claimant",
        description="Check claim processing status and any pending items.",
        due_days=3,
        recurrence_rule="interval_days",
        recurrence_interval=3,
    ),
    StatusTransitionTemplate(
        from_status="pending",
        to_status="open",
        title="Review open claim",
        task_type="review_documents",
        description="Review claim documents and next steps.",
        due_days=2,
    ),
    StatusTransitionTemplate(
        from_status="processing",
        to_status="open",
        title="Follow up on opened claim",
        task_type="follow_up_claimant",
        description="Verify claimant has been contacted and documents received.",
        due_days=5,
    ),
    StatusTransitionTemplate(
        from_status="processing",
        to_status="under_investigation",
        title="Start investigation workflow",
        task_type="review_documents",
        description="Assign investigator and gather required evidence.",
        due_days=1,
    ),
    StatusTransitionTemplate(
        from_status="open",
        to_status="settled",
        title="Verify settlement and payment",
        task_type="other",
        description="Confirm payment issued and claimant notified.",
        due_days=1,
    ),
    StatusTransitionTemplate(
        from_status="open",
        to_status="disputed",
        title="Prepare dispute response",
        task_type="review_documents",
        description="Review dispute details and prepare response package.",
        due_days=1,
    ),
    StatusTransitionTemplate(
        from_status="needs_review",
        to_status="processing",
        title="Resume processing after review",
        task_type="review_documents",
        description="Complete any items from review and continue processing.",
        due_days=2,
    ),
    StatusTransitionTemplate(
        from_status="needs_review",
        to_status="under_investigation",
        title="Escalate reviewed claim to investigation",
        task_type="review_documents",
        description="Escalate reviewed findings to investigation handling.",
        due_days=1,
    ),
    StatusTransitionTemplate(
        from_status="open",
        to_status="needs_review",
        title="Address review items",
        task_type="review_documents",
        description="Address items flagged in human review.",
        due_days=3,
    ),
    StatusTransitionTemplate(
        from_status="settled",
        to_status="closed",
        title="Finalize claim closure",
        task_type="other",
        description="Confirm all settlement obligations are complete before closure.",
        due_days=1,
    ),
]


def get_status_transition_templates(
    from_status: str,
    to_status: str,
) -> list[StatusTransitionTemplate]:
    """Return templates for diary entries to create at a status transition."""
    return [
        t
        for t in STATUS_TRANSITION_TEMPLATES
        if t.from_status == from_status and t.to_status == to_status
    ]
