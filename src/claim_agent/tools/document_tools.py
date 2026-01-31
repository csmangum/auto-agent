"""Document and report generation tools."""

from crewai.tools import tool

from claim_agent.tools.logic import generate_report_impl, generate_claim_id_impl


@tool("Generate Claim Report")
def generate_report(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    """Generate a claim report/summary document.
    Args:
        claim_id: Assigned claim ID.
        claim_type: new, duplicate, or total_loss.
        status: Claim status (e.g., open, closed, duplicate).
        summary: Human-readable summary of actions and outcome.
        payout_amount: Optional settlement amount for total loss.
    Returns:
        JSON string with report_id, claim_id, status, summary, payout_amount.
    """
    return generate_report_impl(claim_id, claim_type, status, summary, payout_amount)


@tool("Generate Claim ID")
def generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID. Use prefix CLM for new claims.
    Args:
        prefix: Optional prefix (default CLM).
    Returns:
        Unique claim ID string.
    """
    return generate_claim_id_impl(prefix)
