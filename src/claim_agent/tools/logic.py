"""Shared logic for claim tools (used by both CrewAI tools and MCP server)."""

import json
import uuid

from claim_agent.tools.data_loader import load_mock_db


def query_policy_db_impl(policy_number: str) -> str:
    db = load_mock_db()
    policies = db.get("policies", {})
    if policy_number in policies:
        p = policies[policy_number]
        return (
            f'{{"valid": true, "coverage": "{p.get("coverage", "comprehensive")}", '
            f'"deductible": {p.get("deductible", 500)}, "status": "active"}}'
        )
    return '{"valid": false, "message": "Policy not found or inactive"}'


def search_claims_db_impl(vin: str, incident_date: str) -> str:
    db = load_mock_db()
    claims = db.get("claims", [])
    matches = [c for c in claims if c.get("vin") == vin and c.get("incident_date") == incident_date]
    return json.dumps(matches)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    a = description_a.lower().strip()
    b = description_b.lower().strip()
    if not a or not b:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    overlap = len(words_a & words_b) / len(words_a)
    score = min(100.0, overlap * 100.0)
    return json.dumps({"similarity_score": round(score, 2), "is_duplicate": score > 80.0})


def fetch_vehicle_value_impl(vin: str, year: int, make: str, model: str) -> str:
    db = load_mock_db()
    key = vin or f"{year}_{make}_{model}"
    values = db.get("vehicle_values", {})
    if key in values:
        v = values[key]
        return json.dumps({
            "value": v.get("value", 15000),
            "condition": v.get("condition", "good"),
            "source": "mock_kbb",
        })
    default_value = max(2000, 12000 + (2025 - year) * -500)
    return json.dumps({
        "value": default_value,
        "condition": "good",
        "source": "mock_kbb_estimated",
    })


def evaluate_damage_impl(damage_description: str, estimated_repair_cost: float | None) -> str:
    desc_lower = damage_description.lower()
    total_loss_keywords = ["totaled", "total loss", "destroyed", "flood", "fire", "frame"]
    is_total_loss_candidate = any(k in desc_lower for k in total_loss_keywords)
    cost = estimated_repair_cost if estimated_repair_cost is not None else 0.0
    return json.dumps({
        "severity": "high" if is_total_loss_candidate else "medium",
        "estimated_repair_cost": cost,
        "total_loss_candidate": is_total_loss_candidate,
    })


def generate_report_impl(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    report = {
        "report_id": str(uuid.uuid4()),
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": status,
        "summary": summary,
        "payout_amount": payout_amount,
    }
    return json.dumps(report)


def generate_claim_id_impl(prefix: str = "CLM") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
