# Skills

Skills are markdown files that define the prompts, context, and operational procedures for each agent in the system. They serve as the "brain" of each agent, providing role definitions, goals, backstories, and detailed instructions.

For agent composition and workflow details, see [Crews](crews.md).

## Overview

The skills system provides:
- **Centralized prompt management** - All agent prompts in one location
- **Human-readable documentation** - Markdown files that serve as both prompts and docs
- **Easy customization** - Modify agent behavior by editing markdown
- **Consistency** - Single source of truth for agent definitions

## Skills Directory

```
src/claim_agent/skills/
├── __init__.py              # Utilities for loading skills
├── README.md                # Skills folder documentation
├── router.md                # Claim Router Supervisor
├── intake.md                # Intake Specialist
├── policy_checker.md        # Policy Verification Specialist
├── assignment.md            # Claim Assignment Specialist
├── search.md                # Claims Search Specialist
├── similarity.md            # Similarity Analyst
├── resolution.md            # Duplicate Resolution Specialist
├── pattern_analysis.md      # Fraud Pattern Analysis Specialist
├── cross_reference.md       # Fraud Cross-Reference Specialist
├── fraud_assessment.md      # Fraud Assessment Specialist
├── damage_assessor.md       # Damage Assessor (Total Loss)
├── valuation.md             # Vehicle Valuation Specialist
├── payout.md                # Payout Calculator
├── settlement.md            # Settlement Specialist
├── partial_loss_damage_assessor.md  # Partial Loss Damage Assessor
├── repair_estimator.md      # Repair Estimator
├── repair_shop_coordinator.md # Repair Shop Coordinator
├── parts_ordering.md        # Parts Ordering Specialist
├── repair_authorization.md  # Repair Authorization Specialist
└── escalation.md            # Escalation Review Specialist
```

## Skills by Workflow

### Core Routing

| Skill | Agent | Purpose |
|-------|-------|---------|
| `router.md` | Claim Router Supervisor | Classify claims and delegate to workflows |

### New Claim Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `intake.md` | Intake Specialist | Validate claim data and required fields |
| `policy_checker.md` | Policy Verification Specialist | Verify policy status and coverage |
| `assignment.md` | Claim Assignment Specialist | Generate claim IDs and initial setup |

### Duplicate Detection Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `search.md` | Claims Search Specialist | Search for potential duplicate claims |
| `similarity.md` | Similarity Analyst | Compare claims and compute similarity |
| `resolution.md` | Duplicate Resolution Specialist | Decide merge or reject |

### Fraud Detection Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `pattern_analysis.md` | Fraud Pattern Analysis Specialist | Identify suspicious patterns |
| `cross_reference.md` | Fraud Cross-Reference Specialist | Check fraud indicator databases |
| `fraud_assessment.md` | Fraud Assessment Specialist | Make fraud determinations |

### Total Loss Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `damage_assessor.md` | Damage Assessor | Evaluate damage severity |
| `valuation.md` | Vehicle Valuation Specialist | Fetch vehicle market value |
| `payout.md` | Payout Calculator | Calculate settlement payout |
| `settlement.md` | Settlement Specialist | Generate reports and close claims |

### Partial Loss Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `partial_loss_damage_assessor.md` | Partial Loss Damage Assessor | Confirm repairability |
| `repair_estimator.md` | Repair Estimator | Calculate repair costs |
| `repair_shop_coordinator.md` | Repair Shop Coordinator | Assign repair facilities |
| `parts_ordering.md` | Parts Ordering Specialist | Order required parts |
| `repair_authorization.md` | Repair Authorization Specialist | Authorize repairs |

### Escalation

| Skill | Agent | Purpose |
|-------|-------|---------|
| `escalation.md` | Escalation Review Specialist | Flag cases for human review |

## Skill File Structure

Each skill file follows a consistent markdown structure:

```markdown
# [Agent Name] Skill

## Role
The agent's role title (used as CrewAI agent role)

## Goal
Primary objective and responsibilities (used as CrewAI agent goal)

## Backstory
Character background providing context (used as CrewAI agent backstory)

## Tools
List of tools the agent uses

## [Process/Workflow Details]
Detailed operational procedures, decision trees, thresholds

## Output Format
Expected output structure and fields
```

### Example: Router Skill

```markdown
# Router Agent Skill

## Role
Claim Router Supervisor

## Goal
Classify the claim as 'new', 'duplicate', 'total_loss', 'fraud', 
or 'partial_loss' based on the claim description and data.

## Backstory
Senior claims manager with expertise in routing and prioritization.
You analyze claim data and direct each claim to the right specialized team.

## Classification Criteria
### New Claim
- First-time submission with no matching VIN/incident date
...
```

## Using Skills Programmatically

### Loading a Skill

```python
from claim_agent.skills import load_skill

# Load and parse a skill
skill = load_skill("router")

print(skill["role"])      # "Claim Router Supervisor"
print(skill["goal"])      # Full goal text
print(skill["backstory"]) # Full backstory text
```

### Available Functions

```python
from claim_agent.skills import (
    load_skill,           # Load and parse a skill file
    load_skill_content,   # Get raw markdown content
    get_skill_path,       # Get path to skill file
    list_skills,          # List all available skills
)

# List all skills
skills = list_skills()
# ['router', 'intake', 'policy_checker', ...]

# Get skill path
path = get_skill_path("router")
# Path('.../skills/router.md')
```

### Skill Name Constants

```python
from claim_agent.skills import (
    ROUTER,
    INTAKE,
    POLICY_CHECKER,
    ASSIGNMENT,
    SEARCH,
    SIMILARITY,
    RESOLUTION,
    PATTERN_ANALYSIS,
    CROSS_REFERENCE,
    FRAUD_ASSESSMENT,
    DAMAGE_ASSESSOR,
    VALUATION,
    PAYOUT,
    SETTLEMENT,
    PARTIAL_LOSS_DAMAGE_ASSESSOR,
    REPAIR_ESTIMATOR,
    REPAIR_SHOP_COORDINATOR,
    PARTS_ORDERING,
    REPAIR_AUTHORIZATION,
    ESCALATION,
)
```

## How Agents Use Skills

Agents load their configuration from skill files at creation time:

```python
# src/claim_agent/agents/router.py

from claim_agent.skills import load_skill, ROUTER

def create_router_agent(llm=None):
    skill = load_skill(ROUTER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        allow_delegation=True,
        verbose=True,
        llm=llm,
    )
```

This approach:
1. Keeps prompts in human-readable markdown
2. Allows non-developers to modify agent behavior
3. Provides comprehensive documentation
4. Maintains a single source of truth

## Customizing Skills

### Modifying Agent Behavior

To change how an agent operates:

1. Open the relevant skill file (e.g., `skills/router.md`)
2. Edit the Role, Goal, or Backstory sections
3. Update operational procedures as needed
4. Restart the application to load changes

### Adding Decision Criteria

Skills can include detailed decision trees and thresholds:

```markdown
## Classification Criteria

### Total Loss
- Damage description indicates severe/catastrophic damage
- Keywords: "totaled", "destroyed", "unrepairable"
- Estimated repair cost exceeds 75% of vehicle value
```

### Adding Output Specifications

Define expected outputs clearly:

```markdown
## Output Format
Provide classification with:
- `claim_type`: new / duplicate / total_loss / fraud / partial_loss
- `confidence`: HIGH / MEDIUM / LOW
- `reasoning`: Brief explanation
```

## Creating New Skills

When adding a new agent:

1. **Create the skill file**: `skills/your_agent.md`
2. **Follow the template structure**: Include Role, Goal, Backstory, Tools
3. **Add detailed procedures**: Document decision logic
4. **Register the constant**: Add to `skills/__init__.py`
5. **Use in agent code**: Load with `load_skill()`

### Template

```markdown
# [Your Agent Name] Skill

## Role
[Role title - concise, descriptive]

## Goal
[Primary objectives - what the agent should accomplish]

## Backstory
[Character background - expertise and perspective]

## Tools
- `tool_name` - Description of what it does

## Process
### Step 1: [First Step]
[Detailed instructions]

### Step 2: [Second Step]
[Detailed instructions]

## Decision Criteria
[Tables, thresholds, logic]

## Output Format
[Expected output structure]
```

## Best Practices

### Writing Effective Skills

1. **Be specific**: Include concrete thresholds and criteria
2. **Use tables**: For decision matrices and reference data
3. **Include examples**: Show expected inputs/outputs
4. **Document edge cases**: Handle unusual scenarios
5. **Keep it actionable**: Focus on what the agent should do

### Maintenance

1. **Keep in sync**: Update skills when changing agent behavior
2. **Version control**: Skills are tracked in git
3. **Review regularly**: Ensure skills reflect current requirements
4. **Test changes**: Verify agents behave as expected after edits

## Related Documentation

- [Crews](crews.md) - Workflow crew details
- [Architecture](architecture.md) - System design
- [Tools](tools.md) - Available tools reference
- [Configuration](configuration.md) - System configuration
