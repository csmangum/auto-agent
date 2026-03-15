"""Task planner crew: creates follow-up tasks after claim routing.

Runs after the primary workflow crew to analyze the claim context and
create actionable tasks for adjusters and downstream agents.
"""

from claim_agent.agents.task_planner import create_task_planner_agent
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_task_planner_crew(llm: LLMProtocol | None = None):
    """Create the task planner crew."""
    return create_crew(
        agents_config=[
            AgentConfig(create_task_planner_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Analyze this claim and create appropriate follow-up tasks. First, check existing
tasks (use get_claim_tasks with the claim_id from claim_data) and notes
(use get_claim_notes) to understand what has already been done and avoid duplicates.

Then create tasks based on the claim type, current status, and what information
or actions are still needed. Consider:

**For ALL claim types:**
- Is the police/incident report on file? If not, create a task to obtain it.
- Are there photos of the damage? If insufficient, request more.
- Has coverage been fully verified? If uncertain, create a verification task.

**For partial_loss claims:**
- Has a vehicle inspection been scheduled?
- Does a repair shop need to be contacted?
- Are repair estimates complete?

**For total_loss claims:**
- Has the vehicle been appraised?
- Is the title transfer process started?
- Are salvage arrangements needed?

**For bodily_injury claims:**
- Have medical records been requested?
- Are there treating physicians to contact?
- Is a medical records review needed?

**For fraud / fraud_suspected claims:**
- Should this be referred to SIU?
- Are there witnesses to interview?
- Are there documents to verify for authenticity?

**For new / open claims:**
- What basic information is still missing?
- Does the claimant need to be contacted for clarification?

**For duplicate claims:**
- Does the prior claim need to be reviewed?
- Should the claimant be contacted about the duplicate filing?

**Missing or incomplete information patterns to watch for:**
- Vague or very short incident descriptions → follow up for details
- No estimated damage amount → request estimate
- Missing or minimal damage description → request photos/inspection
- Incident date far in the past → verify delay reason
- High damage estimate without supporting documentation → request docs

Create each task with:
- A clear, specific title
- The appropriate task_type from the reference list
- A description explaining what needs to be done and why
- Appropriate priority (urgent/high/medium/low)
- Use "Task Planner" as the created_by value

Do NOT create tasks for work that has already been completed based on the
workflow output and existing notes.""",
                expected_output="Confirmation of tasks created with their IDs, titles, types, and priorities.",
                agent_index=0,
            ),
        ],
        llm=llm,
    )
