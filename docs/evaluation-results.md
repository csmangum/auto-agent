# Claim Processing Evaluation Results


## Summary

| Metric | Value |
|--------|--------|
| **Total scenarios** | 37 |
| **Successful runs** | 37 |
| **Overall classification accuracy** | **86.5%** |
| **Total latency** | 186,157 ms (~3.1 min) |
| **Average latency** | 5,031 ms per scenario |
| **Total tokens** | **120,134** |
| **Total cost** | **$0.0214** |

All scenarios completed without runtime errors. Token count and cost are wired from CrewAI LLM usage (see `main_crew._record_crew_llm_usage`). Five scenarios were misclassified in this run.

---

## Evaluation Scenarios

Scenarios are synthetic claims with a known **expected type**. The system routes each claim through the main crew; accuracy is measured by whether the **actual** claim type matches the expected one. Scenarios are grouped by intent.

### Scenario groups

| Group | Purpose |
|-------|--------|
| **new** | Claims that need intake/assessment before classification (e.g. unclear damage). |
| **duplicate** | Claims that should be detected as duplicates of an existing claim (same VIN, same/similar incident). |
| **total_loss** | Catastrophic or economic total loss (flood, fire, rollover, frame damage, or repair cost > 75% of value). |
| **fraud** | Claims with fraud indicators (staged accident, inflated estimate, suspicious timing, multiple red flags). |
| **partial_loss** | Repairable damage: fender benders, bumper/glass/panel damage, moderate multi-panel, etc. |
| **edge_cases** | Ambiguous damage, borderline total-loss threshold, minimal/high-value vehicles, inactive/expired policy, very old vehicle, mixed signals. |
| **escalation** | Claims that should still classify correctly but may trigger escalation (high payout, disputed liability, complex/uninsured). |
| **stress_test** | Unusual inputs: very long or minimal descriptions, special characters, numeric copy, conflicting incident vs damage text. |

### Scenario list (by group)

- **new** (2): `new_first_claim_unclear_damage`, `new_weather_related` (hail → partial_loss).
- **duplicate** (3): `duplicate_same_vin_date`, `duplicate_similar_description`, `duplicate_close_date` (date one day off).
- **total_loss** (5): `total_loss_flood`, `total_loss_fire`, `total_loss_rollover`, `total_loss_frame_damage`, `total_loss_implied_by_cost`.
- **fraud** (4): `fraud_staged_accident`, `fraud_inflated_estimate`, `fraud_suspicious_timing`, `fraud_multiple_red_flags`.
- **partial_loss** (7): `partial_loss_basic_fender_bender`, `partial_loss_rear_bumper`, `partial_loss_fender`, `partial_loss_front_collision`, `partial_loss_door_damage`, `partial_loss_windshield`, `partial_loss_moderate_damage`.
- **edge_cases** (8): `edge_ambiguous_damage`, `edge_borderline_total_loss`, `edge_minimal_damage`, `edge_high_value_vehicle`, `edge_inactive_policy`, `edge_expired_policy`, `edge_very_old_vehicle`, `edge_mixed_signals_partial`.
- **escalation** (3): `escalation_high_payout`, `escalation_disputed_liability`, `escalation_complex_claim`.
- **stress_test** (5): `stress_very_long_description`, `stress_minimal_description`, `stress_special_characters`, `stress_numeric_description`, `stress_conflicting_signals`.

Total: **37** scenarios. Each scenario has a difficulty (`easy` / `medium` / `hard`) and tags; run `scripts/evaluate_claim_processing.py --list` to see full details.

---

## Accuracy by Expected Type

| Expected type | Correct | Total | Accuracy |
|---------------|---------|-------|----------|
| **new** | 3 | 3 | **100%** |
| **partial_loss** | 18 | 19 | 94.7% |
| **total_loss** | 7 | 8 | 87.5% |
| **duplicate** | 2 | 3 | 66.7% |
| **fraud** | 2 | 4 | 50.0% |

- **Strong:** `new` is perfect.
- **Good:** `partial_loss` at 94.7%, `total_loss` at 87.5%.
- **Needs work:** `duplicate` at 66.7%, `fraud` at 50%.

---

## Confusion Matrix (Expected → Actual)

| Expected \\ Actual | duplicate | fraud | new | partial_loss | total_loss |
|-------------------|-----------|-------|-----|--------------|------------|
| **duplicate** | 2 | 0 | 0 | 1 | 0 |
| **fraud** | 0 | 2 | 0 | 0 | 2 |
| **new** | 0 | 0 | 3 | 0 | 0 |
| **partial_loss** | 0 | 0 | 0 | 18 | 1 |
| **total_loss** | 0 | 0 | 0 | 1 | 7 |

Observations:

- **duplicate → partial_loss (1):** `duplicate_same_vin_date` classified as partial_loss.
- **fraud → total_loss (2):** `fraud_inflated_estimate`, `fraud_suspicious_timing` routed to total_loss.
- **partial_loss → total_loss (1):** `edge_mixed_signals_partial` routed to total_loss.
- **total_loss → partial_loss (1):** `edge_very_old_vehicle` routed to partial_loss.

---

## Misclassifications (5)

| Scenario | Expected | Actual | Notes |
|----------|----------|--------|--------|
| `duplicate_same_vin_date` | duplicate | partial_loss | Same VIN/date duplicate routed to partial_loss. |
| `fraud_inflated_estimate` | fraud | total_loss | Inflated estimate scenario routed to total_loss. |
| `fraud_suspicious_timing` | fraud | total_loss | Suspicious timing fraud routed to total_loss. |
| `edge_very_old_vehicle` | total_loss | partial_loss | Very old vehicle economic total routed to partial_loss. |
| `edge_mixed_signals_partial` | partial_loss | total_loss | Mixed signals repairable case routed to total_loss. |

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