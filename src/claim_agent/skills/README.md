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
| `settlement.md` | Settlement Specialist | Generates settlement reports |

### Partial Loss Workflow
| File | Agent | Description |
|------|-------|-------------|
| `partial_loss_damage_assessor.md` | Partial Loss Damage Assessor | Confirms repairability |
| `repair_estimator.md` | Repair Estimator | Calculates repair costs |
| `repair_shop_coordinator.md` | Repair Shop Coordinator | Assigns repair facilities |
| `parts_ordering.md` | Parts Ordering Specialist | Orders required parts |
| `repair_authorization.md` | Repair Authorization Specialist | Authorizes repairs |

### Escalation
| File | Agent | Description |
|------|-------|-------------|
| `escalation.md` | Escalation Review Specialist | Flags cases for human review |

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
