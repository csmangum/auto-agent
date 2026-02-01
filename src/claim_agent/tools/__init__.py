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
    "query_policy_db",
    "search_claims_db",
    "compute_similarity",
    "fetch_vehicle_value",
    "evaluate_damage",
    "calculate_payout",
    "generate_report",
    "generate_claim_id",
    "search_california_compliance",
    "evaluate_escalation",
    "detect_fraud_indicators",
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
    # RAG tools
    "search_policy_compliance",
    "get_compliance_deadlines",
    "get_required_disclosures",
    "get_coverage_exclusions",
    "get_total_loss_requirements",
    "get_fraud_detection_guidance",
    "get_repair_standards",
]


def __getattr__(name: str):
    mod = sys.modules[__name__]
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
    if name == "calculate_payout":
        from claim_agent.tools.valuation_tools import calculate_payout
        setattr(mod, "calculate_payout", calculate_payout)
        return calculate_payout
    if name == "generate_report":
        from claim_agent.tools.document_tools import generate_report
        setattr(mod, "generate_report", generate_report)
        return generate_report
    if name == "generate_claim_id":
        from claim_agent.tools.document_tools import generate_claim_id
        setattr(mod, "generate_claim_id", generate_claim_id)
        return generate_claim_id
    if name == "search_california_compliance":
        from claim_agent.tools.compliance_tools import search_california_compliance
        setattr(mod, "search_california_compliance", search_california_compliance)
        return search_california_compliance
    if name == "evaluate_escalation":
        from claim_agent.tools.escalation_tools import evaluate_escalation
        setattr(mod, "evaluate_escalation", evaluate_escalation)
        return evaluate_escalation
    if name == "detect_fraud_indicators":
        from claim_agent.tools.escalation_tools import detect_fraud_indicators
        setattr(mod, "detect_fraud_indicators", detect_fraud_indicators)
        return detect_fraud_indicators
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
