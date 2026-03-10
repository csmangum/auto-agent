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
├── partial_loss_damage_assessor.md  # Partial Loss Damage Assessor
├── repair_estimator.md      # Repair Estimator
├── repair_shop_coordinator.md # Repair Shop Coordinator
├── parts_ordering.md        # Parts Ordering Specialist
├── repair_authorization.md  # Repair Authorization Specialist
├── settlement_documentation.md # Settlement Documentation Specialist
├── payment_distribution.md  # Payment Distribution Specialist
├── settlement_closure.md    # Settlement Closure Specialist
├── escalation.md            # Escalation Review Specialist
├── rental_eligibility_specialist.md # Rental Eligibility Specialist
├── rental_coordinator.md    # Rental Coordinator
├── rental_reimbursement_processor.md # Rental Reimbursement Processor
├── salvage_coordinator.md   # Salvage Coordinator
├── title_specialist.md      # Title Specialist
├── auction_liaison.md       # Auction Liaison
├── liability_investigator.md # Liability Investigator
├── demand_specialist.md     # Demand Specialist
├── recovery_tracker.md      # Recovery Tracker
├── supplemental_intake.md   # Supplemental Intake Specialist
├── damage_verifier.md       # Damage Verifier
├── estimate_adjuster.md     # Estimate Adjuster
├── dispute_intake.md        # Dispute Intake Specialist
├── dispute_policy_analyst.md # Dispute Policy Analyst
├── dispute_resolution.md    # Dispute Resolution Specialist
├── coverage_analyst.md      # Coverage Analyst
├── denial_letter_specialist.md # Denial Letter Specialist
├── appeal_reviewer.md       # Appeal Reviewer
├── bi_intake_specialist.md  # Bodily Injury Intake Specialist
├── medical_records_reviewer.md # Medical Records Reviewer
├── settlement_negotiator.md  # Settlement Negotiator
├── human_review_handback.md  # Human Review Handback Specialist
├── reopened_validator.md    # Reopened Validator
├── prior_claim_loader.md    # Prior Claim Loader
└── reopened_router.md       # Reopened Router
```

*Additional skills support sub-workflows (Rental, Salvage, Subrogation, Supplemental, Denial/Coverage, Dispute, Bodily Injury, Reopened). See [Crews](crews.md) for full workflow mapping.*

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

### Partial Loss Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `partial_loss_damage_assessor.md` | Partial Loss Damage Assessor | Confirm repairability |
| `repair_estimator.md` | Repair Estimator | Calculate repair costs |
| `repair_shop_coordinator.md` | Repair Shop Coordinator | Assign repair facilities |
| `parts_ordering.md` | Parts Ordering Specialist | Order required parts |
| `repair_authorization.md` | Repair Authorization Specialist | Authorize repairs and prepare settlement handoff |

### Settlement Workflow

| Skill | Agent | Purpose |
|-------|-------|---------|
| `settlement_documentation.md` | Settlement Documentation Specialist | Create claim-type-specific settlement documentation |
| `payment_distribution.md` | Payment Distribution Specialist | Document insured, lienholder, and shop payment splits |
| `settlement_closure.md` | Settlement Closure Specialist | Finalize settlement and capture next steps |

### Escalation

| Skill | Agent | Purpose |
|-------|-------|---------|
| `escalation.md` | Escalation Review Specialist | Flag cases for human review |

### Additional Workflows

Skills for sub-workflows and specialized crews (see [Crews](crews.md) for full details):

| Workflow | Skills |
|----------|--------|
| Rental Reimbursement | `rental_eligibility_specialist`, `rental_coordinator`, `rental_reimbursement_processor` |
| Salvage | `salvage_coordinator`, `title_specialist`, `auction_liaison` |
| Subrogation | `liability_investigator`, `demand_specialist`, `recovery_tracker` |
| Supplemental | `supplemental_intake`, `damage_verifier`, `estimate_adjuster` |
| Denial / Coverage | `coverage_analyst`, `denial_letter_specialist`, `appeal_reviewer` |
| Dispute | `dispute_intake`, `dispute_policy_analyst`, `dispute_resolution` |
| Bodily Injury | `bi_intake_specialist`, `medical_records_reviewer`, `settlement_negotiator` |
| Human Review Handback | `human_review_handback` |
| Reopened | `reopened_validator`, `prior_claim_loader`, `reopened_router` |

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

All skill names are available as constants in `claim_agent.skills`. Core constants include:

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
    SETTLEMENT_DOCUMENTATION,
    PAYMENT_DISTRIBUTION,
    SETTLEMENT_CLOSURE,
    PARTIAL_LOSS_DAMAGE_ASSESSOR,
    REPAIR_ESTIMATOR,
    REPAIR_SHOP_COORDINATOR,
    PARTS_ORDERING,
    REPAIR_AUTHORIZATION,
    ESCALATION,
    # Plus: RENTAL_ELIGIBILITY_SPECIALIST, RENTAL_COORDINATOR, RENTAL_REIMBURSEMENT_PROCESSOR,
    # SALVAGE_COORDINATOR, TITLE_SPECIALIST, AUCTION_LIAISON, LIABILITY_INVESTIGATOR,
    # DEMAND_SPECIALIST, RECOVERY_TRACKER, and others for sub-workflows.
)
```

Use `list_skills()` to get the full list of available skill names.

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
