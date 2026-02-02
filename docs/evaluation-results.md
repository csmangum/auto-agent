# Claim Processing Evaluation Results

**Latest run:** 2026-02-01 18:54:31  
**Report source:** `evaluation_report_20260201_185431.json`  
**Script:** `.venv/bin/python scripts/evaluate_claim_processing.py --all`

---

## Summary

| Metric | Value |
|--------|--------|
| **Total scenarios** | 37 |
| **Successful runs** | 37 |
| **Overall classification accuracy** | **94.6%** |
| **Total latency** | 172,601 ms (~2.9 min) |
| **Average latency** | 4,665 ms per scenario |
| **Total tokens** | 0 (metrics not wired in eval path) |
| **Total cost** | $0.00 |

All scenarios completed without runtime errors. Two scenarios were misclassified.

---

## Accuracy by Expected Type

| Expected type | Correct | Total | Accuracy |
|---------------|---------|-------|----------|
| **duplicate** | 3 | 3 | **100%** |
| **new** | 3 | 3 | **100%** |
| **partial_loss** | 19 | 19 | **100%** |
| **total_loss** | 7 | 8 | 87.5% |
| **fraud** | 3 | 4 | 75.0% |

- **Strong:** `duplicate`, `new`, and `partial_loss` are perfect.
- **Good:** `total_loss` at 87.5%.
- **Needs work:** `fraud` at 75% (one fraud case classified as total_loss).

---

## Confusion Matrix (Expected → Actual)

| Expected \\ Actual | duplicate | fraud | new | partial_loss | total_loss |
|-------------------|-----------|-------|-----|--------------|------------|
| **duplicate** | 3 | 0 | 0 | 0 | 0 |
| **fraud** | 0 | 3 | 0 | 0 | 1 |
| **new** | 0 | 0 | 3 | 0 | 0 |
| **partial_loss** | 0 | 0 | 0 | 19 | 0 |
| **total_loss** | 0 | 0 | 0 | 1 | 7 |

Observations:

- **fraud → total_loss (1):** `fraud_inflated_estimate` classified as total_loss (damage/economic signals may outweigh fraud indicators).
- **total_loss → partial_loss (1):** `edge_very_old_vehicle` classified as partial_loss (very old vehicle economic total may need stronger routing cues).

---

## Misclassifications (2)

| Scenario | Expected | Actual | Notes |
|----------|----------|--------|--------|
| `fraud_inflated_estimate` | fraud | total_loss | Inflated estimate scenario routed to total_loss. |
| `edge_very_old_vehicle` | total_loss | partial_loss | Very old vehicle (e.g. 2005 Cavalier) economic total routed to partial_loss. |

---

## How to Re-run

```bash
# Activate venv and run full evaluation
.venv/bin/python scripts/evaluate_claim_processing.py --all

# Save to a named report
.venv/bin/python scripts/evaluate_claim_processing.py --all --output evaluation_report.json

# Compare to a previous report
.venv/bin/python scripts/evaluate_claim_processing.py --all --output evaluation_report_new.json --compare evaluation_report_20260201_185431.json
```

Full per-scenario details (latency, claim_id, status) are in the JSON report file.

---

## Previous Run (for comparison)

Earlier run (2026-02-01, report `evaluation_report.json`) had **86.5%** overall accuracy with five misclassifications (duplicate → partial_loss, total_loss → fraud ×3, partial_loss → total_loss). Router and pre-routing changes (description_similarity_score, catastrophic vs explicit total-loss keywords, strictly cost-based `is_economic_total_loss`, duplicate rule grouping) improved accuracy to **94.6%** and reduced misclassifications to two.
