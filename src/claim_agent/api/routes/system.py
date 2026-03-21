"""System configuration, health, and agent catalog API routes."""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from claim_agent.api.deps import require_role
from claim_agent.config import get_settings
from claim_agent.data.loader import load_mock_db
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
RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")




# Agent/crew catalog (static structure from codebase)
_CREWS_CATALOG = [
    {
        "name": "Router Crew",
        "description": "Entry point for all claim processing. Classifies claims into one of seven types.",
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
        "name": "Escalation Crew",
        "description": "Pre-workflow HITL gate. Evaluates claims against escalation criteria and flags cases needing human review.",
        "module": "crews/escalation_crew.py",
        "agents": [
            {
                "name": "Escalation Review Specialist",
                "skill": "escalation",
                "tools": ["get_escalation_evidence", "detect_fraud_indicators", "generate_escalation_report"],
                "description": "Evaluates escalation criteria and flags cases for human review",
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
        "name": "Reopened Crew",
        "description": "Validates reopening reason, loads prior settled claim, and routes to partial_loss, total_loss, or bodily_injury.",
        "module": "crews/reopened_crew.py",
        "agents": [
            {
                "name": "Reopening Reason Validator",
                "skill": "reopened_validator",
                "tools": ["query_policy_db", "get_claim_notes"],
                "description": "Validates reopening reason before proceeding",
            },
            {
                "name": "Prior Claim Loader",
                "skill": "prior_claim_loader",
                "tools": ["lookup_original_claim"],
                "description": "Loads and summarizes the prior settled claim",
            },
            {
                "name": "Reopened Router",
                "skill": "reopened_router",
                "tools": ["evaluate_damage", "get_claim_notes"],
                "description": "Routes to partial_loss, total_loss, or bodily_injury",
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
                "tools": ["perform_fraud_assessment", "generate_fraud_report", "get_fraud_detection_guidance"],
                "description": "Makes fraud determinations and SIU referrals",
            },
        ],
    },
    {
        "name": "SIU Investigation Crew",
        "description": "Investigates claims under SIU review. Document verification, records check, case management, state fraud bureau filing. Sub-workflow via POST /claims/{id}/siu-investigate.",
        "module": "crews/siu_crew.py",
        "agents": [
            {
                "name": "SIU Document Verification Specialist",
                "skill": "siu_document_verification",
                "tools": ["verify_document_authenticity", "get_siu_case_details", "add_siu_investigation_note"],
                "description": "Verifies proof of loss, repair estimates, IDs, photos",
            },
            {
                "name": "SIU Records Investigator",
                "skill": "siu_records_investigator",
                "tools": ["check_claimant_investigation_history", "search_claims_db", "get_siu_case_details", "add_siu_investigation_note"],
                "description": "Checks prior claims, fraud flags, SIU cases on VIN/policy",
            },
            {
                "name": "SIU Case Manager",
                "skill": "siu_case_manager",
                "tools": ["get_siu_case_details", "add_siu_investigation_note", "update_siu_case_status", "file_fraud_report_state_bureau", "get_fraud_detection_guidance"],
                "description": "Synthesizes findings, files state reports, updates case status",
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
        "name": "Bodily Injury Crew",
        "description": "Handles injury-related claims: intake injury details, review medical records, assess liability, propose settlement.",
        "module": "crews/bodily_injury_crew.py",
        "agents": [
            {
                "name": "BI Intake Specialist",
                "skill": "bi_intake_specialist",
                "tools": ["add_claim_note", "get_claim_notes", "escalate_claim"],
                "description": "Captures injury details at intake",
            },
            {
                "name": "Medical Records Reviewer",
                "skill": "medical_records_reviewer",
                "tools": ["query_medical_records", "assess_injury_severity", "audit_medical_bills", "build_treatment_timeline", "add_claim_note", "get_claim_notes", "escalate_claim"],
                "description": "Reviews medical records, audits bills, builds timeline, assesses severity",
            },
            {
                "name": "Settlement Negotiator",
                "skill": "settlement_negotiator",
                "tools": ["calculate_bi_settlement", "check_pip_medpay_exhaustion", "check_cms_reporting_required", "check_minor_settlement_approval", "get_structured_settlement_option", "calculate_loss_of_earnings", "add_claim_note", "get_claim_notes", "escalate_claim"],
                "description": "Proposes BI settlement with PIP/CMS/minor/structured checks",
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
                "tools": ["check_rental_coverage", "get_rental_limits", "search_state_compliance"],
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
        "name": "Dispute Crew",
        "description": "Handles policyholder disputes on existing claims. Intake, policy/compliance analysis, resolution or escalation. Sub-workflow via POST /claims/{id}/dispute.",
        "module": "crews/dispute_crew.py",
        "agents": [
            {
                "name": "Dispute Intake Specialist",
                "skill": "dispute_intake",
                "tools": ["lookup_original_claim", "classify_dispute", "query_policy_db", "search_policy_compliance"],
                "description": "Retrieves original claim and classifies the dispute",
            },
            {
                "name": "Dispute Policy & Compliance Analyst",
                "skill": "dispute_policy_analyst",
                "tools": ["query_policy_db", "search_policy_compliance", "get_compliance_deadlines", "get_required_disclosures"],
                "description": "Reviews policy terms and regulatory requirements",
            },
            {
                "name": "Dispute Resolution Specialist",
                "skill": "dispute_resolution",
                "tools": ["fetch_vehicle_value", "calculate_repair_estimate", "calculate_payout", "escalate_claim", "generate_report", "generate_dispute_report", "get_compliance_deadlines"],
                "description": "Resolves or escalates the dispute",
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
        "name": "Human Review Handback Crew",
        "description": "Processes claims returned from human review with an approval decision. Parses decision, updates claim, routes to next step.",
        "module": "crews/human_review_handback_crew.py",
        "agents": [
            {
                "name": "Human Review Handback Specialist",
                "skill": "human_review_handback",
                "tools": ["get_escalation_context", "apply_reviewer_decision", "parse_reviewer_decision"],
                "description": "Processes post-escalation handback and routes claim",
            },
        ],
    },
    {
        "name": "Follow-up Crew",
        "description": "Human-in-the-loop outreach to claimants, policyholders, repair shops. Sends follow-up messages, records responses, integrates with pending_info.",
        "module": "crews/follow_up_crew.py",
        "agents": [
            {
                "name": "Outreach Planner",
                "skill": "follow_up_outreach",
                "tools": ["send_user_message", "check_pending_responses", "get_claim_notes"],
                "description": "Identifies user type and plans follow-up tasks",
            },
            {
                "name": "Message Composer",
                "skill": "message_composition",
                "tools": ["send_user_message", "check_pending_responses", "get_claim_notes"],
                "description": "Drafts and sends tailored outreach messages",
            },
            {
                "name": "Response Processor",
                "skill": "response_processing",
                "tools": ["check_pending_responses", "record_user_response", "add_claim_note", "get_claim_notes"],
                "description": "Processes user responses and updates claim context",
            },
        ],
    },
    {
        "name": "Party Intake Crew",
        "description": "Witness identification, statement capture, and attorney representation (LOP) intake with represented_by linkage.",
        "module": "crews/party_intake_crew.py",
        "agents": [
            {
                "name": "Party Intake Specialist (Witness & Attorney)",
                "skill": "party_intake",
                "tools": [
                    "record_witness_party",
                    "update_witness_party",
                    "record_witness_statement",
                    "record_attorney_representation",
                    "create_claim_task",
                    "create_document_request",
                    "get_claim_notes",
                    "send_user_message",
                ],
                "description": "Records witnesses and counsel; routes messaging via claim_parties",
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
    {
        "name": "After Action Crew",
        "description": "Runs after all workflow stages. Compiles summary note and evaluates whether the claim should be closed.",
        "module": "crews/after_action_crew.py",
        "agents": [
            {
                "name": "After-Action Summary Specialist",
                "skill": "after_action_summary",
                "tools": ["add_after_action_note", "get_claim_notes"],
                "description": "Compiles token-budgeted after-action summary note",
            },
            {
                "name": "After-Action Status Specialist",
                "skill": "after_action_status",
                "tools": ["close_claim", "get_claim_notes"],
                "description": "Evaluates whether claim should be closed",
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
            count = conn.execute(text("SELECT COUNT(*) as cnt FROM claims")).fetchone()[0]
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


@router.get("/system/policies", dependencies=[RequireAdjuster])
def get_policies():
    """List policies with vehicles for the New Claim form dropdown.
    Returns active policies only, with policy_vehicles for autofill."""
    db = load_mock_db()
    policies_data = db.get("policies", {})
    policy_vehicles = db.get("policy_vehicles", {})

    result = []
    for policy_number, policy in policies_data.items():
        status = (policy.get("status") or "").lower()
        if status != "active":
            continue
        raw_vehicles = policy_vehicles.get(policy_number, [])
        vehicles = [
            {
                "vin": v.get("vin", ""),
                "vehicle_year": v.get("vehicle_year"),
                "vehicle_make": v.get("vehicle_make", ""),
                "vehicle_model": v.get("vehicle_model", ""),
            }
            for v in raw_vehicles
            if v.get("vin") and v.get("vehicle_year") is not None and v.get("vehicle_make") and v.get("vehicle_model")
        ]
        if not vehicles:
            continue
        liability = policy.get("liability_limits") or {}
        bi = liability.get("bi_per_accident")
        pd = liability.get("pd_per_accident")
        coll_ded = policy.get("collision_deductible")
        comp_ded = policy.get("comprehensive_deductible")
        result.append({
            "policy_number": policy_number,
            "status": status,
            "vehicle_count": len(vehicles),
            "liability_limits": {"bi_per_accident": bi, "pd_per_accident": pd},
            "collision_deductible": coll_ded,
            "comprehensive_deductible": comp_ded,
            "vehicles": vehicles,
        })
    result.sort(key=lambda p: p["policy_number"])
    return {"policies": result}
