"""MCP server exposing claim tools via stdio transport.

This server includes observability endpoints for metrics and tracing.
"""

import json

from mcp.server.fastmcp import FastMCP

from claim_agent.tools.logic import (
    query_policy_db_impl,
    search_claims_db_impl,
    compute_similarity_impl,
    fetch_vehicle_value_impl,
    evaluate_damage_impl,
    calculate_payout_impl,
    generate_report_impl,
    generate_claim_id_impl,
    search_california_compliance_impl,
)
from claim_agent.observability import get_metrics

mcp = FastMCP("claim-tools", json_response=True)


@mcp.tool()
def query_policy_db(policy_number: str) -> str:
    """Query the policy database to validate policy and retrieve coverage details."""
    return query_policy_db_impl(policy_number)


@mcp.tool()
def search_claims_db(vin: str, incident_date: str) -> str:
    """Search existing claims by VIN and incident date for potential duplicates."""
    return search_claims_db_impl(vin, incident_date)


@mcp.tool()
def compute_similarity(description_a: str, description_b: str) -> str:
    """Compare two incident descriptions and return similarity score 0-100."""
    return compute_similarity_impl(description_a, description_b)


@mcp.tool()
def fetch_vehicle_value(vin: str, year: int, make: str, model: str) -> str:
    """Fetch current market value for a vehicle (mock KBB API)."""
    return fetch_vehicle_value_impl(vin, year, make, model)


@mcp.tool()
def evaluate_damage(damage_description: str, estimated_repair_cost: float | None = None) -> str:
    """Evaluate damage description and optional repair cost to assess severity."""
    return evaluate_damage_impl(damage_description, estimated_repair_cost)


@mcp.tool()
def calculate_payout(vehicle_value: float, policy_number: str) -> str:
    """Calculate total loss payout by subtracting policy deductible from vehicle value."""
    return calculate_payout_impl(vehicle_value, policy_number)


@mcp.tool()
def generate_report(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    """Generate a claim report/summary document."""
    return generate_report_impl(claim_id, claim_type, status, summary, payout_amount)


@mcp.tool()
def generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID."""
    return generate_claim_id_impl(prefix)


@mcp.tool()
def search_california_compliance(query: str = "") -> str:
    """Search California auto insurance compliance/regulatory reference data by keyword."""
    return search_california_compliance_impl(query)


# ============================================================================
# OBSERVABILITY TOOLS
# ============================================================================


@mcp.tool()
def get_claim_metrics(claim_id: str | None = None) -> str:
    """Get metrics for claim processing.

    Args:
        claim_id: Optional claim ID. If provided, returns metrics for that claim.
                 If not provided, returns global metrics summary.

    Returns:
        JSON string with metrics data including:
        - total_llm_calls: Number of LLM API calls made
        - total_tokens: Total tokens used
        - total_cost_usd: Estimated cost in USD
        - total_latency_ms: Total processing time
        - avg_latency_ms: Average latency per call
        - status: Current claim status
    """
    metrics = get_metrics()

    if claim_id:
        summary = metrics.get_claim_summary(claim_id)
        if summary is None:
            return json.dumps({"error": f"No metrics found for claim: {claim_id}"})
        return json.dumps(summary.to_dict(), default=str)
    else:
        return json.dumps({
            "global_stats": metrics.get_global_stats(),
            "claims": [s.to_dict() for s in metrics.get_all_summaries()],
        }, default=str)


@mcp.tool()
def get_observability_config() -> str:
    """Get current observability configuration.

    Returns:
        JSON string with high-level tracing configuration (sensitive fields redacted).
    """
    from claim_agent.observability.tracing import TracingConfig

    config = TracingConfig.from_env()
    return json.dumps({
        "langsmith_enabled": config.langsmith_enabled,
        "trace_llm_calls": config.trace_llm_calls,
        "trace_tool_calls": config.trace_tool_calls,
    })


def main() -> None:
    """Run the MCP server with stdio transport (default)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
