"""Tools for claim processing. Tools are lazy-loaded to avoid pulling crewai until needed."""

import sys

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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
