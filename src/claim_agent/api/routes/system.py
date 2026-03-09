"""System configuration, health, and agent catalog API routes."""

import logging

from fastapi import APIRouter

from claim_agent.api.deps import require_role
from claim_agent.config import get_settings
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
                "tools": ["generate_repair_authorization", "generate_claim_id", "escalate_claim"],
                "description": "Authorizes repairs and prepares the settlement handoff",
            },
        ],
    },
    {
        "name": "Rental Reimbursement Crew",
        "description": "Manages loss-of-use / rental coverage for partial loss claims. Runs after Partial Loss, before Settlement.",
        "module": "crews/rental_crew.py",
        "agents": [
            {
                "name": "Rental Eligibility Specialist",
                "skill": "rental_eligibility_specialist",
                "tools": ["check_rental_coverage", "get_rental_limits", "search_california_compliance"],
                "description": "Checks policy for rental coverage and limits",
            },
            {
                "name": "Rental Coordinator",
                "skill": "rental_coordinator",
                "tools": ["get_rental_limits"],
                "description": "Arranges and approves rental within policy limits",
            },
            {
                "name": "Reimbursement Processor",
                "skill": "rental_reimbursement_processor",
                "tools": ["process_rental_reimbursement", "get_rental_limits"],
                "description": "Processes rental reimbursement for approved rentals",
            },
        ],
    },
    {
        "name": "Denial / Coverage Dispute Crew",
        "description": "Handles denials and coverage disputes. Reviews denial reason, verifies coverage/exclusions, generates denial letter or routes to appeal. Sub-workflow via POST /claims/{id}/denial-coverage. Requires STATUS_DENIED.",
        "module": "crews/denial_coverage_crew.py",
        "agents": [
            {
                "name": "Coverage Analyst",
                "skill": "coverage_analyst",
                "tools": ["lookup_original_claim", "query_policy_db", "get_coverage_exclusions", "search_policy_compliance"],
                "description": "Reviews denial reason and verifies coverage/exclusions",
            },
            {
                "name": "Denial Letter Specialist",
                "skill": "denial_letter_specialist",
                "tools": ["generate_denial_letter", "get_required_disclosures", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Generates compliant denial letters",
            },
            {
                "name": "Appeal Reviewer",
                "skill": "appeal_reviewer",
                "tools": ["route_to_appeal", "escalate_claim", "generate_report", "get_compliance_deadlines"],
                "description": "Decides uphold vs route to appeal",
            },
        ],
    },
    {
        "name": "Supplemental Crew",
        "description": "Handles additional damage discovered during repair on partial loss claims. Sub-workflow via POST /claims/{id}/supplemental.",
        "module": "crews/supplemental_crew.py",
        "agents": [
            {
                "name": "Supplemental Intake Specialist",
                "skill": "supplemental_intake",
                "tools": ["get_original_repair_estimate", "query_policy_db", "get_repair_standards"],
                "description": "Validates supplemental report and retrieves original estimate",
            },
            {
                "name": "Damage Verifier",
                "skill": "damage_verifier",
                "tools": ["get_original_repair_estimate", "evaluate_damage"],
                "description": "Compares supplemental damage to original scope",
            },
            {
                "name": "Estimate Adjuster",
                "skill": "estimate_adjuster",
                "tools": ["calculate_supplemental_estimate", "update_repair_authorization"],
                "description": "Calculates supplemental estimate and updates authorization",
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
                "tools": ["generate_claim_id", "generate_report", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Creates claim-type-specific settlement documentation",
            },
            {
                "name": "Payment Distribution Specialist",
                "skill": "payment_distribution",
                "tools": ["calculate_payout", "generate_report", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Documents insured, lienholder, and shop payment splits",
            },
            {
                "name": "Settlement Closure Specialist",
                "skill": "settlement_closure",
                "tools": ["generate_claim_id", "generate_report", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Finalizes settlement and records post-settlement next steps",
            },
        ],
    },
    {
        "name": "Subrogation Crew",
        "description": "Recovers payments from at-fault parties after settlement. Assess fault, build case, send demand, track recovery.",
        "module": "crews/subrogation_crew.py",
        "agents": [
            {
                "name": "Liability Investigator",
                "skill": "liability_investigator",
                "tools": ["assess_liability", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Assesses fault from incident description for subrogation eligibility",
            },
            {
                "name": "Demand Specialist",
                "skill": "demand_specialist",
                "tools": ["build_subrogation_case", "send_demand_letter", "generate_report", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Builds recovery case and sends demand letter to at-fault party",
            },
            {
                "name": "Recovery Tracker",
                "skill": "recovery_tracker",
                "tools": ["record_recovery", "generate_report", "escalate_claim", "get_compliance_deadlines", "search_policy_compliance"],
                "description": "Tracks recovery status and records next steps",
            },
        ],
    },
    {
        "name": "Salvage Crew",
        "description": "Handles total-loss vehicle disposition. Runs after Settlement and Subrogation for total_loss claims only.",
        "module": "crews/salvage_crew.py",
        "agents": [
            {
                "name": "Salvage Coordinator",
                "skill": "salvage_coordinator",
                "tools": ["get_salvage_value", "generate_report", "escalate_claim", "get_total_loss_requirements", "search_policy_compliance"],
                "description": "Assesses salvage value and recommends disposition",
            },
            {
                "name": "Title Specialist",
                "skill": "title_specialist",
                "tools": ["initiate_title_transfer", "generate_report", "escalate_claim", "get_total_loss_requirements", "search_policy_compliance"],
                "description": "Initiates DMV title transfer or salvage certificate",
            },
            {
                "name": "Auction Liaison",
                "skill": "auction_liaison",
                "tools": ["record_salvage_disposition", "generate_report", "escalate_claim", "get_total_loss_requirements", "search_policy_compliance"],
                "description": "Records disposition outcome and tracks auction/recovery",
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
        "background_tasks": {
            "max_concurrent": get_settings().max_concurrent_background_tasks,
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
