# Pilot Data Seeding

## Overview

The `seed_pilot_data.py` script generates realistic, anonymized historical claims for pilot demonstrations and testing. It creates a diverse dataset suitable for:

- **Duplicate detection validation**: Multiple claims on the same VIN with similar dates
- **Reporting and analytics**: Claim volume trends, type distribution, status tracking
- **Fraud pattern detection**: Multiple claims on the same vehicle over time
- **Realistic claim lifecycle**: Open, closed, disputed, and under-investigation claims

## Usage

### Basic Usage

```bash
python scripts/seed_pilot_data.py
```

This generates 100 historical claims spanning 6 months and seeds them into `data/claims.db`.

### Options

```bash
python scripts/seed_pilot_data.py [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--count N` | Number of historical claims to generate | 100 |
| `--months M` | Months of historical data to generate | 6 |
| `--db-path PATH` | Path to SQLite database | `data/claims.db` |
| `--clean` | Delete existing claims before seeding | `false` |
| `--seed N` | Optional RNG seed for reproducible generation | (none) |

### Examples

**Generate 200 claims spanning 12 months:**
```bash
python scripts/seed_pilot_data.py --count 200 --months 12
```

**Clean reset with fresh pilot data:**
```bash
python scripts/seed_pilot_data.py --clean
```

**Custom database path:**
```bash
python scripts/seed_pilot_data.py --db-path /path/to/custom.db --count 150
```

## Data Characteristics

### Claim Status Distribution

The script generates claims with realistic status distribution:

| Status | Percentage | Description |
|--------|------------|-------------|
| `closed` | 60% | Completed claims with payouts |
| `settled` | 15% | Settled claims |
| `pending` | 10% | Claims awaiting processing |
| `needs_review` | 5% | Claims requiring human review |
| `disputed` | 5% | Disputed claims |
| `under_investigation` | 3% | Claims under investigation |
| `denied` | 2% | Denied claims |

### Claim Type Distribution

| Type | Percentage | Description |
|------|------------|-------------|
| `partial_loss` | 50% | Minor to moderate vehicle damage |
| `new` | 20% | New/unclassified claims |
| `total_loss` | 10% | Vehicle declared total loss |
| `bodily_injury` | 8% | Claims involving injuries |
| `fraud` | 5% | Suspected fraud cases |
| `duplicate` | 5% | Duplicate submissions |
| `reopened` | 2% | Previously closed claims reopened |

### Realistic Features

1. **Incident Descriptions**: Type-appropriate narratives (e.g., "Rear-ended at stoplight" for partial loss)
2. **Damage Patterns**: Realistic damage descriptions matching incident types
3. **Financial Data**: Estimated damage and payout amounts based on claim type and severity
4. **Date Distribution**: Claims spread across the specified time range
5. **Duplicate Scenarios**: Multiple claims on the same VIN for testing duplicate detection
6. **Policy Coverage**: Claims linked to active policies from `mock_db.json`

## Data Sources

The script uses `data/mock_db.json` for:
- Active policy numbers
- Vehicle information (VIN, make, model, year)
- Policy-vehicle relationships

### Required Environment

- `MOCK_DB_PATH`: Path to mock_db.json (default: `data/mock_db.json`)
- `CLAIMS_DB_PATH`: Path to claims database (default: `data/claims.db`)

## Integration with Existing Scripts

### Comparison with `seed_claims_from_mock_db.py`

| Feature | `seed_claims_from_mock_db.py` | `seed_pilot_data.py` |
|---------|-------------------------------|----------------------|
| Data source | Existing claims in mock_db.json | Generated realistic claims |
| Claim count | Fixed (~30 claims) | Configurable (default: 100) |
| Date range | Pre-defined dates | Configurable historical range |
| Status variety | Limited | Full lifecycle representation |
| Duplicate scenarios | Minimal | Intentional duplicates for testing |
| Use case | Quick test data | Pilot demonstrations, analytics |

### Recommended Workflow

For pilot environments:
1. Start with `seed_pilot_data.py` for historical baseline
2. Use `seed_claims_from_mock_db.py` for additional test scenarios
3. Process live claims via API or CLI

## Output Example

```
Generating 100 pilot claims spanning 6 months...
Loaded 25 policy-vehicle pairs from mock_db.json

=== Pilot Data Summary ===
Total claims: 100

Status distribution:
  closed              :  60 ( 60.0%)
  settled             :  15 ( 15.0%)
  pending             :  10 ( 10.0%)
  needs_review        :   5 (  5.0%)
  disputed            :   5 (  5.0%)
  under_investigation :   3 (  3.0%)
  denied              :   2 (  2.0%)

Claim type distribution:
  partial_loss        :  50 ( 50.0%)
  new                 :  20 ( 20.0%)
  total_loss          :  10 ( 10.0%)
  bodily_injury       :   8 (  8.0%)
  fraud               :   5 (  5.0%)
  duplicate           :   5 (  5.0%)
  reopened            :   2 (  2.0%)

Incident date range: 2025-09-27 to 2026-03-27

Payouts: 75 claims, avg $5,234.67

Seeding to database: data/claims.db
Seeded 100 pilot claims into data/claims.db (0 skipped/existing).

✓ Pilot data seeding complete!
```

## Validation

After seeding, verify the data:

```bash
# Check claim distribution
sqlite3 data/claims.db "SELECT claim_type, COUNT(*) FROM claims GROUP BY claim_type"

# Find VINs with multiple claims (duplicate detection)
sqlite3 data/claims.db "SELECT vin, COUNT(*) as cnt FROM claims GROUP BY vin HAVING cnt > 1"

# Check date range
sqlite3 data/claims.db "SELECT MIN(incident_date), MAX(incident_date) FROM claims"

# Status breakdown
sqlite3 data/claims.db "SELECT status, COUNT(*) FROM claims GROUP BY status"
```

## Anonymization

All generated data is synthetic and anonymized:
- **Names**: No PII; uses policy numbers from mock_db.json
- **VINs**: Test VINs from mock_db.json (not real vehicles)
- **Amounts**: Randomly generated within realistic ranges
- **Dates**: Relative to current date minus configurable months

## Production Considerations

**Do not use this script in production.** It is designed for:
- Pilot demonstrations
- Development and testing
- Performance testing with realistic data volumes
- Training and onboarding

For production data migration, use Alembic migrations and proper ETL processes.

## Troubleshooting

### "No active policy-vehicle pairs found"
- Ensure `data/mock_db.json` exists and contains active policies
- Check `MOCK_DB_PATH` environment variable

### "No such table: claims"
- The script auto-creates the claims table if missing
- For full schema, run `alembic upgrade head` before seeding

### Duplicate claim IDs
- Use `--clean` flag to reset database
- Or generate with a different prefix (modify `_generate_claim_id()` if needed)

## Advanced Usage

### Seeding Multiple Environments

```bash
# Dev environment (small dataset)
python scripts/seed_pilot_data.py --count 50 --months 3 --db-path data/claims_dev.db --clean

# Staging environment (medium dataset)
python scripts/seed_pilot_data.py --count 200 --months 6 --db-path data/claims_staging.db --clean

# Load testing (large dataset)
python scripts/seed_pilot_data.py --count 1000 --months 12 --db-path data/claims_load.db --clean
```

### Custom Distributions

To adjust claim type or status distributions, edit the `CLAIM_STATUSES` and `CLAIM_TYPES` tuples in the script:

```python
CLAIM_STATUSES = [
    ("closed", 0.70),    # 70% closed
    ("pending", 0.20),   # 20% pending
    ("disputed", 0.10),  # 10% disputed
]
```

## See Also

- [Architecture Overview](architecture.md)
- [Database Schema](database.md)
- [Testing Guide](../README.md#testing)
- [Common Tasks](../README.md#common-tasks)
