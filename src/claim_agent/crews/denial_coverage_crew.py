"""Denial and coverage dispute workflow crew.

This crew handles denials and coverage disputes through:
1. Coverage Analyst — review denial reason and verify coverage/exclusions
2. Denial Letter Specialist — generate compliant denial letter (when upholding)
3. Appeal Reviewer — decide uphold vs route to appeal
"""

from claim_agent.agents.denial_coverage import (
    create_appeal_reviewer_agent,
    create_coverage_analyst_agent,
    create_denial_letter_specialist_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_denial_coverage_crew(llm: LLMProtocol | None = None, state: str = "California"):
    """Create the Denial/Coverage crew: coverage analysis -> denial letter or appeal routing.

    Flow: Review denial reason -> Verify coverage/exclusions -> Generate denial letter or route to appeal.

    Returns:
        Crew configured for denial and coverage dispute handling.
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_coverage_analyst_agent),
            AgentConfig(create_denial_letter_specialist_agent),
            AgentConfig(create_appeal_reviewer_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DENIAL DATA (JSON):
{denial_data}

You are reviewing a denied claim. The claim has status 'denied'.

Steps:
1. Use lookup_original_claim with the claim_id to retrieve the claim record, workflow output, and any denial context.
2. Extract the denial reason from the claim data or denial_data (denial_reason field).
3. Use query_policy_db with the policy_number from the claim to retrieve policy terms.
4. Use get_coverage_exclusions with the relevant coverage type (e.g., collision, comprehensive) to verify the exclusion cited in the denial.
5. Use search_policy_compliance to find denial notice requirements and appeal rights for the state.
6. Document:
   - Whether the cited exclusion exists and applies
   - Whether policy language supports the denial
   - Recommendation: uphold_denial, reconsider, or route_to_appeal

Output the coverage analysis for the denial letter specialist and appeal reviewer.""",
                expected_output=(
                    "Coverage analysis with denial_reason, coverage_type, exclusion_verified, "
                    "policy_support, and recommendation (uphold_denial, reconsider, or route_to_appeal)."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DENIAL DATA (JSON):
{denial_data}

Using the coverage analysis from the previous task, prepare the denial letter content.

If the coverage analyst recommended UPHOLD_DENIAL:
1. Use get_required_disclosures to get mandatory disclosures for denial notices.
2. Use get_compliance_deadlines to get appeal deadline requirements.
3. Use generate_denial_letter with:
   - claim_id, denial_reason, policy_provision from the coverage analysis
   - exclusion_citation if applicable
   - appeal_deadline from compliance
   - required_disclosures from the disclosures tool
4. Output the full denial letter.

If the coverage analyst recommended ROUTE_TO_APPEAL or RECONSIDER:
- Output a brief note that no denial letter will be sent; claim will be routed to appeal.
- Do not call generate_denial_letter.""",
                expected_output=(
                    "Denial letter (when upholding) or note that claim will be routed to appeal."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DENIAL DATA (JSON):
{denial_data}

Using the coverage analysis and denial letter (or appeal note) from previous tasks, make the final determination.

If coverage analyst recommended UPHOLD_DENIAL and denial letter was generated:
1. Use generate_report to document the outcome (denial upheld, letter sent).
2. Output outcome: uphold_denial.

If coverage analyst recommended ROUTE_TO_APPEAL or RECONSIDER:
1. Use route_to_appeal with claim_id, appeal_reason (from coverage analysis), and any policyholder_evidence from denial_data.
2. Output outcome: route_to_appeal.

If the case is ambiguous or requires human judgment:
1. Use escalate_claim to flag for human review.
2. Output outcome: escalated.

Output the final determination with outcome, rationale, and next_steps.""",
                expected_output=(
                    "Final determination: outcome (uphold_denial, route_to_appeal, or escalated), "
                    "rationale, and next_steps."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state},
    )
