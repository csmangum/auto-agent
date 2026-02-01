#!/usr/bin/env python3
"""Comprehensive evaluation script for agentic claim processing.

This script evaluates the claim processing system across different claim types
and scenarios, tracking accuracy, latency, cost, and token usage.

Usage:
    python scripts/evaluate_claim_processing.py [options]

Options:
    --all                Run all evaluation scenarios
    --type TYPE          Run scenarios for specific claim type
    --scenario NAME      Run a specific scenario by name
    --quick              Run quick evaluation (one scenario per type)
    --sample-claims      Run evaluation using existing sample claim files
    --output PATH        Save report to file (default: evaluation_report.json)
    --compare PATH       Compare with previous evaluation report
    --verbose            Enable verbose logging
    --dry-run            Show scenarios without running them
    --list               List all available scenarios

Claim Types:
    new, duplicate, total_loss, fraud, partial_loss

Scenario Groups:
    new, duplicate, total_loss, fraud, partial_loss, edge_cases, escalation, stress_test

Examples:
    python scripts/evaluate_claim_processing.py --all
    python scripts/evaluate_claim_processing.py --type fraud
    python scripts/evaluate_claim_processing.py --quick --verbose
    python scripts/evaluate_claim_processing.py --sample-claims
    python scripts/evaluate_claim_processing.py --compare previous_report.json
"""

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

# Load .env from project root so OPENAI_API_KEY / OPENROUTER_API_KEY are available
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

os.environ.setdefault(
    "MOCK_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"),
)


# ============================================================================
# Evaluation Scenarios Definition
# ============================================================================

@dataclass
class EvaluationScenario:
    """Definition of a single evaluation scenario."""
    
    name: str
    description: str
    claim_data: dict[str, Any]
    expected_type: str
    expected_status: str | None = None
    tags: list[str] = field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "claim_data": self.claim_data,
            "expected_type": self.expected_type,
            "expected_status": self.expected_status,
            "tags": self.tags,
            "difficulty": self.difficulty,
        }


@dataclass
class EvaluationResult:
    """Result of running an evaluation scenario."""
    
    scenario: EvaluationScenario
    success: bool
    actual_type: str | None = None
    actual_status: str | None = None
    claim_id: str | None = None
    latency_ms: float = 0.0
    error: str | None = None
    workflow_output: str | None = None
    llm_calls: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario.name,
            "expected_type": self.scenario.expected_type,
            "actual_type": self.actual_type,
            "success": self.success,
            "type_match": self.actual_type == self.scenario.expected_type,
            "actual_status": self.actual_status,
            "claim_id": self.claim_id,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }


# ============================================================================
# Scenario Definitions
# ============================================================================

# Claims exceeding this fraction of vehicle value are classified as total loss
TOTAL_LOSS_THRESHOLD_PCT = 0.75

# New Claim Scenarios
NEW_CLAIM_SCENARIOS = [
    EvaluationScenario(
        name="new_first_claim_unclear_damage",
        description="New claim with unclear damage description",
        claim_data={
            "policy_number": "POL-007",
            "vin": "1FA6P8TH2L5123456",
            "vehicle_year": 2021,
            "vehicle_make": "Ford",
            "vehicle_model": "Mustang",
            "incident_date": "2025-02-01",
            "incident_description": "Vehicle was in an accident. Need assessment.",
            "damage_description": "Damage to be assessed by adjuster.",
            "estimated_damage": None,
        },
        expected_type="new",
        tags=["unclear", "assessment_needed"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="new_weather_related",
        description="New claim from weather-related incident (hail)",
        claim_data={
            "policy_number": "POL-009",
            "vin": "2HGFG3B54CH501234",
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "incident_date": "2025-01-28",
            "incident_description": "Hail storm damage. Vehicle parked outside during storm.",
            "damage_description": "Multiple small dents on hood and roof from hail. Windshield cracked.",
            "estimated_damage": 4500,
        },
        expected_type="partial_loss",  # Hail damage is typically partial loss
        tags=["weather", "hail"],
        difficulty="medium",
    ),
]

# Duplicate Claim Scenarios
DUPLICATE_CLAIM_SCENARIOS = [
    EvaluationScenario(
        name="duplicate_same_vin_date",
        description="Duplicate claim: same VIN and incident date as existing claim",
        claim_data={
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended at stoplight. Damage to rear bumper and trunk.",
            "damage_description": "Rear bumper and trunk damaged. Rear-ended at stoplight.",
            "estimated_damage": 3500,
        },
        expected_type="duplicate",
        tags=["exact_match", "same_vin"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="duplicate_similar_description",
        description="Duplicate claim with slightly different description",
        claim_data={
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Someone hit my car from behind at a red light.",
            "damage_description": "Damage to back bumper and trunk area.",
            "estimated_damage": 3200,
        },
        expected_type="duplicate",
        tags=["similar_match", "same_vin"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="duplicate_close_date",
        description="Duplicate claim with date one day off",
        claim_data={
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-16",  # One day after existing claim
            "incident_description": "Rear-ended at intersection. Rear bumper damage.",
            "damage_description": "Bumper and trunk damage from rear collision.",
            "estimated_damage": 3400,
        },
        expected_type="duplicate",
        tags=["date_variance", "same_vin"],
        difficulty="hard",
    ),
]

# Total Loss Claim Scenarios
TOTAL_LOSS_SCENARIOS = [
    EvaluationScenario(
        name="total_loss_flood",
        description="Total loss from flood damage",
        claim_data={
            "policy_number": "POL-002",
            "vin": "1HGBH41JXMN109199",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-10",
            "incident_description": "Vehicle totaled in flood. Water damage throughout.",
            "damage_description": "Total loss. Flood damage. Vehicle submerged. Engine and interior destroyed.",
            "estimated_damage": 15000,
        },
        expected_type="total_loss",
        tags=["flood", "water_damage", "explicit_total"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="total_loss_fire",
        description="Total loss from fire damage",
        claim_data={
            "policy_number": "POL-004",
            "vin": "WBA3B1C50EK123456",
            "vehicle_year": 2019,
            "vehicle_make": "BMW",
            "vehicle_model": "330i",
            "incident_date": "2025-01-22",
            "incident_description": "Vehicle caught fire in garage. Fire department responded.",
            "damage_description": "Vehicle burned. Total loss. Fire damage throughout. Frame warped.",
            "estimated_damage": 28000,
        },
        expected_type="total_loss",
        tags=["fire", "explicit_total"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="total_loss_rollover",
        description="Total loss from rollover accident",
        claim_data={
            "policy_number": "POL-006",
            "vin": "1C6RR7GT8MS123456",
            "vehicle_year": 2023,
            "vehicle_make": "RAM",
            "vehicle_model": "1500",
            "incident_date": "2025-01-18",
            "incident_description": "Lost control on highway. Vehicle rolled over multiple times.",
            "damage_description": "Rollover damage. Roof crushed. Frame bent. Airbags deployed. Total loss.",
            "estimated_damage": 52000,
        },
        expected_type="total_loss",
        tags=["rollover", "structural_damage"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="total_loss_frame_damage",
        description="Total loss due to frame damage from collision",
        claim_data={
            "policy_number": "POL-008",
            "vin": "1G1ZD5ST0LF123456",
            "vehicle_year": 2020,
            "vehicle_make": "Chevrolet",
            "vehicle_model": "Malibu",
            "incident_date": "2025-01-25",
            "incident_description": "Head-on collision at intersection. Major impact.",
            "damage_description": "Frame damage. Engine pushed into cabin. Multiple airbags deployed. Destroyed.",
            "estimated_damage": 24000,
        },
        expected_type="total_loss",
        tags=["frame_damage", "head_on"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="total_loss_implied_by_cost",
        description="Total loss implied by repair cost exceeding vehicle value",
        claim_data={
            "policy_number": "POL-010",
            "vin": "2T1BURHE5KC123456",  # Value: $6,500
            "vehicle_year": 2016,
            "vehicle_make": "Toyota",
            "vehicle_model": "Corolla",
            "incident_date": "2025-01-26",
            "incident_description": "Struck deer on highway. Significant damage.",
            "damage_description": "Front end destroyed. Hood, bumper, headlights, radiator, fender all damaged.",
            "estimated_damage": 8500,  # Exceeds TOTAL_LOSS_THRESHOLD_PCT of $6,500 value
        },
        expected_type="total_loss",
        tags=["cost_based", "economic_total"],
        difficulty="hard",
    ),
]

# Fraud Claim Scenarios
FRAUD_CLAIM_SCENARIOS = [
    EvaluationScenario(
        name="fraud_staged_accident",
        description="Fraud indicators: staged accident language",
        claim_data={
            "policy_number": "POL-001",
            "vin": "JM1BL1S58A1234568",
            "vehicle_year": 2020,
            "vehicle_make": "Mazda",
            "vehicle_model": "3",
            "incident_date": "2026-01-25",
            "incident_description": "Staged accident at intersection. Multiple occupants all reported injuries. Witnesses left scene before police arrived. The other driver brake checked me suddenly.",
            "damage_description": "Inflated damage claim with pre-existing dents. Front bumper, hood, and both headlights claimed damaged. Repair shop estimate seems exaggerated and inconsistent with incident description.",
            "estimated_damage": 25000,
        },
        expected_type="fraud",
        tags=["staged", "inflated", "witnesses_fled"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="fraud_inflated_estimate",
        description="Fraud indicators: severely inflated damage estimate",
        claim_data={
            "policy_number": "POL-003",
            "vin": "3VWDP7AJ5HM012345",
            "vehicle_year": 2019,
            "vehicle_make": "Volkswagen",
            "vehicle_model": "Jetta",
            "incident_date": "2025-01-28",
            "incident_description": "Minor parking lot bump. Other driver barely tapped bumper.",
            "damage_description": "Claiming entire front end damage. Bumper, hood, lights, radiator, frame damage.",
            "estimated_damage": 45000,  # Way too high for minor bump
        },
        expected_type="fraud",
        tags=["inflated", "inconsistent"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="fraud_suspicious_timing",
        description="Fraud indicators: new policy with immediate claim",
        claim_data={
            "policy_number": "POL-001",
            "vin": "4T1BF1FK5EU123457",
            "vehicle_year": 2018,
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "incident_date": "2025-01-30",
            "incident_description": "Claimed theft from parking lot. No witnesses. Security cameras were not working.",
            "damage_description": "Vehicle allegedly stripped. All valuables taken. Pre-existing damage noted by previous owner.",
            "estimated_damage": 15000,
        },
        expected_type="fraud",
        tags=["theft_suspicious", "no_witnesses"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="fraud_multiple_red_flags",
        description="Multiple fraud indicators combined",
        claim_data={
            "policy_number": "POL-005",
            "vin": "1FA6P8TH2L5123457",
            "vehicle_year": 2020,
            "vehicle_make": "Ford",
            "vehicle_model": "Explorer",
            "incident_date": "2025-01-29",
            "incident_description": "Staged collision. Multiple occupants complaining of whiplash and back injuries. Witnesses suspiciously left before police arrived. Other driver is allegedly a friend.",
            "damage_description": "Inflated estimate. Pre-existing damage visible in prior photos. Inconsistent with low-speed impact claimed. Demanding full replacement of undamaged parts.",
            "estimated_damage": 38000,
        },
        expected_type="fraud",
        tags=["staged", "inflated", "injury_fraud", "witnesses_fled"],
        difficulty="easy",
    ),
]

# Partial Loss Claim Scenarios
PARTIAL_LOSS_SCENARIOS = [
    EvaluationScenario(
        name="partial_loss_basic_fender_bender",
        description="Partial loss: minor fender bender with repairable damage",
        claim_data={
            "policy_number": "POL-001",
            "vin": "5YJSA1E26HF123456",
            "vehicle_year": 2022,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model 3",
            "incident_date": "2025-01-20",
            "incident_description": "Minor fender bender in parking lot. Front bumper scratch.",
            "damage_description": "Scratches and small dent on front bumper. No structural damage.",
            "estimated_damage": 1200,
        },
        expected_type="partial_loss",
        tags=["basic", "low_damage"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="partial_loss_rear_bumper",
        description="Partial loss: rear bumper damage from rear-end collision",
        claim_data={
            "policy_number": "POL-003",
            "vin": "5FNRL6H76MB012346",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Pilot",
            "incident_date": "2025-01-28",
            "incident_description": "Rear-ended at stoplight by distracted driver. Moderate impact to rear of vehicle.",
            "damage_description": "Rear bumper cracked and dented. Taillight assembly broken. Trunk lid has minor dent. Exhaust pipe slightly bent.",
            "estimated_damage": 3500,
        },
        expected_type="partial_loss",
        tags=["bumper", "rear_collision"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="partial_loss_fender",
        description="Partial loss: fender and mirror damage from sideswipe",
        claim_data={
            "policy_number": "POL-005",
            "vin": "2HGFG3B54CH501234",
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "incident_date": "2025-01-25",
            "incident_description": "Sideswiped while parallel parking. Other driver misjudged distance.",
            "damage_description": "Front fender scratched and dented. Side mirror broken. Minor paint damage on front door.",
            "estimated_damage": 1800,
        },
        expected_type="partial_loss",
        tags=["fender", "mirror", "sideswipe"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="partial_loss_front_collision",
        description="Partial loss: front-end damage from low-speed collision",
        claim_data={
            "policy_number": "POL-011",
            "vin": "4T1BF1FK5EU123456",
            "vehicle_year": 2022,
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "incident_date": "2025-01-20",
            "incident_description": "Low-speed collision at parking lot. Vehicle in front stopped suddenly.",
            "damage_description": "Front bumper cracked. Headlight assembly on driver side broken. Hood has minor dent. Grille damaged.",
            "estimated_damage": 4200,
        },
        expected_type="partial_loss",
        tags=["front", "bumper", "headlight"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="partial_loss_door_damage",
        description="Partial loss: door and panel damage",
        claim_data={
            "policy_number": "POL-012",
            "vin": "1G1YY22G965112345",
            "vehicle_year": 2021,
            "vehicle_make": "Chevrolet",
            "vehicle_model": "Corvette",
            "incident_date": "2025-01-22",
            "incident_description": "Hit and run in parking garage. Struck while parked.",
            "damage_description": "Driver door deeply dented. Quarter panel scratched. Paint damage along driver side.",
            "estimated_damage": 5500,
        },
        expected_type="partial_loss",
        tags=["door", "panel", "hit_and_run"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="partial_loss_windshield",
        description="Partial loss: windshield damage from road debris",
        claim_data={
            "policy_number": "POL-014",
            "vin": "3VWDP7AJ5HM012345",
            "vehicle_year": 2019,
            "vehicle_make": "Volkswagen",
            "vehicle_model": "Jetta",
            "incident_date": "2025-01-24",
            "incident_description": "Rock kicked up by truck on highway. Struck windshield.",
            "damage_description": "Windshield cracked across driver view. Chip expanded to large crack.",
            "estimated_damage": 600,
        },
        expected_type="partial_loss",
        tags=["windshield", "glass", "road_debris"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="partial_loss_moderate_damage",
        description="Partial loss: moderate multi-panel damage",
        claim_data={
            "policy_number": "POL-016",
            "vin": "JM1BL1S58A1234567",
            "vehicle_year": 2021,
            "vehicle_make": "Mazda",
            "vehicle_model": "CX-5",
            "incident_date": "2025-01-27",
            "incident_description": "T-bone collision at intersection. Other driver ran red light.",
            "damage_description": "Front fender crushed. Door dented. Quarter panel damage. Wheel bent but axle intact.",
            "estimated_damage": 7500,
        },
        expected_type="partial_loss",
        tags=["multi_panel", "t_bone"],
        difficulty="medium",
    ),
]

# Edge Case Scenarios
EDGE_CASE_SCENARIOS = [
    EvaluationScenario(
        name="edge_ambiguous_damage",
        description="Edge case: ambiguous damage description",
        claim_data={
            "policy_number": "POL-017",
            "vin": "5YJ3E1EA1NF123456",
            "vehicle_year": 2023,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model Y",
            "incident_date": "2025-01-30",
            "incident_description": "Car was damaged. Need to file claim.",
            "damage_description": "Damage present. Awaiting inspection.",
            "estimated_damage": None,
        },
        expected_type="new",  # Unclear, defaults to new
        tags=["ambiguous", "edge_case"],
        difficulty="hard",
    ),
    EvaluationScenario(
        name="edge_borderline_total_loss",
        description=f"Edge case: damage near total loss threshold ({TOTAL_LOSS_THRESHOLD_PCT:.0%})",
        claim_data={
            "policy_number": "POL-005",
            "vin": "2HGFG3B54CH501234",  # Value: $8,500
            "vehicle_year": 2018,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "incident_date": "2025-01-29",
            "incident_description": "Collision damage, significant but potentially repairable.",
            "damage_description": "Front end damage. Bumper, hood, fender affected. Frame appears intact.",
            "estimated_damage": 6200,  # 73% of value - borderline
        },
        expected_type="partial_loss",  # Just under threshold
        tags=["borderline", "threshold", "edge_case"],
        difficulty="hard",
    ),
    EvaluationScenario(
        name="edge_minimal_damage",
        description="Edge case: very minimal damage",
        claim_data={
            "policy_number": "POL-019",
            "vin": "1C4RJFAG5FC612345",
            "vehicle_year": 2022,
            "vehicle_make": "Jeep",
            "vehicle_model": "Grand Cherokee",
            "incident_date": "2025-01-28",
            "incident_description": "Shopping cart rolled into vehicle in parking lot.",
            "damage_description": "Small dent on rear door. Minor paint scratch.",
            "estimated_damage": 350,
        },
        expected_type="partial_loss",
        tags=["minimal", "edge_case"],
        difficulty="easy",
    ),
    EvaluationScenario(
        name="edge_high_value_vehicle",
        description="Edge case: high-value luxury vehicle damage",
        claim_data={
            "policy_number": "POL-020",
            "vin": "5YJ3E1EA1NF123456",  # Value: $72,000
            "vehicle_year": 2023,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model S Plaid",
            "incident_date": "2025-01-26",
            "incident_description": "Struck debris on highway. Front end damage.",
            "damage_description": "Front bumper damaged. Sensor array damaged. Hood dent. Lights intact.",
            "estimated_damage": 15000,  # High but well under total loss threshold
        },
        expected_type="partial_loss",
        tags=["high_value", "luxury", "edge_case"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="edge_inactive_policy",
        description="Edge case: claim with inactive policy",
        claim_data={
            "policy_number": "POL-021",  # Inactive policy
            "vin": "1HGBH41JXMN109190",
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-30",
            "incident_description": "Rear collision at red light.",
            "damage_description": "Rear bumper damage. Tail lights broken.",
            "estimated_damage": 2500,
        },
        expected_type="partial_loss",  # Classification still works, escalation handles policy
        tags=["inactive_policy", "edge_case"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="edge_expired_policy",
        description="Edge case: claim with expired policy",
        claim_data={
            "policy_number": "POL-023",  # Expired policy
            "vin": "WBA3B1C50EK123459",
            "vehicle_year": 2019,
            "vehicle_make": "BMW",
            "vehicle_model": "330i",
            "incident_date": "2025-01-28",
            "incident_description": "Hit while parked in lot.",
            "damage_description": "Driver door dent and scratch.",
            "estimated_damage": 3200,
        },
        expected_type="partial_loss",  # Classification still works
        tags=["expired_policy", "edge_case"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="edge_very_old_vehicle",
        description="Edge case: very old low-value vehicle",
        claim_data={
            "policy_number": "POL-004",
            "vin": "1G1JC524727100001",
            "vehicle_year": 2005,
            "vehicle_make": "Chevrolet",
            "vehicle_model": "Cavalier",
            "incident_date": "2025-01-29",
            "incident_description": "Front-end collision with guardrail.",
            "damage_description": "Bumper, hood damage. Radiator may be damaged.",
            "estimated_damage": 3500,  # Likely exceeds vehicle value
        },
        expected_type="total_loss",  # Old car, likely total loss
        tags=["old_vehicle", "low_value", "edge_case"],
        difficulty="hard",
    ),
    EvaluationScenario(
        name="edge_mixed_signals_partial",
        description="Edge case: damage description with mixed signals but repairable",
        claim_data={
            "policy_number": "POL-007",
            "vin": "5FNRL6H76MB012347",
            "vehicle_year": 2022,
            "vehicle_make": "Honda",
            "vehicle_model": "Pilot",
            "incident_date": "2025-01-27",
            "incident_description": "Collision at intersection. Significant impact but vehicle drivable.",
            "damage_description": "Front bumper destroyed. Hood bent. Headlights smashed. But frame is intact and engine runs fine.",
            "estimated_damage": 6500,
        },
        expected_type="partial_loss",
        tags=["mixed_signals", "drivable", "edge_case"],
        difficulty="hard",
    ),
]

# Escalation Scenarios (claims that should trigger escalation)
ESCALATION_SCENARIOS = [
    EvaluationScenario(
        name="escalation_high_payout",
        description="Escalation: high payout claim requiring review",
        claim_data={
            "policy_number": "POL-003",
            "vin": "5YJ3E1EA1NF123456",  # Value: $72,000
            "vehicle_year": 2023,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model S",
            "incident_date": "2025-01-25",
            "incident_description": "Vehicle submerged in flash flood. Complete water damage.",
            "damage_description": "Total loss. Battery pack flooded. Interior destroyed. Electronics fried.",
            "estimated_damage": 75000,
        },
        expected_type="total_loss",
        expected_status="needs_review",  # High value should trigger escalation
        tags=["escalation", "high_value", "total_loss"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="escalation_disputed_liability",
        description="Escalation: claim with disputed liability indicators",
        claim_data={
            "policy_number": "POL-008",
            "vin": "1G1ZD5ST0LF123459",
            "vehicle_year": 2020,
            "vehicle_make": "Chevrolet",
            "vehicle_model": "Malibu",
            "incident_date": "2025-01-26",
            "incident_description": "Multi-vehicle accident. Both drivers claim green light. Police report inconclusive.",
            "damage_description": "Side impact damage. Doors crushed. No injuries reported.",
            "estimated_damage": 8500,
        },
        expected_type="partial_loss",
        tags=["escalation", "liability_dispute"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="escalation_complex_claim",
        description="Escalation: complex multi-factor claim",
        claim_data={
            "policy_number": "POL-011",
            "vin": "2T1BURHE5KC123459",
            "vehicle_year": 2019,
            "vehicle_make": "Toyota",
            "vehicle_model": "Corolla",
            "incident_date": "2025-01-28",
            "incident_description": "Accident involving uninsured motorist. Other driver fled scene. Witness statements conflicting.",
            "damage_description": "Significant damage to front quarter. Multiple repair complications expected.",
            "estimated_damage": 5500,
        },
        expected_type="partial_loss",
        tags=["escalation", "uninsured_motorist", "complex"],
        difficulty="hard",
    ),
]

# Stress Test Scenarios (unusual or extreme cases)
STRESS_TEST_SCENARIOS = [
    EvaluationScenario(
        name="stress_very_long_description",
        description="Stress test: extremely long incident description",
        claim_data={
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109191",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-29",
            "incident_description": (
                "I was driving eastbound on Highway 101 near the downtown exit at approximately "
                "3:45 PM on a Tuesday afternoon when traffic suddenly slowed due to what appeared "
                "to be construction ahead. The vehicle in front of me, a large red pickup truck, "
                "stopped abruptly without warning. I applied my brakes immediately but the road "
                "was wet from earlier rain and my tires began to skid. Despite my best efforts "
                "to stop, I made contact with the rear of the truck at what I estimate was "
                "approximately 15-20 miles per hour. The impact caused my airbags to deploy "
                "and I felt a jolt in my neck. After the collision, I pulled to the side of "
                "the road and exchanged information with the other driver. The police arrived "
                "about 20 minutes later and filed a report. I have photos of both vehicles "
                "and the road conditions at the time of the accident."
            ),
            "damage_description": "Front bumper crushed. Hood dented. Headlights broken. Airbags deployed.",
            "estimated_damage": 6500,
        },
        expected_type="partial_loss",
        tags=["stress_test", "long_description"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="stress_minimal_description",
        description="Stress test: minimal/sparse description",
        claim_data={
            "policy_number": "POL-002",
            "vin": "5YJSA1E26HF123458",
            "vehicle_year": 2022,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model 3",
            "incident_date": "2025-01-30",
            "incident_description": "Hit.",
            "damage_description": "Damage.",
            "estimated_damage": None,
        },
        expected_type="new",  # Too vague to classify
        tags=["stress_test", "minimal_description"],
        difficulty="hard",
    ),
    EvaluationScenario(
        name="stress_special_characters",
        description="Stress test: description with special characters",
        claim_data={
            "policy_number": "POL-003",
            "vin": "2HGFG3B54CH501236",
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "incident_date": "2025-01-28",
            "incident_description": "Car was hit @intersection #accident $500 damage? <unknown> driver & fled!",
            "damage_description": "Bumper (front) dented; paint scratched... lights OK!",
            "estimated_damage": 1500,
        },
        expected_type="partial_loss",
        tags=["stress_test", "special_chars"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="stress_numeric_description",
        description="Stress test: numeric/abbreviated description",
        claim_data={
            "policy_number": "POL-004",
            "vin": "3VWDP7AJ5HM012348",
            "vehicle_year": 2019,
            "vehicle_make": "Volkswagen",
            "vehicle_model": "Jetta",
            "incident_date": "2025-01-27",
            "incident_description": "2 car accident on I-95 N at MM 145. 3:30pm. Other driver ran red.",
            "damage_description": "Front: bumper 100% gone, hood 50% bent, L headlight cracked 75%.",
            "estimated_damage": 4200,
        },
        expected_type="partial_loss",
        tags=["stress_test", "numeric"],
        difficulty="medium",
    ),
    EvaluationScenario(
        name="stress_conflicting_signals",
        description="Stress test: conflicting damage signals in description",
        claim_data={
            "policy_number": "POL-005",
            "vin": "JM1BL1S58A1234569",
            "vehicle_year": 2020,
            "vehicle_make": "Mazda",
            "vehicle_model": "3",
            "incident_date": "2025-01-26",
            "incident_description": "Minor fender bender. Just a scratch really. Nothing major at all.",
            "damage_description": "Total destruction of front end. Frame bent. Engine destroyed. Totaled beyond repair.",
            "estimated_damage": 25000,
        },
        expected_type="total_loss",  # Damage description wins
        tags=["stress_test", "conflicting"],
        difficulty="hard",
    ),
]

# All scenarios grouped
ALL_SCENARIOS = {
    "new": NEW_CLAIM_SCENARIOS,
    "duplicate": DUPLICATE_CLAIM_SCENARIOS,
    "total_loss": TOTAL_LOSS_SCENARIOS,
    "fraud": FRAUD_CLAIM_SCENARIOS,
    "partial_loss": PARTIAL_LOSS_SCENARIOS,
    "edge_cases": EDGE_CASE_SCENARIOS,
    "escalation": ESCALATION_SCENARIOS,
    "stress_test": STRESS_TEST_SCENARIOS,
}


# ============================================================================
# Evaluation Engine
# ============================================================================

class ClaimEvaluator:
    """Engine for evaluating claim processing accuracy and performance."""
    
    def __init__(self, verbose: bool = False, parallel: int = 1):
        self.verbose = verbose
        self.parallel = parallel
        self.results: list[EvaluationResult] = []
        self._db_path: str | None = None
        
    def setup(self) -> None:
        """Set up evaluation environment with temporary database."""
        from claim_agent.db.database import init_db
        from claim_agent.observability.metrics import reset_metrics
        
        # Create temporary database for evaluation
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self._db_path)
        os.environ["CLAIMS_DB_PATH"] = self._db_path
        
        # Seed original claims for duplicate detection scenarios
        self._seed_original_claims()
        
        # Reset metrics
        reset_metrics()
        
        if self.verbose:
            print(f"[Setup] Using temporary database: {self._db_path}")
    
    def _seed_original_claims(self) -> None:
        """Seed the database with original claims that duplicate scenarios should match against."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from datetime import date
        
        repo = ClaimRepository(self._db_path)
        
        # Original claim that duplicate scenarios reference (same VIN: 1HGBH41JXMN109186)
        original_claim = ClaimInput(
            policy_number="POL-001",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Rear-ended at stoplight. Damage to rear bumper and trunk.",
            damage_description="Rear bumper and trunk damaged from rear-end collision.",
            estimated_damage=3500,
        )
        repo.create_claim(original_claim)
        
        if self.verbose:
            print("[Setup] Seeded original claims for duplicate detection")
    
    def teardown(self) -> None:
        """Clean up evaluation environment."""
        if self._db_path and os.path.exists(self._db_path):
            try:
                os.unlink(self._db_path)
            except OSError as e:
                # Ignore errors during cleanup since the database file is temporary,
                # but log details when running in verbose mode to aid debugging.
                if self.verbose:
                    print(
                        f"[Teardown] Failed to remove temporary database {self._db_path}: {e}",
                        file=sys.stderr,
                    )
        os.environ.pop("CLAIMS_DB_PATH", None)
        
        if self.verbose:
            print("[Teardown] Cleaned up temporary database")
    
    def run_scenario(self, scenario: EvaluationScenario) -> EvaluationResult:
        """Run a single evaluation scenario."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.observability import get_metrics
        
        if self.verbose:
            print(f"\n[Running] {scenario.name}: {scenario.description}")
        
        start_time = time.time()
        
        try:
            result = run_claim_workflow(scenario.claim_data)
            latency_ms = (time.time() - start_time) * 1000
            
            actual_type = result.get("claim_type", "unknown")
            claim_id = result.get("claim_id")
            actual_status = result.get("status")
            workflow_output = result.get("workflow_output", "")
            
            # Get metrics for this claim
            metrics = get_metrics()
            summary = metrics.get_claim_summary(claim_id) if claim_id else None
            
            llm_calls = summary.total_llm_calls if summary else 0
            total_tokens = summary.total_tokens if summary else 0
            cost_usd = summary.total_cost_usd if summary else 0.0
            
            success = True
            type_match = actual_type == scenario.expected_type
            
            if self.verbose:
                status = "✓" if type_match else "✗"
                print(f"  {status} Expected: {scenario.expected_type}, Got: {actual_type}")
                print(f"    Latency: {latency_ms:.0f}ms, Tokens: {total_tokens}, Cost: ${cost_usd:.4f}")
            
            return EvaluationResult(
                scenario=scenario,
                success=success,
                actual_type=actual_type,
                actual_status=actual_status,
                claim_id=claim_id,
                latency_ms=latency_ms,
                workflow_output=workflow_output[:500] if workflow_output else None,
                llm_calls=llm_calls,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            
            if self.verbose:
                print(f"  ✗ Error: {str(e)[:100]}")
            
            return EvaluationResult(
                scenario=scenario,
                success=False,
                error=str(e)[:500],
                latency_ms=latency_ms,
            )


def _run_scenario_worker(args: tuple[EvaluationScenario, bool]) -> EvaluationResult:
    """Run a single scenario in a worker process (own DB and env). Used for parallel execution."""
    scenario, verbose = args
    evaluator = ClaimEvaluator(verbose=verbose)
    try:
        evaluator.setup()
        return evaluator.run_scenario(scenario)
    finally:
        evaluator.teardown()


def _claim_evaluator_run_scenarios(
    self: "ClaimEvaluator",
    scenarios: list[EvaluationScenario],
    parallel: int = 1,
) -> list[EvaluationResult]:
    """Run multiple evaluation scenarios, optionally in parallel (N worker processes)."""
    if parallel and parallel > 1:
        results = []
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            futures = {
                executor.submit(_run_scenario_worker, (s, self.verbose)): s
                for s in scenarios
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                self.results.append(result)
        return results
    results = []
    for scenario in scenarios:
        result = self.run_scenario(scenario)
        results.append(result)
        self.results.append(result)
    return results


ClaimEvaluator.run_scenarios = _claim_evaluator_run_scenarios


def _run_all_impl(self: ClaimEvaluator) -> list[EvaluationResult]:
    """Run all evaluation scenarios."""
    all_scenarios = []
    for group in ALL_SCENARIOS.values():
        all_scenarios.extend(group)
    return self.run_scenarios(all_scenarios, self.parallel)


def _run_type_impl(self: ClaimEvaluator, claim_type: str) -> list[EvaluationResult]:
    """Run scenarios for a specific claim type."""
    scenarios = ALL_SCENARIOS.get(claim_type, [])
    if not scenarios:
        print(f"No scenarios found for type: {claim_type}")
        print(f"Available types: {list(ALL_SCENARIOS.keys())}")
        return []
    return self.run_scenarios(scenarios, self.parallel)


def _run_quick_impl(self: ClaimEvaluator) -> list[EvaluationResult]:
    """Run a quick evaluation with one scenario per type."""
    scenarios = []
    for group in ALL_SCENARIOS.values():
        if group:
            easy = [s for s in group if s.difficulty == "easy"]
            scenarios.append(easy[0] if easy else group[0])
    return self.run_scenarios(scenarios, self.parallel)


ClaimEvaluator.run_all = _run_all_impl
ClaimEvaluator.run_type = _run_type_impl
ClaimEvaluator.run_quick = _run_quick_impl


# ============================================================================
# Report Generation
# ============================================================================

@dataclass
class EvaluationReport:
    """Comprehensive evaluation report."""

    timestamp: str
    total_scenarios: int
    successful_runs: int
    type_accuracy: dict[str, dict[str, Any]]
    overall_accuracy: float
    total_latency_ms: float
    avg_latency_ms: float
    total_tokens: int
    total_cost_usd: float
    results: list[dict[str, Any]]
    confusion_matrix: dict[str, dict[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_scenarios": self.total_scenarios,
                "successful_runs": self.successful_runs,
                "overall_accuracy": self.overall_accuracy,
                "total_latency_ms": self.total_latency_ms,
                "avg_latency_ms": self.avg_latency_ms,
                "total_tokens": self.total_tokens,
                "total_cost_usd": self.total_cost_usd,
            },
            "accuracy_by_type": self.type_accuracy,
            "confusion_matrix": self.confusion_matrix,
            "results": self.results,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    def print_summary(self) -> None:
        """Print a human-readable summary."""
        print("\n" + "=" * 70)
        print("CLAIM PROCESSING EVALUATION REPORT")
        print("=" * 70)
        print(f"Timestamp: {self.timestamp}")
        print(f"Total Scenarios: {self.total_scenarios}")
        print(f"Successful Runs: {self.successful_runs}")
        print(f"Overall Classification Accuracy: {self.overall_accuracy:.1%}")
        print()
        
        print("ACCURACY BY EXPECTED TYPE:")
        print("-" * 50)
        for type_name, stats in sorted(self.type_accuracy.items()):
            correct = stats.get("correct", 0)
            total = stats.get("total", 0)
            accuracy = stats.get("accuracy", 0)
            print(f"  {type_name:15} {correct:3}/{total:3} ({accuracy:.1%})")
        print()

        print("CONFUSION MATRIX (expected -> actual):")
        print("-" * 50)
        all_actual = set()
        for row in self.confusion_matrix.values():
            all_actual.update(row.keys())
        types_sorted = sorted(set(self.confusion_matrix.keys()) | all_actual)
        # Header row
        print("  " + "".join(f"{t:>12}" for t in types_sorted))
        for expected in types_sorted:
            row = self.confusion_matrix.get(expected, {})
            print(
                f"  {expected:12}"
                + "".join(
                    f"{row.get(actual, 0):>12}" for actual in types_sorted
                )
            )
        print()

        print("PERFORMANCE METRICS:")
        print("-" * 50)
        print(f"  Total Latency:      {self.total_latency_ms:,.0f} ms")
        print(f"  Average Latency:    {self.avg_latency_ms:,.0f} ms")
        print(f"  Total Tokens:       {self.total_tokens:,}")
        print(f"  Total Cost:         ${self.total_cost_usd:.4f}")
        print()
        
        # Show misclassifications
        misclassified = [r for r in self.results if not r.get("type_match", True)]
        if misclassified:
            print("MISCLASSIFICATIONS:")
            print("-" * 50)
            for r in misclassified:
                print(f"  {r['scenario_name']}")
                print(f"    Expected: {r['expected_type']}, Got: {r['actual_type']}")
            print()
        
        # Show errors
        errors = [r for r in self.results if r.get("error")]
        if errors:
            print("ERRORS:")
            print("-" * 50)
            for r in errors:
                print(f"  {r['scenario_name']}: {r['error'][:80]}...")
            print()
        
        print("=" * 70)


def compute_confusion_matrix(
    results: list[EvaluationResult],
) -> dict[str, dict[str, int]]:
    """Compute confusion matrix: expected_type -> { actual_type -> count }."""
    matrix: dict[str, dict[str, int]] = {}
    for r in results:
        expected = r.scenario.expected_type
        actual = r.actual_type or "unknown"
        if expected not in matrix:
            matrix[expected] = {}
        matrix[expected][actual] = matrix[expected].get(actual, 0) + 1
    return matrix


def generate_report(results: list[EvaluationResult]) -> EvaluationReport:
    """Generate evaluation report from results."""
    timestamp = datetime.now().isoformat()

    total_scenarios = len(results)
    successful_runs = sum(1 for r in results if r.success)

    # Calculate accuracy by expected type
    type_accuracy: dict[str, dict[str, Any]] = {}
    for r in results:
        expected = r.scenario.expected_type
        if expected not in type_accuracy:
            type_accuracy[expected] = {"total": 0, "correct": 0}
        type_accuracy[expected]["total"] += 1
        if r.actual_type == expected:
            type_accuracy[expected]["correct"] += 1

    for stats in type_accuracy.values():
        stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] > 0 else 0

    # Confusion matrix
    confusion_matrix = compute_confusion_matrix(results)

    # Overall accuracy
    correct_classifications = sum(
        1 for r in results if r.actual_type == r.scenario.expected_type
    )
    overall_accuracy = correct_classifications / total_scenarios if total_scenarios > 0 else 0

    # Performance metrics
    total_latency = sum(r.latency_ms for r in results)
    avg_latency = total_latency / total_scenarios if total_scenarios > 0 else 0
    total_tokens = sum(r.total_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)

    return EvaluationReport(
        timestamp=timestamp,
        total_scenarios=total_scenarios,
        successful_runs=successful_runs,
        type_accuracy=type_accuracy,
        confusion_matrix=confusion_matrix,
        overall_accuracy=overall_accuracy,
        total_latency_ms=total_latency,
        avg_latency_ms=avg_latency,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        results=[r.to_dict() for r in results],
    )


# ============================================================================
# Sample Claims Integration
# ============================================================================

# Mapping of sample claim files to expected types
SAMPLE_CLAIMS_MAPPING = {
    "partial_loss_parking.json": "partial_loss",
    "duplicate_claim.json": "duplicate",
    "total_loss_claim.json": "total_loss",
    "fraud_claim.json": "fraud",
    "partial_loss_claim.json": "partial_loss",
    "partial_loss_fender.json": "partial_loss",
    "partial_loss_front_collision.json": "partial_loss",
}


def load_sample_claims_scenarios() -> list[EvaluationScenario]:
    """Load scenarios from the sample claims directory."""
    sample_dir = Path(__file__).resolve().parent.parent / "tests" / "sample_claims"
    scenarios = []
    
    for filename, expected_type in SAMPLE_CLAIMS_MAPPING.items():
        filepath = sample_dir / filename
        if filepath.exists():
            try:
                with open(filepath, encoding="utf-8") as f:
                    claim_data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping invalid JSON in {filename}: {e}", file=sys.stderr)
                continue

            scenarios.append(EvaluationScenario(
                name=f"sample_{filename.replace('.json', '')}",
                description=f"Sample claim from {filename}",
                claim_data=claim_data,
                expected_type=expected_type,
                tags=["sample_claim", expected_type],
                difficulty="easy",
            ))

    return scenarios


# ============================================================================
# Comparison Utilities
# ============================================================================

def load_previous_report(path: str) -> dict | None:
    """Load a previous evaluation report for comparison."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load previous report: {e}")
        return None


def compare_reports(current: EvaluationReport, previous: dict) -> None:
    """Compare current evaluation with a previous report."""
    print("\n" + "=" * 70)
    print("COMPARISON WITH PREVIOUS EVALUATION")
    print("=" * 70)
    
    prev_summary = previous.get("summary", {})
    
    # Accuracy comparison
    prev_accuracy = prev_summary.get("overall_accuracy", 0)
    curr_accuracy = current.overall_accuracy
    accuracy_diff = curr_accuracy - prev_accuracy
    accuracy_arrow = "↑" if accuracy_diff > 0 else "↓" if accuracy_diff < 0 else "="
    print(f"\nOverall Accuracy:")
    print(f"  Previous: {prev_accuracy:.1%}")
    print(f"  Current:  {curr_accuracy:.1%} ({accuracy_arrow} {abs(accuracy_diff):.1%})")
    
    # Latency comparison
    prev_latency = prev_summary.get("avg_latency_ms", 0)
    curr_latency = current.avg_latency_ms
    latency_diff = curr_latency - prev_latency
    latency_arrow = "↑" if latency_diff > 0 else "↓" if latency_diff < 0 else "="
    latency_good = "✓" if latency_diff <= 0 else ""
    print(f"\nAverage Latency:")
    print(f"  Previous: {prev_latency:,.0f} ms")
    print(f"  Current:  {curr_latency:,.0f} ms ({latency_arrow} {abs(latency_diff):,.0f} ms) {latency_good}")
    
    # Cost comparison
    prev_cost = prev_summary.get("total_cost_usd", 0)
    curr_cost = current.total_cost_usd
    cost_diff = curr_cost - prev_cost
    cost_arrow = "↑" if cost_diff > 0 else "↓" if cost_diff < 0 else "="
    cost_good = "✓" if cost_diff <= 0 else ""
    print(f"\nTotal Cost:")
    print(f"  Previous: ${prev_cost:.4f}")
    print(f"  Current:  ${curr_cost:.4f} ({cost_arrow} ${abs(cost_diff):.4f}) {cost_good}")
    
    # Token comparison
    prev_tokens = prev_summary.get("total_tokens", 0)
    curr_tokens = current.total_tokens
    tokens_diff = curr_tokens - prev_tokens
    tokens_arrow = "↑" if tokens_diff > 0 else "↓" if tokens_diff < 0 else "="
    print(f"\nTotal Tokens:")
    print(f"  Previous: {prev_tokens:,}")
    print(f"  Current:  {curr_tokens:,} ({tokens_arrow} {abs(tokens_diff):,})")
    
    # Per-type accuracy comparison
    prev_type_acc = previous.get("accuracy_by_type", {})
    print("\nAccuracy by Type Comparison:")
    print("-" * 50)
    all_types = set(current.type_accuracy.keys()) | set(prev_type_acc.keys())
    for type_name in sorted(all_types):
        prev_acc = prev_type_acc.get(type_name, {}).get("accuracy", 0)
        curr_stats = current.type_accuracy.get(type_name, {})
        curr_acc = curr_stats.get("accuracy", 0)
        diff = curr_acc - prev_acc
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "="
        print(f"  {type_name:15} {prev_acc:.1%} → {curr_acc:.1%} ({arrow} {abs(diff):.1%})")
    
    print("\n" + "=" * 70)


# ============================================================================
# CLI Interface
# ============================================================================

def filter_scenarios_by_tags(
    scenarios: list[EvaluationScenario], tags: list[str]
) -> list[EvaluationScenario]:
    """Return scenarios that have at least one of the given tags (OR logic)."""
    if not tags:
        return scenarios
    tag_set = {t.strip().lower() for t in tags if t}
    return [s for s in scenarios if any(t.lower() in tag_set for t in s.tags)]


def list_scenarios() -> None:
    """List all available scenarios."""
    print("\nAvailable Evaluation Scenarios:")
    print("=" * 70)
    for group_name, scenarios in ALL_SCENARIOS.items():
        print(f"\n{group_name.upper()} ({len(scenarios)} scenarios):")
        print("-" * 50)
        for s in scenarios:
            print(f"  [{s.difficulty}] {s.name}")
            print(f"      {s.description}")
            print(f"      Expected: {s.expected_type}, Tags: {', '.join(s.tags)}")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate agentic claim processing system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/evaluate_claim_processing.py --all
    python scripts/evaluate_claim_processing.py --type fraud
    python scripts/evaluate_claim_processing.py --quick --verbose
    python scripts/evaluate_claim_processing.py --sample-claims
    python scripts/evaluate_claim_processing.py --compare previous_report.json
    python scripts/evaluate_claim_processing.py --list
        """,
    )
    
    parser.add_argument("--all", action="store_true", help="Run all evaluation scenarios")
    parser.add_argument("--type", choices=list(ALL_SCENARIOS.keys()), help="Run scenarios for specific claim type")
    parser.add_argument("--scenario", help="Run a specific scenario by name")
    parser.add_argument("--quick", action="store_true", help="Run quick evaluation (one per type)")
    parser.add_argument("--sample-claims", action="store_true", help="Run evaluation using sample claim files")
    parser.add_argument("--output", help="Save report to JSON file")
    parser.add_argument("--compare", help="Compare with previous evaluation report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Show scenarios without running")
    parser.add_argument("--list", action="store_true", help="List all available scenarios")
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run scenarios in parallel with N worker processes (default: 1)",
    )
    parser.add_argument(
        "--tag",
        action="append",
        metavar="TAG",
        help="Filter scenarios by tag; can be repeated (OR logic)",
    )

    args = parser.parse_args()
    
    # Handle list command
    if args.list:
        list_scenarios()
        
        # Also list sample claims
        sample_scenarios = load_sample_claims_scenarios()
        if sample_scenarios:
            print(f"\nSAMPLE_CLAIMS ({len(sample_scenarios)} scenarios):")
            print("-" * 50)
            for s in sample_scenarios:
                print(f"  [easy] {s.name}")
                print(f"      {s.description}")
                print(f"      Expected: {s.expected_type}")
        return
    
    # Handle dry-run
    if args.dry_run:
        if args.scenario:
            # Find specific scenario
            found = None
            for group in ALL_SCENARIOS.values():
                for s in group:
                    if s.name == args.scenario:
                        found = s
                        break
                if found:
                    break
            # Also check sample claims
            if not found:
                for s in load_sample_claims_scenarios():
                    if s.name == args.scenario:
                        found = s
                        break
            if found:
                scenarios = [found]
            else:
                print(f"Scenario not found: {args.scenario}")
                print("Use --list to see available scenarios")
                return
        elif args.sample_claims:
            scenarios = load_sample_claims_scenarios()
        elif args.type:
            scenarios = ALL_SCENARIOS.get(args.type, [])
        elif args.quick:
            scenarios = []
            for group in ALL_SCENARIOS.values():
                if group:
                    easy = [s for s in group if s.difficulty == "easy"]
                    scenarios.append(easy[0] if easy else group[0])
        else:
            scenarios = []
            for group in ALL_SCENARIOS.values():
                scenarios.extend(group)

        scenarios = filter_scenarios_by_tags(scenarios, args.tag or [])

        print(f"\nDry Run - Would execute {len(scenarios)} scenarios:")
        for s in scenarios:
            print(f"  - {s.name} (expected: {s.expected_type})")
        return
    
    # Check for API key
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        print("Error: OPENAI_API_KEY or OPENROUTER_API_KEY must be set")
        print("Set the environment variable and try again.")
        sys.exit(1)
    
    # Determine what to run
    if not (args.all or args.type or args.scenario or args.quick or args.sample_claims):
        parser.print_help()
        print("\nError: Must specify --all, --type, --scenario, --quick, or --sample-claims")
        sys.exit(1)
    
    # Initialize evaluator
    evaluator = ClaimEvaluator(verbose=args.verbose, parallel=args.parallel)
    
    try:
        evaluator.setup()
        
        # Run appropriate evaluation
        if args.scenario:
            # Find specific scenario
            found = None
            for group in ALL_SCENARIOS.values():
                for s in group:
                    if s.name == args.scenario:
                        found = s
                        break
                if found:
                    break
            # Also check sample claims
            if not found:
                for s in load_sample_claims_scenarios():
                    if s.name == args.scenario:
                        found = s
                        break
            if not found:
                print(f"Scenario not found: {args.scenario}")
                print("Use --list to see available scenarios")
                sys.exit(1)
            scenarios = filter_scenarios_by_tags([found], args.tag or [])
            if not scenarios:
                print("No scenarios match the given --tag filter.")
                sys.exit(1)
            results = evaluator.run_scenarios(scenarios, evaluator.parallel)
        elif args.sample_claims:
            print("\nEvaluating using sample claim files...")
            scenarios = filter_scenarios_by_tags(
                load_sample_claims_scenarios(), args.tag or []
            )
            results = evaluator.run_scenarios(scenarios, evaluator.parallel)
        elif args.type:
            print(f"\nEvaluating {args.type} scenarios...")
            scenarios = filter_scenarios_by_tags(
                ALL_SCENARIOS.get(args.type, []), args.tag or []
            )
            results = evaluator.run_scenarios(scenarios, evaluator.parallel)
        elif args.quick:
            print("\nRunning quick evaluation (one per type)...")
            scenarios = []
            for group in ALL_SCENARIOS.values():
                if group:
                    easy = [s for s in group if s.difficulty == "easy"]
                    scenarios.append(easy[0] if easy else group[0])
            scenarios = filter_scenarios_by_tags(scenarios, args.tag or [])
            results = evaluator.run_scenarios(scenarios, evaluator.parallel)
        else:  # --all
            print("\nRunning comprehensive evaluation (all scenarios)...")
            all_scenarios = []
            for group in ALL_SCENARIOS.values():
                all_scenarios.extend(group)
            scenarios = filter_scenarios_by_tags(all_scenarios, args.tag or [])
            results = evaluator.run_scenarios(scenarios, evaluator.parallel)
        
        # Generate and display report
        report = generate_report(results)
        report.print_summary()
        
        # Compare with previous report if requested
        if args.compare:
            previous = load_previous_report(args.compare)
            if previous:
                compare_reports(report, previous)
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = args.output or f"evaluation_report_{timestamp}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())
        print(f"\nDetailed report saved to: {output_path}")
        
    finally:
        evaluator.teardown()


if __name__ == "__main__":
    main()
