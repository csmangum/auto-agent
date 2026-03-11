"""Follow-up crew for human-in-the-loop flows.

Handles structured outreach to claimants, policyholders, repair shops, and other
stakeholders. Flow: task intake -> message composition -> response handling.
Integrates with pending_info when adjuster requests more info.
"""

from claim_agent.agents.follow_up import (
    create_message_composer_agent,
    create_outreach_planner_agent,
    create_response_processor_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_follow_up_crew(llm: LLMProtocol | None = None):
    """Create the Follow-up crew: outreach planning -> message composition -> response processing.

    Handles tasks such as:
    - Gather photos from claimant (pending_info flow)
    - Request supplement from repair shop
    - Ask policyholder for clarification
    - Structured questions for SIU
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_outreach_planner_agent),
            AgentConfig(create_message_composer_agent),
            AgentConfig(create_response_processor_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

TASK:
{task}

PRIOR CONTEXT (claim notes, adjuster requests):
{claim_notes}

You are the Outreach Planner. Your job is to:
1. Identify which user type to contact: claimant, policyholder, repair_shop, siu, adjuster, or other.
2. Determine what information or action is needed.
3. Output a structured plan: user_type, message_summary, and key_points to include in the outreach.

Use get_claim_notes if claim_notes are not provided.""",
                expected_output=(
                    "Structured plan with user_type, message_summary, and key_points to include."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

TASK:
{task}

Using the outreach plan from the previous task, compose a professional, clear message tailored to the user type.
Then use send_user_message with claim_id, user_type, and message_content.
Include email or phone if available from claim context for claimant/policyholder.""",
                expected_output=(
                    "Confirmation that message was sent, including message_id from send_user_message."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

TASK:
{task}

USER RESPONSE (if provided):
{user_response}

Use check_pending_responses to see if there are pending follow-ups for this claim.
If a response has been provided above (user_response), use record_user_response with the
appropriate message_id to record it, then add_claim_note to capture key findings for downstream crews.
If no user_response is provided, output that we are waiting for the user to respond.
Determine next step: task_complete, need_more_info, escalate_to_human, or waiting_for_response.""",
                expected_output=(
                    "Processing summary: whether response was recorded, next_step, and any note added."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
