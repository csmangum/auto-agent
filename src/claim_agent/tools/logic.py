"""Shared logic for claim tools (used by both CrewAI tools and MCP server)."""

import json
import uuid
from datetime import datetime

from claim_agent.db.repository import ClaimRepository
from claim_agent.tools.data_loader import load_mock_db

# Vehicle valuation defaults (mock KBB)
DEFAULT_BASE_VALUE = 12000
DEPRECIATION_PER_YEAR = 500
MIN_VEHICLE_VALUE = 2000


def query_policy_db_impl(policy_number: str) -> str:
    if not policy_number or not isinstance(policy_number, str):
        return json.dumps({"valid": False, "message": "Invalid policy number"})
    policy_number = policy_number.strip()
    if not policy_number:
        return json.dumps({"valid": False, "message": "Empty policy number"})
    db = load_mock_db()
    policies = db.get("policies", {})
    if policy_number in policies:
        p = policies[policy_number]
        status = p.get("status", "active")
        is_active = isinstance(status, str) and status.lower() == "active"
        if is_active:
            return json.dumps({
                "valid": True,
                "coverage": p.get("coverage", "comprehensive"),
                "deductible": p.get("deductible", 500),
                "status": status,
            })
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})


def search_claims_db_impl(vin: str, incident_date: str) -> str:
    if not vin or not isinstance(vin, str) or not vin.strip():
        return json.dumps([])
    if not incident_date or not isinstance(incident_date, str) or not incident_date.strip():
        return json.dumps([])
    repo = ClaimRepository()
    matches = repo.search_claims(vin=vin.strip(), incident_date=incident_date.strip())
    # Return shape expected by tools: claim_id, vin, incident_date, incident_description
    out = [
        {
            "claim_id": c.get("id"),
            "vin": c.get("vin"),
            "incident_date": c.get("incident_date"),
            "incident_description": c.get("incident_description", ""),
        }
        for c in matches
    ]
    return json.dumps(out)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    a = description_a.lower().strip()
    b = description_b.lower().strip()
    if not a or not b:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    score = (intersection / union) * 100.0
    return json.dumps({"similarity_score": round(score, 2), "is_duplicate": score > 80.0})


def fetch_vehicle_value_impl(vin: str, year: int, make: str, model: str) -> str:
    vin = vin.strip() if isinstance(vin, str) else ""
    make = make.strip() if isinstance(make, str) else ""
    model = model.strip() if isinstance(model, str) else ""
    year_int = int(year) if isinstance(year, (int, float)) and year > 0 else 2020
    db = load_mock_db()
    key = vin or f"{year_int}_{make}_{model}"
    values = db.get("vehicle_values", {})
    if key in values:
        v = values[key]
        return json.dumps({
            "value": v.get("value", 15000),
            "condition": v.get("condition", "good"),
            "source": "mock_kbb",
        })
    current_year = datetime.now().year
    default_value = max(
        MIN_VEHICLE_VALUE,
        DEFAULT_BASE_VALUE + (current_year - year_int) * -DEPRECIATION_PER_YEAR,
    )
    return json.dumps({
        "value": default_value,
        "condition": "good",
        "source": "mock_kbb_estimated",
    })


def evaluate_damage_impl(damage_description: str, estimated_repair_cost: float | None) -> str:
    if not damage_description or not isinstance(damage_description, str):
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
    desc_lower = damage_description.strip().lower()
    if not desc_lower:
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
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
