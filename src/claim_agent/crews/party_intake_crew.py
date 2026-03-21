"""Crew for witness statement capture and attorney representation intake."""

from claim_agent.agents.party_intake import create_party_intake_agent
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_party_intake_crew(llm: LLMProtocol | None = None):
    """Witness intake then attorney intake; uses party_intake tools."""
    return create_crew(
        agents_config=[AgentConfig(create_party_intake_agent)],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

FOCUS / ADJUSTER INSTRUCTIONS:
{focus}

PRIOR NOTES:
{claim_notes}

You handle WITNESS INTAKE. Use get_claim_notes if needed.
1. Decide if witnesses should be recorded from the claim narrative or focus instructions.
2. For each witness, use record_witness_party with a clear role (eyewitness, passenger, other).
3. If a statement text is provided in focus instructions, use record_witness_statement with the correct witness_party_id.
4. If follow-up is needed, create_claim_task with task_type=contact_witness.
5. Optionally send_user_message with user_type=witness when email/phone exist on the witness row (from claim_data parties).

Output a concise summary of witness party_ids and actions taken.""",
                expected_output="Summary of witness parties and statements/tasks created.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

FOCUS / ADJUSTER INSTRUCTIONS:
{focus}

PRIOR NOTES:
{claim_notes}

You handle ATTORNEY INTAKE. Use get_claim_notes if needed.
1. If representation / LOP is indicated, use record_attorney_representation when you have attorney name (and contact if available).
2. If LOP document must be collected, use create_document_request with appropriate document_type and requested_from.
3. If outreach to counsel is appropriate and contact exists, send_user_message with user_type=attorney.

Output a concise summary of attorney linkage, document requests, and messages.""",
                expected_output="Summary of attorney representation and related actions.",
                agent_index=0,
                context_task_indices=[0],
            ),
        ],
        llm=llm,
    )
