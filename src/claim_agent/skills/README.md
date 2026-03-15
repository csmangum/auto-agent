# Agent Skills

This folder contains the skill definitions for each agent in the claims processing system. Each markdown file defines an agent's role, goal, backstory, tools, and detailed operational context.

## Purpose

These skill files serve as:
1. **Prompt templates** - The core instructions that define agent behavior
2. **Documentation** - Human-readable descriptions of agent responsibilities
3. **Context providers** - Detailed domain knowledge for each agent role

## Skill Files by Workflow

### Core Routing
| File | Agent | Description |
|------|-------|-------------|
| `router.md` | Claim Router Supervisor | Classifies and routes claims to appropriate workflows |

### New Claim Workflow
| File | Agent | Description |
|------|-------|-------------|
| `intake.md` | Intake Specialist | Validates claim data and required fields |
| `policy_checker.md` | Policy Verification Specialist | Verifies policy status and coverage |
| `assignment.md` | Claim Assignment Specialist | Generates claim IDs and initial setup |

### Duplicate Detection Workflow
| File | Agent | Description |
|------|-------|-------------|
| `search.md` | Claims Search Specialist | Searches for potential duplicate claims |
| `similarity.md` | Similarity Analyst | Compares claims for duplicate detection |
| `resolution.md` | Duplicate Resolution Specialist | Decides merge/reject for duplicates |

### Fraud Detection Workflow
| File | Agent | Description |
|------|-------|-------------|
| `pattern_analysis.md` | Fraud Pattern Analysis Specialist | Analyzes suspicious claim patterns |
| `cross_reference.md` | Fraud Cross-Reference Specialist | Checks against fraud indicators database |
| `fraud_assessment.md` | Fraud Assessment Specialist | Makes fraud determinations |

### Total Loss Workflow
| File | Agent | Description |
|------|-------|-------------|
| `damage_assessor.md` | Damage Assessor | Evaluates vehicle damage severity |
| `valuation.md` | Vehicle Valuation Specialist | Fetches vehicle market value |
| `payout.md` | Payout Calculator | Calculates total loss payout |

### Partial Loss Workflow
| File | Agent | Description |
|------|-------|-------------|
| `partial_loss_damage_assessor.md` | Partial Loss Damage Assessor | Confirms repairability |
| `repair_estimator.md` | Repair Estimator | Calculates repair costs |
| `repair_shop_coordinator.md` | Repair Shop Coordinator | Assigns repair facilities |
| `parts_ordering.md` | Parts Ordering Specialist | Orders required parts |
| `repair_authorization.md` | Repair Authorization Specialist | Authorizes repairs and prepares settlement handoff |

### Settlement Workflow
| File | Agent | Description |
|------|-------|-------------|
| `settlement_documentation.md` | Settlement Documentation Specialist | Generates claim-type-specific settlement documentation |
| `payment_distribution.md` | Payment Distribution Specialist | Documents payment recipients and amounts |
| `settlement_closure.md` | Settlement Closure Specialist | Finalizes settlement and records next steps |

### Escalation
| File | Agent | Description |
|------|-------|-------------|
| `escalation.md` | Escalation Review Specialist | Flags cases for human review |

### Rental Reimbursement Workflow
| File | Agent | Description |
|------|-------|-------------|
| `rental_eligibility_specialist.md` | Rental Eligibility Specialist | Checks rental coverage and limits |
| `rental_coordinator.md` | Rental Coordinator | Arranges rental within policy limits |
| `rental_reimbursement_processor.md` | Rental Reimbursement Processor | Processes reimbursement claims |

### Salvage Workflow
| File | Agent | Description |
|------|-------|-------------|
| `salvage_coordinator.md` | Salvage Coordinator | Assesses salvage value and disposition |
| `title_specialist.md` | Title Specialist | Initiates title transfer |
| `auction_liaison.md` | Auction Liaison | Tracks auction and recovery |

### Subrogation Workflow
| File | Agent | Description |
|------|-------|-------------|
| `liability_investigator.md` | Liability Investigator | Assesses liability |
| `demand_specialist.md` | Demand Specialist | Builds case and sends demand letters |
| `recovery_tracker.md` | Recovery Tracker | Records recovery |

### Supplemental Workflow
| File | Agent | Description |
|------|-------|-------------|
| `supplemental_intake.md` | Supplemental Intake Specialist | Validates supplemental damage reports |
| `damage_verifier.md` | Damage Verifier | Verifies additional damage |
| `estimate_adjuster.md` | Estimate Adjuster | Calculates and updates supplemental estimates |

### Denial / Coverage Dispute Workflow
| File | Agent | Description |
|------|-------|-------------|
| `coverage_analyst.md` | Coverage Analyst | Reviews denial and coverage |
| `denial_letter_specialist.md` | Denial Letter Specialist | Generates denial letters |
| `appeal_reviewer.md` | Appeal Reviewer | Routes to appeal or upholds denial |

### Dispute Workflow
| File | Agent | Description |
|------|-------|-------------|
| `dispute_intake.md` | Dispute Intake Specialist | Intakes policyholder disputes |
| `dispute_policy_analyst.md` | Dispute Policy Analyst | Analyzes policy and evidence |
| `dispute_resolution.md` | Dispute Resolution Specialist | Resolves disputes |

### Bodily Injury Workflow
| File | Agent | Description |
|------|-------|-------------|
| `bi_intake_specialist.md` | BI Intake Specialist | Intakes injury details |
| `medical_records_reviewer.md` | Medical Records Reviewer | Reviews medical records |
| `settlement_negotiator.md` | Settlement Negotiator | Proposes BI settlement |

### Human Review Handback Workflow
| File | Agent | Description |
|------|-------|-------------|
| `human_review_handback.md` | Human Review Handback Specialist | Processes post-escalation handback |

### Reopened Workflow
| File | Agent | Description |
|------|-------|-------------|
| `reopened_validator.md` | Reopened Validator | Validates reopening reason |
| `prior_claim_loader.md` | Prior Claim Loader | Loads prior settled claim |
| `reopened_router.md` | Reopened Router | Routes to partial_loss/total_loss/bodily_injury |

### SIU Investigation Workflow
| File | Agent | Description |
|------|-------|-------------|
| `siu_document_verification.md` | SIU Document Verification Specialist | Verifies document authenticity |
| `siu_records_investigator.md` | SIU Records Investigator | Investigates prior claims and fraud flags |
| `siu_case_manager.md` | SIU Case Manager | Manages SIU case and files state reports |

### Claim Review Workflow
| File | Agent | Description |
|------|-------|-------------|
| `process_auditor.md` | Process Auditor | Traces claim process |
| `compliance_review_specialist.md` | Compliance Review Specialist | Verifies compliance rules |
| `claim_review_supervisor.md` | Claim Review Supervisor | Synthesizes findings |

### Task Planner
| File | Agent | Description |
|------|-------|-------------|
| `task_planner.md` | Task Planner | Plans and coordinates tasks |

### After-Action / Follow-up Workflow
| File | Agent | Description |
|------|-------|-------------|
| `after_action_summary.md` | After Action Summary | Summarizes claim handling |
| `after_action_status.md` | After Action Status | Updates after-action status |
| `follow_up_outreach.md` | Follow-up Outreach | Initiates claimant follow-up |
| `message_composition.md` | Message Composition | Composes messages |
| `response_processing.md` | Response Processing | Processes claimant responses |

## File Structure

Each skill file follows a consistent structure:

```markdown
# [Agent Name] Skill

## Role
The agent's role title

## Goal
Primary objective and responsibilities

## Backstory
Character background providing context

## Tools
List of tools the agent uses

## [Process/Workflow Details]
Detailed operational procedures

## Output Format
Expected output structure
```

## Usage

### Loading Skills Programmatically

```python
from claim_agent.skills import load_skill

# Load a specific skill
router_skill = load_skill("router")

# Use in agent creation
agent = Agent(
    role=router_skill["role"],
    goal=router_skill["goal"],
    backstory=router_skill["backstory"],
    ...
)
```

### Referencing Skills

Skills can be referenced in agent definitions to maintain consistency between documentation and code:

```python
from claim_agent.skills import get_skill_path

# Get path to skill file for reference
skill_path = get_skill_path("router")
```

## Maintenance

When updating agent behavior:
1. Update the corresponding skill markdown file
2. Ensure the agent code reflects any changes to role, goal, or backstory
3. Keep tools lists synchronized between skill files and agent code
4. Test agent behavior after updates

## Contributing

When adding new agents:
1. Create a new skill markdown file following the template structure
2. Include all relevant operational details
3. Document expected inputs and outputs
4. Add the agent to this README
5. Update the agents code to use the skill definitions
