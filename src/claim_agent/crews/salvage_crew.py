"""Salvage disposition crew: assess value, arrange disposition, transfer title, track auction."""

from claim_agent.agents.salvage import (
    create_auction_liaison_agent,
    create_salvage_coordinator_agent,
    create_title_specialist_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_salvage_crew(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the salvage crew for total-loss vehicle disposition."""
    return create_crew(
        agents_config=[
            AgentConfig(create_salvage_coordinator_agent),
            AgentConfig(create_title_specialist_agent),
            AgentConfig(create_auction_liaison_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT (includes settlement):
{workflow_output}

Assess salvage value for this total-loss vehicle. Use get_salvage_value with vin, vehicle_year, vehicle_make, vehicle_model from claim_data, damage_description from claim_data, and vehicle_value from claim_data or workflow_output when available.

Output the estimated salvage value, disposition_recommendation (auction, owner_retention, or scrap), and reasoning. Use generate_report if needed to document the assessment.""",
                expected_output="Salvage value estimate and disposition recommendation (auction, owner_retention, or scrap).",
                agent_index=0,
            ),
            TaskConfig(
                description="""Using the salvage assessment from the previous task:

CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Arrange disposition by initiating the title transfer. Use initiate_title_transfer with claim_id from claim_data, vin, vehicle_year, vehicle_make, vehicle_model, and disposition_type from the salvage coordinator's recommendation (auction, owner_retention, or scrap).
Then call record_dmv_salvage_report with claim_id and dmv_reference from the transfer result to persist salvage title tracking on the claim.

Output the transfer_id and dmv_reference. Use generate_report to document the title transfer initiation.""",
                expected_output="Title transfer initiated with transfer_id and DMV reference.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""Using the salvage assessment and title transfer context from previous tasks:

CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Confirm the title transfer was initiated and document DMV/salvage certificate status. Use generate_report with status='salvage_title_initiated' to capture the transfer confirmation and next steps for the policyholder or auction partner.""",
                expected_output="Title transfer confirmation and DMV/salvage certificate status documented.",
                agent_index=1,
                context_task_indices=[0, 1],
            ),
            TaskConfig(
                description="""Using the salvage and title context from previous tasks:

CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Record the salvage disposition outcome. Use record_salvage_disposition with claim_id from claim_data, disposition_type from the salvage assessment, salvage_amount if known (from workflow or assessment), status (pending, auction_scheduled, auction_complete, owner_retained, or scrapped), and notes summarizing the disposition.

Use generate_report to document the final salvage disposition status and any next steps for auction follow-up or recovery tracking.""",
                expected_output="Salvage disposition recorded with status and next steps documented.",
                agent_index=2,
                context_task_indices=[0, 1, 2],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state, "use_rag": use_rag},
    )
