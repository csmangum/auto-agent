"""Router crew creation and output parsing."""

import json
from typing import Any

from crewai import Crew, Task

from claim_agent.agents.router import create_router_agent
from claim_agent.config.llm import get_llm
from claim_agent.config.settings import (
    DUPLICATE_DAYS_WINDOW,
    DUPLICATE_SIMILARITY_THRESHOLD,
    DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE,
    get_crew_verbose,
)
from claim_agent.models.claim import ClaimType, RouterOutput
from claim_agent.tools.escalation_logic import (
    normalize_claim_type,
    _parse_router_confidence,
)


def create_router_crew(llm=None):
    """Create a crew with only the router agent to classify the claim."""
    llm = llm or get_llm()
    router = create_router_agent(llm)

    _desc = """Classify the following claim based on its data.

CLAIM DATA:
{{claim_data}}

Classify this claim as exactly one of: new, duplicate, total_loss, fraud, partial_loss, bodily_injury, or reopened.

CLASSIFICATION RULES (in priority order):

0. **reopened**: If ANY of these are true in the claim data, classify as reopened:
   - "prior_claim_id" is present and not empty (references a prior settled claim)
   - "reopening_reason" is present (e.g., new_damage, policyholder_appeal, additional_covered_damage)
   - "is_reopened" is true
   Reopened claims are settled claims being reopened for new damage, policyholder appeal, or similar. Route to reopened workflow.

1. **definitive_duplicate**: If "definitive_duplicate" is true in the claim data, you MUST classify as duplicate. Do not classify as anything else.

2. **duplicate**: ONLY if "existing_claims_for_vin" contains claims with:
   - For standard claims: description_similarity_score >= {duplicate_threshold} AND days_difference <= {days_window} (incident dates within {days_window} days)
   - For high-value claims ("high_value_claim": true): description_similarity_score >= {duplicate_threshold_high_value} AND days_difference <= {days_window}
   - In all cases, different damage types on the same VIN are NOT duplicates, even if the above thresholds are met

3. **total_loss**: Classify as total_loss if ANY of these are true:
   - "is_catastrophic_event": true (rollover, fire, flood, etc.)
   - "damage_indicates_total_loss": true (damage description mentions totaled/destroyed/etc.)
   - "is_economic_total_loss": true AND damage description does NOT conflict with minor damage
   - Damage description contains: totaled, flood, fire, destroyed, frame bent, frame damage, rollover, submerged, roof crushed, beyond repair, complete loss, unrepairable

4. **fraud**: Classify as fraud if:
   - "pre_routing_fraud_indicators" is present AND not empty
   - OR incident description describes a minor event (e.g. "minor bump", "barely tapped", "parking lot bump") AND damage description claims major damage (e.g. "frame damage", "entire front end", "vehicle stripped") — this incident/damage mismatch is fraud
   - Fraud-override phrases in incident text: "minor bump", "barely tapped", "staged", "no witnesses", "cameras not working", "inflated" — when present with conflicting damage or pre_routing_fraud_indicators, prefer fraud
   - EXCEPTION: If damage text contains catastrophic keywords (flood, fire, rollover, submerged), classify as total_loss, NOT fraud
   - High damage-to-value ratio alone is NOT fraud if the damage description supports total loss

5. **bodily_injury**: Classify as bodily_injury if the claim involves injury to persons:
   - Incident or damage description mentions: injured, injury, whiplash, broken bone, fracture, hospital, medical treatment, back pain, neck pain, concussion, soft tissue, laceration, ambulance, ER visit, bodily harm, passenger injured, driver injured
   - "injury_related" or "bodily_injury" is true in claim data when present
   - When injury to people is a significant component (not just vehicle damage), use bodily_injury

6. **partial_loss**: Damage is repairable:
   - Bumper, fender, door, mirror, dent, scratch, light, windshield damage
   - No catastrophic keywords in damage description
   - "damage_is_repairable": true indicates damage to replaceable parts
   - If damage_is_repairable is true AND is_economic_total_loss is false -> partial_loss
   - Even with high damage cost, if only repairable parts are mentioned (doors, panels, etc.) -> partial_loss

7. **new**: First-time claim, unclear damage, or needs assessment. Use only if none of the above apply.

EDGE CASE HINTS:
- Very old vehicles (15+ years) with repair cost > 75% of value are typically total_loss.
- If damage_is_repairable is true and no catastrophic keywords in damage description, prefer partial_loss unless is_economic_total_loss is explicitly true.

KEY DECISION POINTS:
- If prior_claim_id, reopening_reason, or is_reopened present -> reopened
- If definitive_duplicate is true -> duplicate (MUST)
- If injury to persons is mentioned (injured, whiplash, hospital, etc.) -> bodily_injury
- If damage says "totaled", "destroyed", "total loss", "beyond repair" -> total_loss (NOT fraud)
- If rollover, fire, or flood mentioned in damage -> total_loss (NOT fraud)
- If incident says "minor bump"/"barely tapped"/"staged"/"no witnesses" and damage claims major damage or pre_routing_fraud_indicators present -> fraud (unless damage has catastrophic keywords)
- High damage cost alone without fraud keywords -> check if total_loss first
- For duplicates: Look at both days_difference AND description_similarity_score

Reply with a JSON object containing:
- claim_type: exactly one of new, duplicate, total_loss, fraud, partial_loss, bodily_injury, or reopened
- confidence: a number from 0.0 to 1.0 indicating your confidence in this classification (1.0 = certain, 0.5 = uncertain)
- reasoning: one sentence explaining your classification""".format(
        duplicate_threshold=DUPLICATE_SIMILARITY_THRESHOLD,
        duplicate_threshold_high_value=DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE,
        days_window=DUPLICATE_DAYS_WINDOW,
    )

    classify_task = Task(
        description=_desc,
        expected_output="JSON: {claim_type, confidence (0.0-1.0), reasoning}",
        agent=router,
        output_pydantic=RouterOutput,
    )

    return Crew(
        agents=[router],
        tasks=[classify_task],
        verbose=get_crew_verbose(),
    )


def create_main_crew(llm=None):
    """Create the main crew (router only). Use run_claim_workflow to classify and run the right sub-crew."""
    return create_router_crew(llm)


def _parse_claim_type(raw_output: str) -> str:
    """Parse claim type from router output with strict matching."""
    lines = raw_output.strip().split("\n")
    for line in lines:
        normalized = line.strip().lower().replace("_", " ").replace("-", " ")
        if normalized in ("new", "duplicate", "total loss", "partial loss", "fraud", "bodily injury", "reopened"):
            if normalized == "total loss":
                return ClaimType.TOTAL_LOSS.value
            if normalized == "partial loss":
                return ClaimType.PARTIAL_LOSS.value
            if normalized == "new":
                return ClaimType.NEW.value
            if normalized == "duplicate":
                return ClaimType.DUPLICATE.value
            if normalized == "fraud":
                return ClaimType.FRAUD.value
            if normalized == "bodily injury":
                return ClaimType.BODILY_INJURY.value
            return normalized
        if normalized.startswith("bodily injury"):
            return ClaimType.BODILY_INJURY.value
        if normalized.startswith("reopened"):
            return ClaimType.REOPENED.value
        if normalized.startswith("fraud"):
            return ClaimType.FRAUD.value
        if normalized.startswith("partial loss"):
            return ClaimType.PARTIAL_LOSS.value
        if normalized.startswith("total loss"):
            return ClaimType.TOTAL_LOSS.value
        if normalized.startswith("duplicate"):
            return ClaimType.DUPLICATE.value
        if normalized.startswith("new"):
            return ClaimType.NEW.value
    return ClaimType.NEW.value


def _parse_router_output(result: Any, raw_output: str) -> tuple[str, float, str]:
    """Parse router output into (claim_type, confidence, reasoning).

    Prefers structured output (Pydantic or JSON). Falls back to legacy parsing.
    """
    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output and isinstance(tasks_output, list) and len(tasks_output) > 0:
        first_output = getattr(tasks_output[0], "output", None)
        if isinstance(first_output, RouterOutput):
            claim_type = normalize_claim_type(first_output.claim_type)
            confidence = max(0.0, min(1.0, float(first_output.confidence)))
            reasoning = (first_output.reasoning or "").strip()
            return claim_type, confidence, reasoning

    try:
        text = raw_output.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            claim_type = normalize_claim_type(parsed.get("claim_type", ""))
            conf_val = parsed.get("confidence")
            if conf_val is not None:
                try:
                    confidence = max(0.0, min(1.0, float(conf_val)))
                except (TypeError, ValueError):
                    confidence = 0.0
            else:
                confidence = 0.0
            reasoning = str(parsed.get("reasoning", "") or "").strip()
            return claim_type, confidence, reasoning
    except (json.JSONDecodeError, TypeError):
        pass

    claim_type = _parse_claim_type(raw_output)
    confidence = _parse_router_confidence(raw_output)
    reasoning = raw_output.strip().split("\n", 1)[-1].strip() if "\n" in raw_output else ""
    return claim_type, confidence, reasoning
