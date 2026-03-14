"""Tests for the chat agent tools (claim_agent.chat.tools)."""

import json
import pytest

from claim_agent.chat.tools import (
    TOOL_DEFINITIONS,
    TOOL_FUNCTIONS,
    execute_tool,
    explain_escalation,
    get_claim_history,
    get_claim_notes,
    get_claims_stats,
    get_review_queue,
    get_system_config,
    lookup_claim,
    lookup_policy,
    search_claims,
)


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all chat tool tests."""
    yield


# ---------------------------------------------------------------------------
# lookup_claim
# ---------------------------------------------------------------------------


class TestLookupClaim:
    def test_found(self, seeded_temp_db):
        result = lookup_claim("CLM-TEST001", db_path=seeded_temp_db)
        assert result["id"] == "CLM-TEST001"
        assert result["status"] == "open"
        assert result["policy_number"] == "POL-001"
        assert "attachments" not in result  # stripped
        assert "attachment_count" in result

    def test_not_found(self, seeded_temp_db):
        result = lookup_claim("CLM-NONEXISTENT", db_path=seeded_temp_db)
        assert "error" in result
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# search_claims
# ---------------------------------------------------------------------------


class TestSearchClaims:
    def test_all(self, seeded_temp_db):
        result = search_claims(db_path=seeded_temp_db)
        assert result["total"] >= 5
        assert len(result["claims"]) <= 10

    def test_filter_by_status(self, seeded_temp_db):
        result = search_claims(status="open", db_path=seeded_temp_db)
        assert result["total"] == 1
        assert result["claims"][0]["id"] == "CLM-TEST001"

    def test_filter_by_type(self, seeded_temp_db):
        result = search_claims(claim_type="fraud", db_path=seeded_temp_db)
        assert result["total"] == 1
        assert result["claims"][0]["id"] == "CLM-TEST003"

    def test_limit(self, seeded_temp_db):
        result = search_claims(limit=2, db_path=seeded_temp_db)
        assert len(result["claims"]) <= 2


# ---------------------------------------------------------------------------
# get_claim_history
# ---------------------------------------------------------------------------


class TestGetClaimHistory:
    def test_found(self, seeded_temp_db):
        result = get_claim_history("CLM-TEST001", db_path=seeded_temp_db)
        assert result["claim_id"] == "CLM-TEST001"
        assert result["total_events"] >= 1
        assert len(result["history"]) >= 1

    def test_not_found(self, seeded_temp_db):
        result = get_claim_history("CLM-NONEXISTENT", db_path=seeded_temp_db)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_claim_notes
# ---------------------------------------------------------------------------


class TestGetClaimNotes:
    def test_found(self, seeded_temp_db):
        result = get_claim_notes("CLM-TEST001", db_path=seeded_temp_db)
        assert result["claim_id"] == "CLM-TEST001"
        assert isinstance(result["notes"], list)

    def test_not_found(self, seeded_temp_db):
        result = get_claim_notes("CLM-NONEXISTENT", db_path=seeded_temp_db)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_claims_stats
# ---------------------------------------------------------------------------


class TestGetClaimsStats:
    def test_returns_stats(self, seeded_temp_db):
        result = get_claims_stats(db_path=seeded_temp_db)
        assert result["total_claims"] >= 5
        assert "by_status" in result
        assert "by_type" in result
        assert isinstance(result["by_status"], dict)
        assert isinstance(result["by_type"], dict)


# ---------------------------------------------------------------------------
# get_system_config
# ---------------------------------------------------------------------------


class TestGetSystemConfig:
    def test_returns_config(self):
        result = get_system_config()
        assert "escalation" in result
        assert "fraud" in result
        assert "confidence_threshold" in result["escalation"]
        assert "high_risk_threshold" in result["fraud"]


# ---------------------------------------------------------------------------
# lookup_policy
# ---------------------------------------------------------------------------


class TestLookupPolicy:
    def test_found(self):
        """Look up a policy that exists in mock_db.json."""
        # Get a known policy from mock_db
        from claim_agent.data.loader import load_mock_db
        db = load_mock_db()
        policies = db.get("policies", {})
        if not policies:
            pytest.skip("No policies in mock_db")
        policy_number = next(iter(policies))
        result = lookup_policy(policy_number)
        assert result["policy_number"] == policy_number
        assert "vehicles" in result

    def test_not_found(self):
        result = lookup_policy("NONEXISTENT-POLICY")
        assert "error" in result
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# explain_escalation
# ---------------------------------------------------------------------------


class TestExplainEscalation:
    def test_found(self, seeded_temp_db):
        result = explain_escalation("CLM-TEST004", db_path=seeded_temp_db)
        assert result["claim_id"] == "CLM-TEST004"
        assert result["status"] == "needs_review"
        assert "escalation_config" in result
        assert "escalation_events" in result

    def test_not_found(self, seeded_temp_db):
        result = explain_escalation("CLM-NONEXISTENT", db_path=seeded_temp_db)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_review_queue
# ---------------------------------------------------------------------------


class TestGetReviewQueue:
    def test_returns_queue(self, seeded_temp_db):
        result = get_review_queue(db_path=seeded_temp_db)
        assert "total" in result
        assert "claims" in result
        assert isinstance(result["claims"], list)


# ---------------------------------------------------------------------------
# Tool definitions schema validation
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    def test_all_tools_have_definitions(self):
        defined_names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
        function_names = set(TOOL_FUNCTIONS.keys())
        assert defined_names == function_names, (
            f"Mismatch: defined={defined_names}, functions={function_names}"
        )

    def test_schema_structure(self):
        for tool in TOOL_DEFINITIONS:
            assert tool["type"] == "function"
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            params = fn["parameters"]
            assert params["type"] == "object"
            assert "properties" in params


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    def test_known_tool(self, seeded_temp_db):
        result_str = execute_tool("get_claims_stats", {}, db_path=seeded_temp_db)
        result = json.loads(result_str)
        assert "total_claims" in result

    def test_unknown_tool(self):
        result_str = execute_tool("nonexistent_tool", {})
        result = json.loads(result_str)
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_tool_with_args(self, seeded_temp_db):
        result_str = execute_tool(
            "lookup_claim", {"claim_id": "CLM-TEST001"}, db_path=seeded_temp_db
        )
        result = json.loads(result_str)
        assert result["id"] == "CLM-TEST001"
