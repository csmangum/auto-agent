"""Shared settlement workflow crew."""

from crewai import Crew, Task

from claim_agent.agents.settlement import (
    create_payment_distribution_agent,
    create_settlement_closure_agent,
    create_settlement_documentation_agent,
)
from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_crew_verbose


def create_settlement_crew(
    llm=None,
    state: str = "California",
    claim_type: str | None = None,
    use_rag: bool = True,
):
    """Create the shared settlement crew for payout-ready claims."""
    llm = llm or get_llm()

    documentation_agent = create_settlement_documentation_agent(
        llm,
        state=state,
        claim_type=claim_type,
        use_rag=use_rag,
    )
    payment_agent = create_payment_distribution_agent(
        llm,
        state=state,
        claim_type=claim_type,
        use_rag=use_rag,
    )
    closure_agent = create_settlement_closure_agent(
        llm,
        state=state,
        claim_type=claim_type,
        use_rag=use_rag,
    )

    documentation_task = Task(
        description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Generate the settlement documentation for this payout-ready claim.
Use generate_report with claim_id from claim_data (or generate one with generate_claim_id if missing),
claim_type from claim_data, status='settlement_documented', a concise summary of the workflow outputs,
and payout_amount from claim_data when present; otherwise extract from the workflow output.

Claim-type-specific requirements:
- total_loss: include valuation summary, ACV, deductible, and salvage/owner-retention considerations
- partial_loss: include repair estimate, assigned shop, authorization reference, and insurance payment summary

Output a structured settlement documentation summary and release agreement notes.""",
        expected_output="Settlement report summary with claim-type-specific documentation and release notes.",
        agent=documentation_agent,
    )

    payment_task = Task(
        description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Using the settlement documentation context, produce a payment distribution plan.
Document who gets paid, how much they receive, and in what order.

Use calculate_payout only as a verification tool when the claim_type is total_loss.
For partial_loss, derive payment recipients from the repair estimate and authorization context,
including insured, lienholder, and repair shop when applicable.

Use generate_report if needed to capture the payment breakdown section.""",
        expected_output="Payment distribution table with recipients, amounts, and ordering rationale.",
        agent=payment_agent,
        context=[documentation_task],
    )

    closure_task = Task(
        description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Finalize settlement using the documentation and payment distribution context.
Use generate_report with claim_id, claim_type, status='settled', summary covering the completed workflow
and settlement steps, and payout_amount from claim_data when present; otherwise from workflow output.

Document final status as settled, include next_steps for subrogation, salvage, or regulatory follow-up,
and confirm the claim is ready for closure.""",
        expected_output="Final settlement report with status settled and documented next steps.",
        agent=closure_agent,
        context=[documentation_task, payment_task],
    )

    return Crew(
        agents=[documentation_agent, payment_agent, closure_agent],
        tasks=[documentation_task, payment_task, closure_task],
        verbose=get_crew_verbose(),
    )
