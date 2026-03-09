"""Rental reimbursement workflow crew for loss-of-use coverage."""

from claim_agent.agents.rental import (
    create_rental_coordinator_agent,
    create_rental_eligibility_specialist_agent,
    create_rental_reimbursement_processor_agent,
)
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_rental_crew(llm=None):
    """Create the Rental Reimbursement crew: eligibility -> arrange/approve -> process reimbursement.

    This crew handles loss-of-use (rental) coverage for partial loss claims:
    1. Check policy for rental coverage and limits (RCC-001 to RCC-004, CCR 2695.7(l))
    2. Arrange/approve rental within limits; ensure comparable vehicle class
    3. Process reimbursement for the approved rental
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_rental_eligibility_specialist_agent),
            AgentConfig(create_rental_coordinator_agent),
            AgentConfig(create_rental_reimbursement_processor_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

PARTIAL LOSS WORKFLOW OUTPUT (for repair duration context):
{workflow_output}

Check rental reimbursement eligibility for this partial loss claim.

1. Use check_rental_coverage with policy_number from claim_data.
2. Use get_rental_limits to get daily_limit, aggregate_limit, and max_days.
3. Use search_california_compliance with query "rental" for RCC-001 through RCC-004 and DISC-006.
4. Determine if the policyholder is eligible for rental reimbursement.

If eligible, output the limits. If not eligible, explain why (e.g., liability-only policy).""",
                expected_output="Eligibility determination: eligible (true/false), daily_limit, aggregate_limit, max_days (if applicable), and brief message.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

PARTIAL LOSS WORKFLOW OUTPUT (repair duration, shop assignment):
{workflow_output}

ELIGIBILITY RESULT (from previous task):
Use the eligibility and limits from the prior task.

Arrange and approve rental within policy limits.

1. Use get_rental_limits to confirm limits.
2. From workflow_output, extract estimated_repair_days or similar to determine rental duration.
3. Ensure rental vehicle class is comparable to the damaged vehicle (RCC-004).
4. Document the arrangement: rental provider, vehicle class, daily rate (within limit), estimated days, estimated total (capped at aggregate_limit).

If not eligible, output that no rental was arranged.""",
                expected_output="Rental arrangement with provider, vehicle class, daily rate, estimated days, estimated total, and confirmation; or 'no rental arranged' if ineligible.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

ELIGIBILITY AND RENTAL ARRANGEMENT (from previous tasks):
Use the eligibility result and rental arrangement from prior tasks.

Process the rental reimbursement.

1. Use get_rental_limits to verify limits.
2. From the rental arrangement, get the reimbursable amount (capped by daily_limit * days and aggregate_limit).
3. Use process_rental_reimbursement with claim_id, amount, rental_days, and policy_number from claim_data.
4. Document the reimbursement_id and status.

If no rental was arranged (ineligible), output that no reimbursement was processed.""",
                expected_output="Reimbursement confirmation with reimbursement_id, amount, status; or 'no reimbursement processed' if ineligible.",
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
