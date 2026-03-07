"""System configuration, health, and agent catalog API routes."""

import logging

from fastapi import APIRouter

from claim_agent.api.deps import require_role
from claim_agent.config.settings import (
    get_escalation_config,
    get_fraud_config,
    get_crew_verbose,
    MAX_TOKENS_PER_CLAIM,
    MAX_LLM_CALLS_PER_CLAIM,
    DEFAULT_BASE_VALUE,
    DEPRECIATION_PER_YEAR,
    MIN_VEHICLE_VALUE,
    DEFAULT_DEDUCTIBLE,
    MIN_PAYOUT_VEHICLE_VALUE,
    PARTIAL_LOSS_THRESHOLD,
    LABOR_HOURS_RNI_PER_PART,
    LABOR_HOURS_PAINT_BODY,
    LABOR_HOURS_MIN,
)
from claim_agent.db.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

RequireAdmin = require_role("admin")




# Agent/crew catalog (static structure from codebase)
_CREWS_CATALOG = [
    {
        "name": "Router Crew",
        "description": "Entry point for all claim processing. Classifies claims into one of five types.",
        "module": "crews/main_crew.py",
        "agents": [
            {
                "name": "Claim Router Supervisor",
                "skill": "router",
                "tools": [],
                "description": "Classifies claims and delegates to appropriate workflow",
            },
        ],
    },
    {
        "name": "New Claim Crew",
        "description": "Handles first-time claim submissions through validation, policy verification, and assignment.",
        "module": "crews/new_claim_crew.py",
        "agents": [
            {
                "name": "Intake Specialist",
                "skill": "intake",
                "tools": [],
                "description": "Validates claim data and required fields",
            },
            {
                "name": "Policy Verification Specialist",
                "skill": "policy_checker",
                "tools": ["query_policy_db"],
                "description": "Verifies policy status and coverage",
            },
            {
                "name": "Claim Assignment Specialist",
                "skill": "assignment",
                "tools": ["generate_claim_id", "generate_report"],
                "description": "Generates claim IDs and initial setup",
            },
        ],
    },
    {
        "name": "Duplicate Crew",
        "description": "Identifies and resolves potential duplicate claims.",
        "module": "crews/duplicate_crew.py",
        "agents": [
            {
                "name": "Claims Search Specialist",
                "skill": "search",
                "tools": ["search_claims_db"],
                "description": "Searches for potential duplicate claims",
            },
            {
                "name": "Similarity Analyst",
                "skill": "similarity",
                "tools": ["compute_similarity"],
                "description": "Compares claims and computes similarity scores",
            },
            {
                "name": "Duplicate Resolution Specialist",
                "skill": "resolution",
                "tools": [],
                "description": "Decides merge or reject for duplicate claims",
            },
        ],
    },
    {
        "name": "Total Loss Crew",
        "description": "Processes claims where the vehicle is a total loss and hands off payout-ready work to Settlement Crew.",
        "module": "crews/total_loss_crew.py",
        "agents": [
            {
                "name": "Damage Assessor",
                "skill": "damage_assessor",
                "tools": ["evaluate_damage"],
                "description": "Evaluates damage severity",
            },
            {
                "name": "Vehicle Valuation Specialist",
                "skill": "valuation",
                "tools": ["fetch_vehicle_value"],
                "description": "Fetches vehicle market value",
            },
            {
                "name": "Payout Calculator",
                "skill": "payout",
                "tools": ["calculate_payout"],
                "description": "Calculates settlement payout amount",
            },
        ],
    },
    {
        "name": "Fraud Detection Crew",
        "description": "Analyzes claims flagged for potential fraud. Runs directly without escalation check.",
        "module": "crews/fraud_detection_crew.py",
        "agents": [
            {
                "name": "Pattern Analysis Specialist",
                "skill": "pattern_analysis",
                "tools": ["analyze_claim_patterns"],
                "description": "Identifies suspicious patterns in claims",
            },
            {
                "name": "Cross-Reference Specialist",
                "skill": "cross_reference",
                "tools": ["cross_reference_fraud_indicators", "detect_fraud_indicators"],
                "description": "Checks fraud indicator databases",
            },
            {
                "name": "Fraud Assessment Specialist",
                "skill": "fraud_assessment",
                "tools": ["perform_fraud_assessment", "generate_fraud_report"],
                "description": "Makes fraud determinations and generates reports",
            },
        ],
    },
    {
        "name": "Partial Loss Crew",
        "description": "Handles repairable vehicle damage and hands off approved payouts to Settlement Crew.",
        "module": "crews/partial_loss_crew.py",
        "agents": [
            {
                "name": "Partial Loss Damage Assessor",
                "skill": "partial_loss_damage_assessor",
                "tools": ["evaluate_damage", "fetch_vehicle_value"],
                "description": "Confirms damage is repairable and assesses severity",
            },
            {
                "name": "Repair Estimator",
                "skill": "repair_estimator",
                "tools": ["calculate_repair_estimate", "get_parts_catalog"],
                "description": "Calculates repair costs including parts and labor",
            },
            {
                "name": "Repair Shop Coordinator",
                "skill": "repair_shop_coordinator",
                "tools": ["get_available_repair_shops", "assign_repair_shop"],
                "description": "Assigns repair facilities",
            },
            {
                "name": "Parts Ordering Specialist",
                "skill": "parts_ordering",
                "tools": ["get_parts_catalog", "create_parts_order"],
                "description": "Orders required parts for repair",
            },
            {
                "name": "Repair Authorization Specialist",
                "skill": "repair_authorization",
                "tools": ["generate_repair_authorization"],
                "description": "Authorizes repairs and prepares the settlement handoff",
            },
        ],
    },
    {
        "name": "Settlement Crew",
        "description": "Shared final settlement phase for payout-ready total loss and partial loss claims.",
        "module": "crews/settlement_crew.py",
        "agents": [
            {
                "name": "Settlement Documentation Specialist",
                "skill": "settlement_documentation",
                "tools": ["generate_claim_id", "generate_report"],
                "description": "Creates claim-type-specific settlement documentation",
            },
            {
                "name": "Payment Distribution Specialist",
                "skill": "payment_distribution",
                "tools": ["calculate_payout", "generate_report"],
                "description": "Documents insured, lienholder, and shop payment splits",
            },
            {
                "name": "Settlement Closure Specialist",
                "skill": "settlement_closure",
                "tools": ["generate_claim_id", "generate_report"],
                "description": "Finalizes settlement and records post-settlement next steps",
            },
        ],
    },
]


@router.get("/system/config", dependencies=[RequireAdmin])
def get_config():
    """Get current system configuration grouped by category."""
    return {
        "escalation": get_escalation_config(),
        "fraud": get_fraud_config(),
        "valuation": {
            "default_base_value": DEFAULT_BASE_VALUE,
            "depreciation_per_year": DEPRECIATION_PER_YEAR,
            "min_vehicle_value": MIN_VEHICLE_VALUE,
            "default_deductible": DEFAULT_DEDUCTIBLE,
            "min_payout_vehicle_value": MIN_PAYOUT_VEHICLE_VALUE,
        },
        "partial_loss": {
            "threshold": PARTIAL_LOSS_THRESHOLD,
            "labor_hours_rni_per_part": LABOR_HOURS_RNI_PER_PART,
            "labor_hours_paint_body": LABOR_HOURS_PAINT_BODY,
            "labor_hours_min": LABOR_HOURS_MIN,
        },
        "token_budgets": {
            "max_tokens_per_claim": MAX_TOKENS_PER_CLAIM,
            "max_llm_calls_per_claim": MAX_LLM_CALLS_PER_CLAIM,
        },
        "crew_verbose": get_crew_verbose(),
    }


@router.get("/system/health", dependencies=[RequireAdmin])
def health_check():
    """Health check with database connectivity."""
    try:
        with get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM claims").fetchone()["cnt"]
        db_status = "connected"
    except Exception as e:
        count = 0
        logger.error("Health check database error: %s", e)
        db_status = "error"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "total_claims": count,
    }


@router.get("/system/agents", dependencies=[RequireAdmin])
def get_agents_catalog():
    """Get the complete agent/crew catalog."""
    return {"crews": _CREWS_CATALOG}
