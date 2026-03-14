"""Read-only tool functions for the chat agent.

Each function accesses claims data, policies, configuration, etc. and returns
a JSON-serializable dict.  The companion ``TOOL_DEFINITIONS`` list provides
OpenAI-compatible function schemas for litellm's ``tools`` parameter.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from claim_agent.config.settings import (
    get_escalation_config,
    get_fraud_config,
)
from claim_agent.data.loader import load_mock_db
from claim_agent.db.database import get_connection, get_db_path
from claim_agent.db.repository import ClaimRepository

logger = logging.getLogger(__name__)


def _get_repo(db_path: str | None = None) -> ClaimRepository:
    return ClaimRepository(db_path=db_path)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def lookup_claim(claim_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Look up a single claim by ID.  Returns claim data or an error message."""
    repo = _get_repo(db_path)
    claim = repo.get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim not found: {claim_id}"}
    # Strip large blob fields for concise context
    result = dict(claim)
    if "attachments" in result:
        try:
            atts = json.loads(result["attachments"]) if isinstance(result["attachments"], str) else result["attachments"]
            result["attachment_count"] = len(atts) if atts else 0
        except (json.JSONDecodeError, TypeError):
            result["attachment_count"] = 0
        del result["attachments"]
    return result


def search_claims(
    *,
    status: str | None = None,
    claim_type: str | None = None,
    limit: int = 10,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Search claims with optional filters.  Returns a list and total count."""
    conditions: list[str] = []
    params: list[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if claim_type:
        conditions.append("claim_type = ?")
        params.append(claim_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    effective_limit = min(max(limit, 1), 50)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        total = conn.execute(f"SELECT COUNT(*) as cnt FROM claims {where}", params).fetchone()["cnt"]
        rows = conn.execute(
            f"SELECT id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, "
            f"claim_type, status, estimated_damage, payout_amount, created_at "
            f"FROM claims {where} ORDER BY created_at DESC LIMIT ?",
            params + [effective_limit],
        ).fetchall()
    return {
        "total": total,
        "showing": len(rows),
        "claims": [dict(r) for r in rows],
    }


def get_claim_history(claim_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Get audit log for a claim."""
    repo = _get_repo(db_path)
    claim = repo.get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim not found: {claim_id}"}
    history, total = repo.get_claim_history(claim_id, limit=30)
    return {"claim_id": claim_id, "total_events": total, "history": history}


def get_claim_notes(claim_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Get notes for a claim."""
    repo = _get_repo(db_path)
    claim = repo.get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim not found: {claim_id}"}
    notes = repo.get_notes(claim_id)
    return {"claim_id": claim_id, "notes": notes}


def get_claims_stats(*, db_path: str | None = None) -> dict[str, Any]:
    """Get aggregate claims statistics."""
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM claims").fetchone()["cnt"]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt "
                "FROM claims GROUP BY status ORDER BY cnt DESC"
            ).fetchall()
        }
        by_type = {
            r["claim_type"]: r["cnt"]
            for r in conn.execute(
                "SELECT COALESCE(claim_type, 'unclassified') as claim_type, COUNT(*) as cnt "
                "FROM claims GROUP BY claim_type ORDER BY cnt DESC"
            ).fetchall()
        }
    return {"total_claims": total, "by_status": by_status, "by_type": by_type}


def get_system_config() -> dict[str, Any]:
    """Get current escalation and fraud configuration."""
    return {
        "escalation": get_escalation_config(),
        "fraud": get_fraud_config(),
    }


def lookup_policy(policy_number: str) -> dict[str, Any]:
    """Look up a policy by number from mock data."""
    db = load_mock_db()
    policies = db.get("policies", {})
    policy = policies.get(policy_number)
    if policy is None:
        return {"error": f"Policy not found: {policy_number}"}
    vehicles = db.get("policy_vehicles", {}).get(policy_number, [])
    return {
        "policy_number": policy_number,
        **policy,
        "vehicles": vehicles,
    }


def explain_escalation(claim_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Gather context to explain why a claim was escalated (or not).

    Returns the claim data, relevant audit events, escalation config, and
    any workflow outputs that mention escalation.
    """
    repo = _get_repo(db_path)
    claim = repo.get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim not found: {claim_id}"}

    history, _ = repo.get_claim_history(claim_id, limit=50)
    escalation_events = [
        h for h in history
        if "escalat" in (h.get("action") or "").lower()
        or "escalat" in (h.get("details") or "").lower()
        or h.get("new_status") == "needs_review"
    ]

    esc_config = get_escalation_config()
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        wf_rows = conn.execute(
            "SELECT claim_type, workflow_output, created_at FROM workflow_runs "
            "WHERE claim_id = ? ORDER BY id ASC",
            (claim_id,),
        ).fetchall()
    workflow_outputs = []
    for wf in wf_rows:
        w = dict(wf)
        if w.get("workflow_output"):
            try:
                parsed = json.loads(w["workflow_output"])
                if isinstance(parsed, dict):
                    workflow_outputs.append(parsed)
            except (json.JSONDecodeError, TypeError):
                workflow_outputs.append({"raw": str(w["workflow_output"])[:500]})

    return {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claim_type": claim.get("claim_type"),
        "priority": claim.get("priority"),
        "estimated_damage": claim.get("estimated_damage"),
        "escalation_events": escalation_events,
        "workflow_outputs": workflow_outputs,
        "escalation_config": esc_config,
    }


def get_review_queue(*, limit: int = 10, db_path: str | None = None) -> dict[str, Any]:
    """Get claims currently in needs_review status."""
    repo = _get_repo(db_path)
    effective_limit = min(max(limit, 1), 50)
    claims, total = repo.list_claims_needing_review(limit=effective_limit)
    return {"total": total, "showing": len(claims), "claims": claims}


# ---------------------------------------------------------------------------
# Tool dispatcher – maps tool name → callable
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS: dict[str, Any] = {
    "lookup_claim": lookup_claim,
    "search_claims": search_claims,
    "get_claim_history": get_claim_history,
    "get_claim_notes": get_claim_notes,
    "get_claims_stats": get_claims_stats,
    "get_system_config": get_system_config,
    "lookup_policy": lookup_policy,
    "explain_escalation": explain_escalation,
    "get_review_queue": get_review_queue,
}


def execute_tool(name: str, arguments: dict[str, Any], *, db_path: str | None = None) -> str:
    """Execute a tool by name with arguments.  Returns JSON string."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        # Inject db_path for DB-backed tools
        import inspect
        sig = inspect.signature(fn)
        if "db_path" in sig.parameters:
            arguments = {**arguments, "db_path": db_path}
        result = fn(**arguments)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.exception("Tool %s failed: %s", name, exc)
        return json.dumps({"error": "Tool execution failed. Please try again or contact support."})


# ---------------------------------------------------------------------------
# OpenAI-compatible tool definitions for litellm
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_claim",
            "description": "Look up a specific claim by its claim ID (e.g. CLM-TEST001). Returns claim details including status, type, damage, payout, dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to look up (e.g. CLM-XXXXXXXX)",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_claims",
            "description": "Search and list claims with optional filters. Returns matching claims with summary info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by claim status (e.g. open, closed, pending, needs_review, fraud_suspected, processing, settled, denied, under_investigation)",
                    },
                    "claim_type": {
                        "type": "string",
                        "description": "Filter by claim type (e.g. new, duplicate, total_loss, fraud, partial_loss, bodily_injury)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results (1-50, default 10)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_claim_history",
            "description": "Get the audit log / event history for a claim. Shows status changes, actions taken, and timestamps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to get history for",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_claim_notes",
            "description": "Get notes attached to a claim by agents, crews, or adjusters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to get notes for",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_claims_stats",
            "description": "Get aggregate statistics: total claims count, breakdown by status, breakdown by type.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_config",
            "description": "Get current system configuration including escalation thresholds, fraud detection settings.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_policy",
            "description": "Look up an insurance policy by policy number. Returns coverage details and insured vehicles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_number": {
                        "type": "string",
                        "description": "The policy number to look up",
                    },
                },
                "required": ["policy_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_escalation",
            "description": "Investigate why a claim was escalated to needs_review (or not). Returns claim context, escalation-related audit events, workflow outputs, and the escalation configuration thresholds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to investigate",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_review_queue",
            "description": "List claims currently in the human review queue (status needs_review).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results (1-50, default 10)",
                    },
                },
                "required": [],
            },
        },
    },
]
