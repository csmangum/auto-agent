"""Rental reimbursement workflow crew for loss-of-use coverage."""

from claim_agent.agents.rental import (
    create_rental_coordinator_agent,
    create_rental_eligibility_specialist_agent,
    create_rental_reimbursement_processor_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_rental_crew(llm: LLMProtocol | None = None):
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

Determine claim coverage FIRST, then rental eligibility. A claims processor must verify coverage before authorizing any benefits (including rental).

Step 1 - CLAIM COVERAGE (required before rental):
1. Use query_policy_db with policy_number and damage_description from claim_data.
2. Verify: valid=true, physical_damage_covered=true. Confirm incident is within policy period.
3. If not covered (invalid policy, no physical damage coverage, or loss type excluded), output claim_covered: false and do NOT proceed to rental.

Step 2 - RENTAL ELIGIBILITY (only if claim_covered):
4. Use check_rental_coverage with policy_number.
5. Use get_rental_limits to get daily_limit, aggregate_limit, and max_days.
6. Use search_state_compliance with query "rental" and state=loss_state from claim_data for RCC-001 through RCC-004 and DISC-006.
7. Determine rental_eligible (true/false).

Output: claim_covered (bool), rental_eligible (bool), daily_limit, aggregate_limit, max_days, and message.""",
                expected_output="Coverage and eligibility: claim_covered (true/false), rental_eligible (true/false), daily_limit, aggregate_limit, max_days (if applicable), and brief message.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

PARTIAL LOSS WORKFLOW OUTPUT (repair duration, shop assignment):
{workflow_output}

ELIGIBILITY RESULT (from previous task):
Use the coverage and eligibility result from the prior task.

CRITICAL: Do NOT arrange rental unless BOTH claim_covered AND rental_eligible are true.
A current claims processor waits for coverage determination before authorizing rental.
If claim_covered is false or not yet determined, output "no rental arranged - coverage must be determined first".
If rental_eligible is false, output "no rental arranged" with reason.

Only when BOTH are true:
1. Use get_rental_limits to confirm limits.
2. From workflow_output, extract estimated_repair_days or similar to determine rental duration.
3. Ensure rental vehicle class is comparable to the damaged vehicle (RCC-004).
4. Document the arrangement: rental provider, vehicle class, daily rate (within limit), estimated days, estimated total (capped at aggregate_limit).""",
                expected_output="Rental arrangement with provider, vehicle class, daily rate, estimated days, estimated total, and confirmation; or 'no rental arranged' with reason (coverage not determined, not covered, or ineligible).",
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
