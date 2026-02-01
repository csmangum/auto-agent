# Claim Processing Evaluation Results

**Run:** 2026-02-01  
**Report source:** `evaluation_report.json`  
**Script:** `scripts/evaluate_claim_processing.py --all --verbose --output evaluation_report.json`

---

## Summary

| Metric | Value |
|--------|--------|
| **Total scenarios** | 37 |
| **Successful runs** | 37 |
| **Overall classification accuracy** | **86.5%** |
| **Total latency** | 212,545 ms (~3.5 min) |
| **Average latency** | 5,744 ms per scenario |
| **Total tokens** | 0 (metrics not wired in eval path) |
| **Total cost** | $0.00 |

All scenarios completed without runtime errors. Five scenarios were misclassified.

---

## Accuracy by Expected Type

| Expected type | Correct | Total | Accuracy |
|---------------|---------|-------|----------|
| **new** | 3 | 3 | **100%** |
| **fraud** | 4 | 4 | **100%** |
| **partial_loss** | 18 | 19 | 94.7% |
| **duplicate** | 2 | 3 | 66.7% |
| **total_loss** | 5 | 8 | 62.5% |

- **Strong:** `new` and `fraud` are perfect.
- **Good:** `partial_loss` at 94.7%.
- **Needs work:** `duplicate` (66.7%) and `total_loss` (62.5%).

---

## Confusion Matrix (Expected → Actual)

| Expected \\ Actual | duplicate | fraud | new | partial_loss | total_loss |
|--------------------|-----------|-------|-----|--------------|------------|
| **duplicate** | 2 | 0 | 0 | 1 | 0 |
| **fraud** | 0 | 4 | 0 | 0 | 0 |
| **new** | 0 | 0 | 3 | 0 | 0 |
| **partial_loss** | 0 | 0 | 0 | 18 | 1 |
| **total_loss** | 0 | 3 | 0 | 0 | 5 |

Observations:

- **duplicate → partial_loss (1):** `duplicate_close_date` classified as partial_loss (tighter duplicate criteria may have excluded it).
- **partial_loss → total_loss (1):** One partial-loss case routed to total_loss.
- **total_loss → fraud (3):** Three total-loss scenarios (rollover, very old vehicle, conflicting signals) classified as fraud, likely due to pre-routing fraud indicators or high damage-to-value ratio.

---

## Misclassifications (5)

| Scenario | Expected | Actual | Notes |
|----------|----------|--------|--------|
| `duplicate_close_date` | duplicate | partial_loss | Close date match not treated as duplicate (days_difference &gt; 3 or description mismatch). |
| `total_loss_rollover` | total_loss | fraud | Rollover case triggered fraud path (e.g. high damage-to-value). |
| `edge_very_old_vehicle` | total_loss | fraud | 2005 Cavalier; economic total but also flagged as fraud. |
| `escalation_disputed_liability` | partial_loss | total_loss | Disputed liability case routed to total_loss. |
| `stress_conflicting_signals` | total_loss | fraud | Conflicting damage signals routed to fraud. |

---

## Post-Implementation Notes

Recommendations from the previous run were implemented:

1. **Duplicate vs partial_loss:** Router now requires BOTH `days_difference <= 3` AND nearly identical incident/description; high_value_claim and different damage types reduce duplicate classification. One duplicate scenario now classifies as partial_loss.
2. **Economic total loss:** Pre-routing `_check_economic_total_loss()` injects `is_economic_total_loss`; router uses it for total_loss. `total_loss_implied_by_cost` and similar cases now classify correctly.
3. **Fraud vs total_loss:** Pre-routing fraud indicators for high damage-to-value; router stresses inflated estimate without catastrophic event as fraud. Some total-loss cases (rollover, old vehicle, conflicting signals) now route to fraud when indicators fire.
4. **Escalation / high-value:** `high_value_claim` flag set for high damage/value; router advised not to classify as duplicate without strong evidence.
5. **Observability:** `LiteLLMTracingCallback` inherits from LiteLLM `CustomLogger`. Token/cost still show 0 in this report—eval may use a path where callbacks are not invoked, or usage is not yet plumbed into the report.

---

## How to Re-run

```bash
# Activate venv and run full evaluation
.venv/bin/python scripts/evaluate_claim_processing.py --all --verbose --output evaluation_report.json

# Compare to this run
.venv/bin/python scripts/evaluate_claim_processing.py --all --output evaluation_report_new.json --compare evaluation_report.json
```

Full per-scenario details (latency, claim_id, status) are in `evaluation_report.json`.
