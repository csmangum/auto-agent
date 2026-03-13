"""Claim Review crew: supervisor/compliance audit of the claim process."""

from claim_agent.agents.claim_review import (
    create_compliance_analyst_agent,
    create_issue_synthesizer_agent,
    create_process_auditor_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.claim_review import ClaimReviewReport


def create_claim_review_crew(llm: LLMProtocol | None = None):
    """Create the Claim Review crew for supervisor/compliance process audit."""
    return create_crew(
        agents_config=[
            AgentConfig(create_process_auditor_agent),
            AgentConfig(create_compliance_analyst_agent),
            AgentConfig(create_issue_synthesizer_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""You are auditing the claim process for procedural correctness.

CLAIM ID: {claim_id}

CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT (from the run):
{workflow_output}

1. Call get_claim_process_context with claim_id to retrieve the full process context: claim record, audit log, workflow runs, task checkpoints, and notes.
2. Trace the process: which stages ran (router, escalation, workflow crew, rental, settlement, subrogation, salvage)? Were status transitions logical?
3. Identify procedural gaps: missing stages, incorrect routing, inconsistent decisions.
4. Output a process trace summary: stages run, status transitions, timing, and any procedural gaps.""",
                expected_output="Process trace summary: stages run, status transitions, timing, and any procedural gaps.",
                agent_index=0,
            ),
            TaskConfig(
                description="""You are verifying claim handling against regulatory requirements.

CLAIM ID: {claim_id}

Use get_claim_process_context with claim_id to retrieve the full process context. Use search_california_compliance, search_policy_compliance, get_compliance_deadlines, and get_required_disclosures to look up applicable rules.

Check these provisions (as applicable to this claim):
- FCSP-001: Acknowledgment within 15 days
- FCSP-002: Investigation within 40 days
- FCSP-003: Decision communicated within 40 days
- FCSP-004: Payment within 30 days of acceptance
- FCSP-005: Undisputed amounts within 30 days
- FCSP-006: Written denial requirements (if denied)
- FCSP-007: Proof of loss forms within 15 days
- FCSP-008: Additional info requests within 40 days
- RCC-001 through RCC-004: Rental rules (if partial_loss)
- Required disclosures: repair shop choice, parts type, appeal rights

Output a compliance checklist: provision_id, passed (bool), notes for each check performed.""",
                expected_output="Compliance checklist: provision_id, passed, notes for each provision checked.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""You are synthesizing the process audit and compliance findings into a structured review report.

You have received:
1. Process trace summary (from Process Auditor)
2. Compliance checklist (from Compliance Analyst)

Produce a ClaimReviewReport with:
- claim_id: {claim_id}
- overall_pass: true if no critical or high severity issues; false otherwise
- issues: list of ReviewIssue (category, severity, description, compliance_ref, recommendation)
- compliance_checks: list of ComplianceCheck (provision_id, passed, notes)
- recommendations: overall recommendations for remediation or process improvement

Severity: critical (regulatory violation), high (significant gap), medium (notable issue), low (minor improvement).
Categories: compliance, procedural, documentation, quality, fraud.""",
                expected_output="ClaimReviewReport: claim_id, overall_pass, issues, compliance_checks, recommendations.",
                agent_index=2,
                context_task_indices=[0, 1],
                output_pydantic=ClaimReviewReport,
            ),
        ],
        llm=llm,
    )
