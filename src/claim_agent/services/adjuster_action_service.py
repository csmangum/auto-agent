"""Adjuster workflow actions: assign, approve, reject, request_info, escalate_to_siu."""

from claim_agent.db.repository import ClaimRepository


class AdjusterActionService:
    """Domain service for adjuster workflow actions on claims in the review queue."""

    def __init__(self, repo: ClaimRepository) -> None:
        self._repo = repo

    def assign(
        self,
        claim_id: str,
        assignee_id: str,
        *,
        actor_id: str,
    ) -> None:
        """Assign claim to an adjuster. Only claims with status needs_review can be assigned."""
        self._repo.assign_claim(claim_id, assignee_id, actor_id=actor_id)

    def approve(
        self,
        claim_id: str,
        *,
        actor_id: str,
    ) -> None:
        """Approve claim for continued processing. Caller must invoke run_claim_workflow."""
        self._repo.perform_adjuster_action(claim_id, "approve", actor_id=actor_id)

    def reject(
        self,
        claim_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> None:
        """Reject claim with optional reason."""
        self._repo.perform_adjuster_action(
            claim_id, "reject", actor_id=actor_id, reason=reason
        )

    def request_info(
        self,
        claim_id: str,
        *,
        actor_id: str,
        note: str | None = None,
    ) -> None:
        """Request more information from claimant."""
        self._repo.perform_adjuster_action(
            claim_id, "request_info", actor_id=actor_id, note=note
        )

    def escalate_to_siu(
        self,
        claim_id: str,
        *,
        actor_id: str,
    ) -> None:
        """Escalate claim to Special Investigations Unit."""
        self._repo.perform_adjuster_action(claim_id, "escalate_to_siu", actor_id=actor_id)
