"""Shared settlement workflow crew."""

from claim_agent.agents.settlement import (
    create_payment_distribution_agent,
    create_settlement_closure_agent,
    create_settlement_documentation_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_settlement_crew(
    llm: LLMProtocol | None = None,
    state: str = "California",
    claim_type: str | None = None,
    use_rag: bool = True,
):
    """Create the shared settlement crew for payout-ready claims."""
    return create_crew(
        agents_config=[
            AgentConfig(create_settlement_documentation_agent),
            AgentConfig(create_payment_distribution_agent),
            AgentConfig(create_settlement_closure_agent),
        ],
        tasks_config=[
            TaskConfig(
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
- bodily_injury: include medical records summary, injury severity, pain/suffering component, and BI settlement breakdown

Output a structured settlement documentation summary and release agreement notes.""",
                expected_output="Settlement report summary with claim-type-specific documentation and release notes.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Using the settlement documentation context, produce a payment distribution plan.
Document who gets paid, how much they receive, and in what order.

Use calculate_payout only as a verification tool when the claim_type is total_loss.
For partial_loss, derive payment recipients from the repair estimate and authorization context,
including insured, lienholder, and repair shop when applicable.

Use record_claim_payment to persist each planned disbursement to the claim_payments ledger
(one row per payee/amount; use payee_secondary for two-party checks). Use a distinct external_ref
per intended payment if you need idempotency (e.g. settlement_shop_1).

Use generate_report if needed to capture the payment breakdown section.""",
                expected_output="Payment distribution table with recipients, amounts, and ordering rationale.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Finalize settlement using the documentation and payment distribution context.
Use generate_report with claim_id, claim_type, status='settled', summary covering the completed workflow
and settlement steps, and payout_amount from claim_data when present; otherwise from workflow output.

If record_claim_payment was not used in the prior task but the distribution plan lists multiple payees,
record any missing ledger rows now before closing.

Document final status as settled, include next_steps for subrogation, salvage, or regulatory follow-up,
and confirm the claim is ready for closure.""",
                expected_output="Final settlement report with status settled and documented next steps.",
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state, "claim_type": claim_type, "use_rag": use_rag},
    )
