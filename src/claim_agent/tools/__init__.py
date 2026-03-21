"""Tools for claim processing. Tools are lazy-loaded to avoid pulling crewai until needed."""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claim_agent.tools.valuation_tools import calculate_payout
    from claim_agent.tools.rag_tools import (
        search_policy_compliance,
        get_compliance_deadlines,
        get_required_disclosures,
        get_coverage_exclusions,
        get_total_loss_requirements,
        get_fraud_detection_guidance,
        get_repair_standards,
    )

__all__ = [
    "add_claim_note",
    "add_after_action_note",
    "get_claim_notes",
    "query_policy_db",
    "search_claims_db",
    "compute_similarity",
    "fetch_vehicle_value",
    "evaluate_damage",
    "calculate_diminished_value",
    "calculate_payout",
    "classify_document",
    "extract_document_data",
    "generate_report",
    "generate_report_pdf",
    "generate_claim_id",
    "search_california_compliance",
    "search_state_compliance",
    "evaluate_escalation",
    "escalate_claim",
    "detect_fraud_indicators",
    "get_escalation_evidence",
    "generate_escalation_report",
    # Fraud detection tools
    "analyze_claim_patterns",
    "cross_reference_fraud_indicators",
    "perform_fraud_assessment",
    "generate_fraud_report",
    # Partial loss tools
    "get_available_repair_shops",
    "assign_repair_shop",
    "get_parts_catalog",
    "create_parts_order",
    "calculate_repair_estimate",
    "generate_repair_authorization",
    # Supplemental tools
    "get_original_repair_estimate",
    "calculate_supplemental_estimate",
    "update_repair_authorization",
    # Vision tools
    "analyze_damage_photo",
    # Dispute tools
    "lookup_original_claim",
    "classify_dispute",
    "generate_dispute_report",
    # Denial / coverage tools
    "generate_denial_letter",
    "route_to_appeal",
    # RAG tools
    "search_policy_compliance",
    "get_compliance_deadlines",
    "get_required_disclosures",
    "get_coverage_exclusions",
    "get_total_loss_requirements",
    "get_fraud_detection_guidance",
    "get_repair_standards",
    # Rental tools
    "check_rental_coverage",
    "get_rental_limits",
    "process_rental_reimbursement",
    # Subrogation tools
    "assess_liability",
    "build_subrogation_case",
    "send_demand_letter",
    "record_arbitration_filing",
    "record_recovery",
    # Salvage tools
    "get_salvage_value",
    "initiate_title_transfer",
    "record_dmv_salvage_report",
    "record_salvage_disposition",
    # Bodily injury tools
    "query_medical_records",
    "assess_injury_severity",
    "calculate_bi_settlement",
    "check_pip_medpay_exhaustion",
    "check_cms_reporting_required",
    "check_minor_settlement_approval",
    "get_structured_settlement_option",
    "calculate_loss_of_earnings",
    "audit_medical_bills",
    "build_treatment_timeline",
    # Payments ledger
    "record_claim_payment",
    # After-action tools
    "close_claim",
    # Follow-up tools
    "send_user_message",
    "record_user_response",
    "check_pending_responses",
    # Party intake (witness / attorney)
    "record_witness_party",
    "update_witness_party",
    "record_witness_statement",
    "record_attorney_representation",
    # Claim review tools
    "get_claim_process_context",
    # SIU investigation tools
    "get_siu_case_details",
    "add_siu_investigation_note",
    "update_siu_case_status",
    "verify_document_authenticity",
    "check_claimant_investigation_history",
    "file_fraud_report_state_bureau",
    "file_nicb_report",
    "file_niss_report",
    # Task tools
    "create_claim_task",
    "create_document_request",
    "get_claim_tasks",
    "get_document_requests",
    "update_claim_task",
    # Compliance tools (state-specific deadlines)
    "get_state_compliance_summary",
    "get_compliance_due_date_tool",
    "get_fraud_report_template_tool",
]


def __getattr__(name: str):
    mod = sys.modules[__name__]
    if name == "add_claim_note":
        from claim_agent.tools.claim_notes_tools import add_claim_note
        setattr(mod, "add_claim_note", add_claim_note)
        return add_claim_note
    if name == "add_after_action_note":
        from claim_agent.tools.claim_notes_tools import add_after_action_note
        setattr(mod, "add_after_action_note", add_after_action_note)
        return add_after_action_note
    if name == "get_claim_notes":
        from claim_agent.tools.claim_notes_tools import get_claim_notes
        setattr(mod, "get_claim_notes", get_claim_notes)
        return get_claim_notes
    if name == "query_policy_db":
        from claim_agent.tools.policy_tools import query_policy_db
        setattr(mod, "query_policy_db", query_policy_db)
        return query_policy_db
    if name == "search_claims_db":
        from claim_agent.tools.claims_tools import search_claims_db
        setattr(mod, "search_claims_db", search_claims_db)
        return search_claims_db
    if name == "compute_similarity":
        from claim_agent.tools.claims_tools import compute_similarity
        setattr(mod, "compute_similarity", compute_similarity)
        return compute_similarity
    if name == "fetch_vehicle_value":
        from claim_agent.tools.valuation_tools import fetch_vehicle_value
        setattr(mod, "fetch_vehicle_value", fetch_vehicle_value)
        return fetch_vehicle_value
    if name == "evaluate_damage":
        from claim_agent.tools.valuation_tools import evaluate_damage
        setattr(mod, "evaluate_damage", evaluate_damage)
        return evaluate_damage
    if name == "calculate_diminished_value":
        from claim_agent.tools.valuation_tools import calculate_diminished_value
        setattr(mod, "calculate_diminished_value", calculate_diminished_value)
        return calculate_diminished_value
    if name == "calculate_payout":
        from claim_agent.tools.valuation_tools import calculate_payout
        setattr(mod, "calculate_payout", calculate_payout)
        return calculate_payout
    if name == "classify_document":
        from claim_agent.tools.document_tools import classify_document
        setattr(mod, "classify_document", classify_document)
        return classify_document
    if name == "extract_document_data":
        from claim_agent.tools.document_tools import extract_document_data
        setattr(mod, "extract_document_data", extract_document_data)
        return extract_document_data
    if name == "generate_report":
        from claim_agent.tools.document_tools import generate_report
        setattr(mod, "generate_report", generate_report)
        return generate_report
    if name == "generate_report_pdf":
        from claim_agent.tools.document_tools import generate_report_pdf
        setattr(mod, "generate_report_pdf", generate_report_pdf)
        return generate_report_pdf
    if name == "generate_claim_id":
        from claim_agent.tools.document_tools import generate_claim_id
        setattr(mod, "generate_claim_id", generate_claim_id)
        return generate_claim_id
    if name == "search_california_compliance":
        from claim_agent.tools.compliance_tools import search_california_compliance
        setattr(mod, "search_california_compliance", search_california_compliance)
        return search_california_compliance
    if name == "search_state_compliance":
        from claim_agent.tools.compliance_tools import search_state_compliance
        setattr(mod, "search_state_compliance", search_state_compliance)
        return search_state_compliance
    if name == "evaluate_escalation":
        from claim_agent.tools.escalation_tools import evaluate_escalation
        setattr(mod, "evaluate_escalation", evaluate_escalation)
        return evaluate_escalation
    if name == "escalate_claim":
        from claim_agent.tools.escalation_tools import escalate_claim
        setattr(mod, "escalate_claim", escalate_claim)
        return escalate_claim
    if name == "detect_fraud_indicators":
        from claim_agent.tools.escalation_tools import detect_fraud_indicators
        setattr(mod, "detect_fraud_indicators", detect_fraud_indicators)
        return detect_fraud_indicators
    if name == "get_escalation_evidence":
        from claim_agent.tools.escalation_tools import get_escalation_evidence
        setattr(mod, "get_escalation_evidence", get_escalation_evidence)
        return get_escalation_evidence
    if name == "generate_escalation_report":
        from claim_agent.tools.escalation_tools import generate_escalation_report
        setattr(mod, "generate_escalation_report", generate_escalation_report)
        return generate_escalation_report
    # Fraud detection tools
    if name == "analyze_claim_patterns":
        from claim_agent.tools.fraud_tools import analyze_claim_patterns
        setattr(mod, "analyze_claim_patterns", analyze_claim_patterns)
        return analyze_claim_patterns
    if name == "cross_reference_fraud_indicators":
        from claim_agent.tools.fraud_tools import cross_reference_fraud_indicators
        setattr(mod, "cross_reference_fraud_indicators", cross_reference_fraud_indicators)
        return cross_reference_fraud_indicators
    if name == "perform_fraud_assessment":
        from claim_agent.tools.fraud_tools import perform_fraud_assessment
        setattr(mod, "perform_fraud_assessment", perform_fraud_assessment)
        return perform_fraud_assessment
    if name == "generate_fraud_report":
        from claim_agent.tools.fraud_tools import generate_fraud_report
        setattr(mod, "generate_fraud_report", generate_fraud_report)
        return generate_fraud_report
    # Partial loss tools
    if name == "get_available_repair_shops":
        from claim_agent.tools.partial_loss_tools import get_available_repair_shops
        setattr(mod, "get_available_repair_shops", get_available_repair_shops)
        return get_available_repair_shops
    if name == "assign_repair_shop":
        from claim_agent.tools.partial_loss_tools import assign_repair_shop
        setattr(mod, "assign_repair_shop", assign_repair_shop)
        return assign_repair_shop
    if name == "get_parts_catalog":
        from claim_agent.tools.partial_loss_tools import get_parts_catalog
        setattr(mod, "get_parts_catalog", get_parts_catalog)
        return get_parts_catalog
    if name == "create_parts_order":
        from claim_agent.tools.partial_loss_tools import create_parts_order
        setattr(mod, "create_parts_order", create_parts_order)
        return create_parts_order
    if name == "calculate_repair_estimate":
        from claim_agent.tools.partial_loss_tools import calculate_repair_estimate
        setattr(mod, "calculate_repair_estimate", calculate_repair_estimate)
        return calculate_repair_estimate
    if name == "generate_repair_authorization":
        from claim_agent.tools.partial_loss_tools import generate_repair_authorization
        setattr(mod, "generate_repair_authorization", generate_repair_authorization)
        return generate_repair_authorization
    # Supplemental tools
    if name == "get_original_repair_estimate":
        from claim_agent.tools.supplemental_tools import get_original_repair_estimate
        setattr(mod, "get_original_repair_estimate", get_original_repair_estimate)
        return get_original_repair_estimate
    if name == "calculate_supplemental_estimate":
        from claim_agent.tools.supplemental_tools import calculate_supplemental_estimate
        setattr(mod, "calculate_supplemental_estimate", calculate_supplemental_estimate)
        return calculate_supplemental_estimate
    if name == "update_repair_authorization":
        from claim_agent.tools.supplemental_tools import update_repair_authorization
        setattr(mod, "update_repair_authorization", update_repair_authorization)
        return update_repair_authorization
    # Vision tools
    if name == "analyze_damage_photo":
        from claim_agent.tools.vision_tools import analyze_damage_photo
        setattr(mod, "analyze_damage_photo", analyze_damage_photo)
        return analyze_damage_photo
    # Dispute tools
    if name == "lookup_original_claim":
        from claim_agent.tools.dispute_tools import lookup_original_claim
        setattr(mod, "lookup_original_claim", lookup_original_claim)
        return lookup_original_claim
    if name == "classify_dispute":
        from claim_agent.tools.dispute_tools import classify_dispute
        setattr(mod, "classify_dispute", classify_dispute)
        return classify_dispute
    if name == "generate_dispute_report":
        from claim_agent.tools.dispute_tools import generate_dispute_report
        setattr(mod, "generate_dispute_report", generate_dispute_report)
        return generate_dispute_report
    # Denial / coverage tools
    if name == "generate_denial_letter":
        from claim_agent.tools.denial_coverage_tools import generate_denial_letter
        setattr(mod, "generate_denial_letter", generate_denial_letter)
        return generate_denial_letter
    if name == "route_to_appeal":
        from claim_agent.tools.denial_coverage_tools import route_to_appeal
        setattr(mod, "route_to_appeal", route_to_appeal)
        return route_to_appeal
    # RAG tools
    if name == "search_policy_compliance":
        from claim_agent.tools.rag_tools import search_policy_compliance
        setattr(mod, "search_policy_compliance", search_policy_compliance)
        return search_policy_compliance
    if name == "get_compliance_deadlines":
        from claim_agent.tools.rag_tools import get_compliance_deadlines
        setattr(mod, "get_compliance_deadlines", get_compliance_deadlines)
        return get_compliance_deadlines
    if name == "get_required_disclosures":
        from claim_agent.tools.rag_tools import get_required_disclosures
        setattr(mod, "get_required_disclosures", get_required_disclosures)
        return get_required_disclosures
    if name == "get_coverage_exclusions":
        from claim_agent.tools.rag_tools import get_coverage_exclusions
        setattr(mod, "get_coverage_exclusions", get_coverage_exclusions)
        return get_coverage_exclusions
    if name == "get_total_loss_requirements":
        from claim_agent.tools.rag_tools import get_total_loss_requirements
        setattr(mod, "get_total_loss_requirements", get_total_loss_requirements)
        return get_total_loss_requirements
    if name == "get_fraud_detection_guidance":
        from claim_agent.tools.rag_tools import get_fraud_detection_guidance
        setattr(mod, "get_fraud_detection_guidance", get_fraud_detection_guidance)
        return get_fraud_detection_guidance
    if name == "get_repair_standards":
        from claim_agent.tools.rag_tools import get_repair_standards
        setattr(mod, "get_repair_standards", get_repair_standards)
        return get_repair_standards
    # Rental tools
    if name == "check_rental_coverage":
        from claim_agent.tools.rental_tools import check_rental_coverage
        setattr(mod, "check_rental_coverage", check_rental_coverage)
        return check_rental_coverage
    if name == "get_rental_limits":
        from claim_agent.tools.rental_tools import get_rental_limits
        setattr(mod, "get_rental_limits", get_rental_limits)
        return get_rental_limits
    if name == "process_rental_reimbursement":
        from claim_agent.tools.rental_tools import process_rental_reimbursement
        setattr(mod, "process_rental_reimbursement", process_rental_reimbursement)
        return process_rental_reimbursement
    # Subrogation tools
    if name == "assess_liability":
        from claim_agent.tools.subrogation_tools import assess_liability
        setattr(mod, "assess_liability", assess_liability)
        return assess_liability
    if name == "build_subrogation_case":
        from claim_agent.tools.subrogation_tools import build_subrogation_case
        setattr(mod, "build_subrogation_case", build_subrogation_case)
        return build_subrogation_case
    if name == "send_demand_letter":
        from claim_agent.tools.subrogation_tools import send_demand_letter
        setattr(mod, "send_demand_letter", send_demand_letter)
        return send_demand_letter
    if name == "record_arbitration_filing":
        from claim_agent.tools.subrogation_tools import record_arbitration_filing
        setattr(mod, "record_arbitration_filing", record_arbitration_filing)
        return record_arbitration_filing
    if name == "record_recovery":
        from claim_agent.tools.subrogation_tools import record_recovery
        setattr(mod, "record_recovery", record_recovery)
        return record_recovery
    # Salvage tools
    if name == "get_salvage_value":
        from claim_agent.tools.salvage_tools import get_salvage_value
        setattr(mod, "get_salvage_value", get_salvage_value)
        return get_salvage_value
    if name == "initiate_title_transfer":
        from claim_agent.tools.salvage_tools import initiate_title_transfer
        setattr(mod, "initiate_title_transfer", initiate_title_transfer)
        return initiate_title_transfer
    if name == "record_dmv_salvage_report":
        from claim_agent.tools.salvage_tools import record_dmv_salvage_report
        setattr(mod, "record_dmv_salvage_report", record_dmv_salvage_report)
        return record_dmv_salvage_report
    if name == "record_salvage_disposition":
        from claim_agent.tools.salvage_tools import record_salvage_disposition
        setattr(mod, "record_salvage_disposition", record_salvage_disposition)
        return record_salvage_disposition
    # Bodily injury tools
    if name == "query_medical_records":
        from claim_agent.tools.bodily_injury_tools import query_medical_records
        setattr(mod, "query_medical_records", query_medical_records)
        return query_medical_records
    if name == "assess_injury_severity":
        from claim_agent.tools.bodily_injury_tools import assess_injury_severity
        setattr(mod, "assess_injury_severity", assess_injury_severity)
        return assess_injury_severity
    if name == "calculate_bi_settlement":
        from claim_agent.tools.bodily_injury_tools import calculate_bi_settlement
        setattr(mod, "calculate_bi_settlement", calculate_bi_settlement)
        return calculate_bi_settlement
    if name == "check_pip_medpay_exhaustion":
        from claim_agent.tools.bodily_injury_tools import check_pip_medpay_exhaustion
        setattr(mod, "check_pip_medpay_exhaustion", check_pip_medpay_exhaustion)
        return check_pip_medpay_exhaustion
    if name == "check_cms_reporting_required":
        from claim_agent.tools.bodily_injury_tools import check_cms_reporting_required
        setattr(mod, "check_cms_reporting_required", check_cms_reporting_required)
        return check_cms_reporting_required
    if name == "check_minor_settlement_approval":
        from claim_agent.tools.bodily_injury_tools import check_minor_settlement_approval
        setattr(mod, "check_minor_settlement_approval", check_minor_settlement_approval)
        return check_minor_settlement_approval
    if name == "get_structured_settlement_option":
        from claim_agent.tools.bodily_injury_tools import get_structured_settlement_option
        setattr(mod, "get_structured_settlement_option", get_structured_settlement_option)
        return get_structured_settlement_option
    if name == "calculate_loss_of_earnings":
        from claim_agent.tools.bodily_injury_tools import calculate_loss_of_earnings
        setattr(mod, "calculate_loss_of_earnings", calculate_loss_of_earnings)
        return calculate_loss_of_earnings
    if name == "audit_medical_bills":
        from claim_agent.tools.bodily_injury_tools import audit_medical_bills
        setattr(mod, "audit_medical_bills", audit_medical_bills)
        return audit_medical_bills
    if name == "build_treatment_timeline":
        from claim_agent.tools.bodily_injury_tools import build_treatment_timeline
        setattr(mod, "build_treatment_timeline", build_treatment_timeline)
        return build_treatment_timeline
    # Payments ledger
    if name == "record_claim_payment":
        from claim_agent.tools.payment_tools import record_claim_payment
        setattr(mod, "record_claim_payment", record_claim_payment)
        return record_claim_payment
    # After-action tools
    if name == "close_claim":
        from claim_agent.tools.status_tools import close_claim
        setattr(mod, "close_claim", close_claim)
        return close_claim
    # Follow-up tools
    if name == "send_user_message":
        from claim_agent.tools.follow_up_tools import send_user_message
        setattr(mod, "send_user_message", send_user_message)
        return send_user_message
    if name == "record_user_response":
        from claim_agent.tools.follow_up_tools import record_user_response
        setattr(mod, "record_user_response", record_user_response)
        return record_user_response
    if name == "check_pending_responses":
        from claim_agent.tools.follow_up_tools import check_pending_responses
        setattr(mod, "check_pending_responses", check_pending_responses)
        return check_pending_responses
    if name == "record_witness_party":
        from claim_agent.tools.party_intake_tools import record_witness_party
        setattr(mod, "record_witness_party", record_witness_party)
        return record_witness_party
    if name == "update_witness_party":
        from claim_agent.tools.party_intake_tools import update_witness_party
        setattr(mod, "update_witness_party", update_witness_party)
        return update_witness_party
    if name == "record_witness_statement":
        from claim_agent.tools.party_intake_tools import record_witness_statement
        setattr(mod, "record_witness_statement", record_witness_statement)
        return record_witness_statement
    if name == "record_attorney_representation":
        from claim_agent.tools.party_intake_tools import record_attorney_representation
        setattr(mod, "record_attorney_representation", record_attorney_representation)
        return record_attorney_representation
    # Claim review tools
    if name == "get_claim_process_context":
        from claim_agent.tools.review_tools import get_claim_process_context
        setattr(mod, "get_claim_process_context", get_claim_process_context)
        return get_claim_process_context
    # SIU investigation tools
    if name == "get_siu_case_details":
        from claim_agent.tools.siu_tools import get_siu_case_details
        setattr(mod, "get_siu_case_details", get_siu_case_details)
        return get_siu_case_details
    if name == "add_siu_investigation_note":
        from claim_agent.tools.siu_tools import add_siu_investigation_note
        setattr(mod, "add_siu_investigation_note", add_siu_investigation_note)
        return add_siu_investigation_note
    if name == "update_siu_case_status":
        from claim_agent.tools.siu_tools import update_siu_case_status
        setattr(mod, "update_siu_case_status", update_siu_case_status)
        return update_siu_case_status
    if name == "verify_document_authenticity":
        from claim_agent.tools.siu_tools import verify_document_authenticity
        setattr(mod, "verify_document_authenticity", verify_document_authenticity)
        return verify_document_authenticity
    if name == "check_claimant_investigation_history":
        from claim_agent.tools.siu_tools import check_claimant_investigation_history
        setattr(mod, "check_claimant_investigation_history", check_claimant_investigation_history)
        return check_claimant_investigation_history
    if name == "file_fraud_report_state_bureau":
        from claim_agent.tools.siu_tools import file_fraud_report_state_bureau
        setattr(mod, "file_fraud_report_state_bureau", file_fraud_report_state_bureau)
        return file_fraud_report_state_bureau
    if name == "file_nicb_report":
        from claim_agent.tools.siu_tools import file_nicb_report
        setattr(mod, "file_nicb_report", file_nicb_report)
        return file_nicb_report
    if name == "file_niss_report":
        from claim_agent.tools.siu_tools import file_niss_report
        setattr(mod, "file_niss_report", file_niss_report)
        return file_niss_report
    # Task tools
    if name == "create_claim_task":
        from claim_agent.tools.task_tools import create_claim_task
        setattr(mod, "create_claim_task", create_claim_task)
        return create_claim_task
    if name == "create_document_request":
        from claim_agent.tools.task_tools import create_document_request
        setattr(mod, "create_document_request", create_document_request)
        return create_document_request
    if name == "get_document_requests":
        from claim_agent.tools.task_tools import get_document_requests
        setattr(mod, "get_document_requests", get_document_requests)
        return get_document_requests
    if name == "update_claim_task":
        from claim_agent.tools.task_tools import update_claim_task
        setattr(mod, "update_claim_task", update_claim_task)
        return update_claim_task
    if name == "get_claim_tasks":
        from claim_agent.tools.task_tools import get_claim_tasks
        setattr(mod, "get_claim_tasks", get_claim_tasks)
        return get_claim_tasks
    if name == "get_state_compliance_summary":
        from claim_agent.tools.compliance_tools import get_state_compliance_summary
        setattr(mod, "get_state_compliance_summary", get_state_compliance_summary)
        return get_state_compliance_summary
    if name == "get_compliance_due_date_tool":
        from claim_agent.tools.compliance_tools import get_compliance_due_date_tool
        setattr(mod, "get_compliance_due_date_tool", get_compliance_due_date_tool)
        return get_compliance_due_date_tool
    if name == "get_fraud_report_template_tool":
        from claim_agent.tools.compliance_tools import get_fraud_report_template_tool
        setattr(mod, "get_fraud_report_template_tool", get_fraud_report_template_tool)
        return get_fraud_report_template_tool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
