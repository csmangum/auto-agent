"""MCP server exposing claim tools via stdio transport."""

from mcp.server.fastmcp import FastMCP

from claim_agent.tools.logic import (
    query_policy_db_impl,
    search_claims_db_impl,
    compute_similarity_impl,
    fetch_vehicle_value_impl,
    evaluate_damage_impl,
    generate_report_impl,
    generate_claim_id_impl,
)

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


def main() -> None:
    """Run the MCP server with stdio transport (default)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
