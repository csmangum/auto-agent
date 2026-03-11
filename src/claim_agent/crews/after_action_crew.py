"""After-action workflow crew.

Runs after all other stages to compile a summary note and evaluate
whether the claim should be closed.
"""

from claim_agent.agents.after_action import (
    create_after_action_status_agent,
    create_after_action_summary_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.config.settings import AFTER_ACTION_NOTE_MAX_TOKENS
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_after_action_crew(llm: LLMProtocol | None = None):
    """Create the after-action crew with summary and status agents."""
    max_tokens = AFTER_ACTION_NOTE_MAX_TOKENS

    return create_crew(
        agents_config=[
            AgentConfig(create_after_action_summary_agent),
            AgentConfig(create_after_action_status_agent),
        ],
        tasks_config=[
            TaskConfig(
                description=f"""CLAIM DATA (JSON):
{{claim_data}}

WORKFLOW OUTPUT:
{{workflow_output}}

TOKEN BUDGET: Your after-action note MUST stay under {max_tokens} tokens (~{max_tokens * 4}
characters). This note serves as the canonical claim state for future interactions, so it
must be dense and information-rich without being verbose. Prioritize facts over narration.
If the note exceeds the budget it will be truncated, losing trailing content.

Review the full workflow output and all existing claim notes (use get_claim_notes
with the claim_id from claim_data). Then compile a single, structured after-action
summary note and persist it using add_after_action_note with the claim_id.

The note MUST include these sections (use terse bullet points, not paragraphs):

1. **Interaction Summary** - Claim type, routing decision, which crews ran, outcomes,
   any escalations or exceptions.
2. **Information Received** - Claimant/policy details, vehicle/incident info, damage
   descriptions, estimates, attachments reviewed.
3. **Key Findings** - Coverage determination, fraud indicators, liability assessment,
   valuation/repair estimates, settlement amounts, payment distribution.
4. **Next Steps** - Pending follow-ups (subrogation, salvage, regulatory), outstanding
   info requests, scheduled reviews, adjuster recommendations.""",
                expected_output="Confirmation that the after-action summary note has been added to the claim.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Using the after-action summary context, evaluate whether this claim should be
transitioned to closed status.

Read the claim notes (use get_claim_notes) to review the after-action summary and
all prior notes. Close the claim (use close_claim with a brief reason) ONLY when:
- Settlement is fully processed and documented
- All payments have been distributed
- No pending subrogation, salvage, or regulatory actions remain
- No open disputes, appeals, or fraud investigations
- No outstanding information requests
- The after-action summary confirms no further action is needed

If ANY of those conditions are not met, do NOT close the claim. Simply confirm the
current status is appropriate and explain why closure is not warranted.""",
                expected_output="Decision on whether the claim was closed, with rationale.",
                agent_index=1,
                context_task_indices=[0],
            ),
        ],
        llm=llm,
    )
