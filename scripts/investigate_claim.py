#!/usr/bin/env python3
"""Investigate why a claim needs review. Usage: python scripts/investigate_claim.py CLM-XXXXXXXX"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from claim_agent.config.settings import get_escalation_config, get_router_config
from claim_agent.db.database import get_db_path, get_connection, row_to_dict


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/investigate_claim.py CLM-XXXXXXXX")
        return 1

    claim_id = sys.argv[1].strip()
    db_path = get_db_path()

    with get_connection(db_path) as conn:
        row = conn.execute(
            text("SELECT * FROM claims WHERE id = :claim_id"),
            {"claim_id": claim_id},
        ).fetchone()
        if not row:
            print(f"Claim {claim_id} not found in database.")
            print(f"DB path: {db_path}")
            return 1

        claim = row_to_dict(row)
        history = conn.execute(
            text(
                "SELECT id, action, old_status, new_status, details, actor_id, created_at "
                "FROM claim_audit_log WHERE claim_id = :claim_id ORDER BY id ASC"
            ),
            {"claim_id": claim_id},
        ).fetchall()
        workflows = conn.execute(
            text("SELECT * FROM workflow_runs WHERE claim_id = :claim_id ORDER BY id ASC"),
            {"claim_id": claim_id},
        ).fetchall()

    print("=" * 60)
    print(f"CLAIM: {claim_id}")
    print("=" * 60)
    print(f"Status: {claim.get('status')}")
    print(f"Claim type: {claim.get('claim_type')}")
    print(f"Priority: {claim.get('priority')}")
    print(f"Estimated damage: {claim.get('estimated_damage')}")
    print(f"Payout: {claim.get('payout_amount')}")
    print()

    print("--- AUDIT LOG ---")
    for h in history:
        d = row_to_dict(h)
        details = (d.get("details") or "")[:200]
        if len(str(d.get("details") or "")) > 200:
            details += "..."
        print(f"  {d.get('created_at')} | {d.get('action')} | {d.get('old_status')} -> {d.get('new_status')} | {details}")

    print()
    print("--- WORKFLOW RUNS ---")
    for wf in workflows:
        w = row_to_dict(wf)
        print(f"  Type: {w.get('claim_type')} | Created: {w.get('created_at')}")
        if w.get("workflow_output"):
            try:
                out = json.loads(w["workflow_output"])
                if isinstance(out, dict):
                    reasons = out.get("escalation_reasons", [])
                    priority = out.get("priority")
                    fraud = out.get("fraud_indicators", [])
                    if reasons or fraud:
                        print(f"    Escalation reasons: {reasons}")
                        print(f"    Priority: {priority}")
                        print(f"    Fraud indicators: {fraud}")
            except json.JSONDecodeError:
                print(f"    Output (raw): {str(w['workflow_output'])[:300]}...")

    print()
    print("--- ESCALATION CONFIG (what triggers needs_review) ---")
    esc = get_escalation_config()
    router = get_router_config()
    print(f"  confidence_threshold: {esc['confidence_threshold']} (router below this -> low_confidence)")
    print(f"  high_value_threshold: ${esc['high_value_threshold']:,.0f} (estimated_damage >= this -> high_value)")
    print(f"  similarity_ambiguous_range: {esc['similarity_ambiguous_range']} (score in range -> ambiguous_similarity)")
    print(f"  use_agent: {esc.get('use_agent', True)} (True=LLM escalation crew, False=rules only)")
    print(f"  Router confidence_threshold: {router.get('confidence_threshold', 0.7)}")

    print()
    print("--- RULES-BASED TRIGGERS (evaluate_escalation_impl) ---")
    est = claim.get("estimated_damage")
    if est is not None:
        try:
            est_f = float(est)
            high = est_f >= esc["high_value_threshold"]
            print(f"  estimated_damage={est_f} >= {esc['high_value_threshold']} -> high_value: {high}")
        except (ValueError, TypeError):
            pass
    print(f"  low_confidence: triggered when router_confidence < {esc['confidence_threshold']} (escalation.confidence_threshold; keyword-based only if router_confidence is missing)")
    print(f"  ambiguous_similarity: duplicate_detection similarity in configured range {esc['similarity_ambiguous_range']}")
    print("  fraud_suspected: fraud detectors return any indicator (keywords, description overlap, etc.)")

    print()
    print("--- MOCK CREW vs PROCESSING ---")
    print("  Mock crew (claim_generator): Only generates claim INPUT (incident/damage text). Does NOT set needs_review.")
    print("  Escalation crew: LLM agent that decides needs_review. Used when use_agent=True.")
    print("  Rules fallback: evaluate_escalation_impl runs when crew disabled or fails.")
    print("  Mid-workflow: Any crew can call escalate_claim tool -> needs_review.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
