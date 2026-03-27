"""Seed pilot data: realistic historical claims for duplicate detection and reporting.

This script generates a realistic set of historical claims spanning multiple months,
with various claim types, statuses, and scenarios useful for pilot demonstrations:
- Duplicate detection validation (same VIN, similar dates)
- Reporting and analytics (claim volume trends, type distribution)
- Fraud pattern detection (multiple claims on same vehicle)
- Realistic claim lifecycle examples (open, closed, disputed)

Run from project root:
    python scripts/seed_pilot_data.py [--count N] [--months M]

Options:
    --count N    Number of historical claims to generate (default: 100)
    --months M   Months of historical data to generate (default: 6)
    --db-path    Path to SQLite database (default: data/claims.db)
    --clean      Delete existing claims before seeding
    --seed N     Optional RNG seed for reproducible generation

Uses MOCK_DB_PATH (default data/mock_db.json) for policy and vehicle data.
Re-running with --clean will reset the database; without --clean, new claims are added.

Standalone: uses only stdlib + minimal dependencies for portability.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Project root (parent of scripts/)
_ROOT = Path(__file__).resolve().parent.parent

# Claim statuses with realistic distribution
CLAIM_STATUSES = [
    ("closed", 0.60),  # 60% closed
    ("settled", 0.15),  # 15% settled
    ("pending", 0.10),  # 10% pending
    ("needs_review", 0.05),  # 5% needs review
    ("disputed", 0.05),  # 5% disputed
    ("under_investigation", 0.03),  # 3% under investigation
    ("denied", 0.02),  # 2% denied
]

# Claim types with realistic distribution
CLAIM_TYPES = [
    ("partial_loss", 0.50),  # 50% partial loss
    ("new", 0.20),  # 20% new/unclassified
    ("total_loss", 0.10),  # 10% total loss
    ("bodily_injury", 0.08),  # 8% bodily injury
    ("fraud", 0.05),  # 5% fraud suspected
    ("duplicate", 0.05),  # 5% duplicates
    ("reopened", 0.02),  # 2% reopened
]

# Realistic incident descriptions by type
INCIDENT_TEMPLATES = {
    "partial_loss": [
        "Rear-ended at stoplight. {damage} damage.",
        "Minor fender bender in parking lot. {damage}.",
        "Side-swiped by another vehicle. {damage}.",
        "Low-speed collision at intersection. {damage}.",
        "Backed into stationary object. {damage}.",
        "Hit by shopping cart in parking lot. {damage}.",
        "Scraped against concrete pillar. {damage}.",
        "Door dent from adjacent vehicle. {damage}.",
        "Hail damage during storm. {damage}.",
        "Tree branch fell on vehicle. {damage}.",
    ],
    "total_loss": [
        "Major collision on highway. Frame damage. Vehicle declared total loss.",
        "Head-on collision. Airbags deployed. Total loss.",
        "Rollover accident. Roof crushed. Vehicle totaled.",
        "Vehicle totaled in flood. Water damage throughout.",
        "Fire spread from garage. Vehicle destroyed.",
        "Theft recovery. Vehicle found stripped. Not economically repairable.",
    ],
    "bodily_injury": [
        "Rear-end collision. Driver and passenger reported neck pain.",
        "T-bone accident at intersection. Driver sustained chest injuries.",
        "Low-speed impact. Passenger complained of back pain.",
        "Multi-vehicle pileup. Driver transported to hospital.",
    ],
    "fraud": [
        "Claimed theft from locked garage. No signs of forced entry.",
        "Damage pattern inconsistent with described accident.",
        "Multiple prior claims on record. SIU referral.",
        "Inflated repair estimate. Pre-existing damage noted.",
    ],
    "duplicate": [
        "Rear-ended at stoplight. Same incident as {related_claim}.",
        "Parking lot collision. Duplicate submission detected.",
    ],
    "reopened": [
        "Additional damage discovered after initial settlement.",
        "Claimant reported injury symptoms weeks after initial claim.",
    ],
}

# Damage descriptions
DAMAGE_PARTS = [
    "Front bumper scratch",
    "Rear bumper dent and scratch",
    "Side panel damage",
    "Hood dent",
    "Front fender crease",
    "Door dent and paint damage",
    "Quarter panel damage",
    "Headlight broken",
    "Taillight cracked",
    "Side mirror knocked off",
    "Windshield crack",
    "Trunk lid dent",
    "Grille damage",
]


def _get_mock_db_path() -> Path:
    """Get path to mock_db.json from environment or default."""
    path = os.environ.get("MOCK_DB_PATH")
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = _ROOT / p
        return p
    return _ROOT / "data" / "mock_db.json"


def _weighted_choice(choices: list[tuple[str, float]]) -> str:
    """Select from weighted choices (value, weight) tuples."""
    total = sum(w for _, w in choices)
    r = random.random() * total
    cumulative = 0.0
    for value, weight in choices:
        cumulative += weight
        if r <= cumulative:
            return value
    return choices[-1][0]


def _generate_claim_id(index: int, prefix: str = "CLM-PILOT") -> str:
    """Generate unique claim ID."""
    return f"{prefix}{index:05d}"


def _generate_incident_date(months_back: int) -> str:
    """Generate random incident date within the last N months."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months_back * 30)
    days_range = (end_date - start_date).days
    random_days = random.randint(0, days_range)
    incident_date = start_date + timedelta(days=random_days)
    return incident_date.strftime("%Y-%m-%d")


def _generate_incident_description(claim_type: str, claim_id: str) -> tuple[str, str]:
    """Generate realistic incident and damage descriptions."""
    templates = INCIDENT_TEMPLATES.get(claim_type, INCIDENT_TEMPLATES["partial_loss"])
    template = random.choice(templates)
    
    if claim_type == "duplicate":
        # For duplicates, reference would be to another claim (simplified for now)
        incident = template.format(related_claim="prior submission")
    elif claim_type in ("partial_loss", "new"):
        damage = random.choice(DAMAGE_PARTS)
        incident = template.format(damage=damage)
    else:
        incident = template
    
    # Generate damage description
    if claim_type == "total_loss":
        damage_desc = "Vehicle total loss. Not economically repairable."
    elif claim_type == "bodily_injury":
        damage_desc = f"{random.choice(DAMAGE_PARTS)}. {random.choice(['Minor', 'Moderate', 'Significant'])} vehicle damage."
    else:
        damage_desc = random.choice(DAMAGE_PARTS)
    
    return incident, damage_desc


def _generate_estimated_damage(claim_type: str) -> float | None:
    """Generate realistic estimated damage amount."""
    if claim_type == "total_loss":
        return random.uniform(15000, 50000)
    elif claim_type == "partial_loss":
        return random.uniform(500, 8000)
    elif claim_type == "bodily_injury":
        return random.uniform(2000, 25000)
    elif claim_type == "fraud":
        # Fraud claims tend to have inflated estimates
        return random.uniform(5000, 20000)
    else:
        return random.uniform(1000, 5000)


def _generate_payout_amount(estimated: float | None, status: str) -> float | None:
    """Generate realistic payout based on estimate and status."""
    if status not in ("closed", "settled"):
        return None
    if estimated is None:
        return None
    # Payout is typically 70-100% of estimate
    return round(estimated * random.uniform(0.70, 1.0), 2)


def load_mock_data() -> dict[str, Any]:
    """Load mock_db.json for policy and vehicle data."""
    mock_path = _get_mock_db_path()
    if not mock_path.exists():
        raise FileNotFoundError(f"Mock DB not found: {mock_path}")
    
    with open(mock_path, encoding="utf-8") as f:
        return json.load(f)


def extract_policy_vehicle_pairs(db: dict[str, Any]) -> list[tuple[str, dict]]:
    """Extract (policy_number, vehicle) pairs from mock_db."""
    policies = db.get("policies", {})
    policy_vehicles = db.get("policy_vehicles", {})
    
    pairs = []
    for pol_num, pol_data in policies.items():
        if pol_data.get("status") != "active":
            continue
        vehicles = policy_vehicles.get(pol_num, [])
        for vehicle in vehicles:
            pairs.append((pol_num, vehicle))
    
    if not pairs:
        raise ValueError("No active policy-vehicle pairs found in mock_db.json")
    
    return pairs


def generate_pilot_claims(count: int, months_back: int, policy_vehicle_pairs: list) -> list[dict]:
    """Generate N realistic historical claims."""
    claims = []
    
    # Track VINs for duplicate detection scenarios
    used_vins = []
    
    for i in range(count):
        claim_id = _generate_claim_id(i + 1)
        claim_type = _weighted_choice(CLAIM_TYPES)
        status = _weighted_choice(CLAIM_STATUSES)
        
        # Select random policy-vehicle pair
        policy_num, vehicle = random.choice(policy_vehicle_pairs)
        vin = vehicle.get("vin", "UNKNOWN")
        
        # For duplicate scenarios, occasionally reuse a VIN with a similar date
        if claim_type == "duplicate" and used_vins and random.random() < 0.7:
            vin = random.choice(used_vins)
        else:
            used_vins.append(vin)
        
        incident_date = _generate_incident_date(months_back)
        incident_desc, damage_desc = _generate_incident_description(claim_type, claim_id)
        estimated = _generate_estimated_damage(claim_type)
        payout = _generate_payout_amount(estimated, status)
        
        claim = {
            "id": claim_id,
            "policy_number": policy_num,
            "vin": vin,
            "vehicle_year": vehicle.get("vehicle_year"),
            "vehicle_make": vehicle.get("vehicle_make"),
            "vehicle_model": vehicle.get("vehicle_model"),
            "incident_date": incident_date,
            "incident_description": incident_desc,
            "damage_description": damage_desc,
            "estimated_damage": estimated,
            "claim_type": claim_type,
            "status": status,
            "payout_amount": payout,
        }
        claims.append(claim)
    
    return claims


def seed_claims_to_db(claims: list[dict], db_path: str, clean: bool = False) -> None:
    """Insert claims into SQLite database."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        # Ensure claims table exists (minimal schema for seeding)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                policy_number TEXT NOT NULL,
                vin TEXT NOT NULL,
                vehicle_year INTEGER,
                vehicle_make TEXT,
                vehicle_model TEXT,
                incident_date TEXT,
                incident_description TEXT,
                damage_description TEXT,
                estimated_damage REAL,
                claim_type TEXT,
                status TEXT DEFAULT 'pending',
                payout_amount REAL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        if clean:
            print(f"Cleaning existing claims from {db_path}...")
            conn.execute("DELETE FROM claims")
            conn.commit()
        
        inserted = 0
        skipped = 0
        
        for claim in claims:
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO claims (
                        id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                        incident_date, incident_description, damage_description,
                        estimated_damage, claim_type, status, payout_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim["id"],
                        claim["policy_number"],
                        claim["vin"],
                        claim["vehicle_year"],
                        claim["vehicle_make"],
                        claim["vehicle_model"],
                        claim["incident_date"],
                        claim["incident_description"],
                        claim["damage_description"],
                        claim["estimated_damage"],
                        claim["claim_type"],
                        claim["status"],
                        claim["payout_amount"],
                    ),
                )
                # rowcount is per-statement (conn.total_changes is cumulative and breaks counting).
                if (cur.rowcount or 0) > 0:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                print(f"Error inserting claim {claim['id']}: {e}")
                skipped += 1
        
        conn.commit()
    
    print(f"Seeded {inserted} pilot claims into {db_path} ({skipped} skipped/existing).")


def print_summary(claims: list[dict]) -> None:
    """Print summary statistics of generated claims."""
    print("\n=== Pilot Data Summary ===")
    print(f"Total claims: {len(claims)}")
    
    # Status distribution
    status_counts: dict[str, int] = {}
    for claim in claims:
        status = claim.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print("\nStatus distribution:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        pct = (count / len(claims)) * 100
        print(f"  {status:20s}: {count:3d} ({pct:5.1f}%)")
    
    # Type distribution
    type_counts: dict[str, int] = {}
    for claim in claims:
        ctype = claim.get("claim_type", "unknown")
        type_counts[ctype] = type_counts.get(ctype, 0) + 1
    
    print("\nClaim type distribution:")
    for ctype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = (count / len(claims)) * 100
        print(f"  {ctype:20s}: {count:3d} ({pct:5.1f}%)")
    
    # Date range
    dates = [claim["incident_date"] for claim in claims if claim.get("incident_date")]
    if dates:
        print(f"\nIncident date range: {min(dates)} to {max(dates)}")
    
    # Payout statistics
    payouts = [claim["payout_amount"] for claim in claims if claim.get("payout_amount")]
    if payouts:
        avg_payout = sum(payouts) / len(payouts)
        print(f"\nPayouts: {len(payouts)} claims, avg ${avg_payout:,.2f}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Seed pilot data with realistic historical claims"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of historical claims to generate (default: 100)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Months of historical data to generate (default: 6)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: data/claims.db from env/config)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing claims before seeding",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Optional RNG seed for reproducible claim generation (tests / demos)",
    )
    args = parser.parse_args()
    
    if args.seed is not None:
        random.seed(args.seed)
    
    # Determine database path
    db_path = args.db_path
    if not db_path:
        db_path = os.environ.get("CLAIMS_DB_PATH", "data/claims.db")
        if not Path(db_path).is_absolute():
            db_path = str(_ROOT / db_path)
    
    print(f"Generating {args.count} pilot claims spanning {args.months} months...")
    
    # Load mock data
    mock_db = load_mock_data()
    policy_vehicle_pairs = extract_policy_vehicle_pairs(mock_db)
    print(f"Loaded {len(policy_vehicle_pairs)} policy-vehicle pairs from mock_db.json")
    
    # Generate claims
    claims = generate_pilot_claims(args.count, args.months, policy_vehicle_pairs)
    
    # Print summary
    print_summary(claims)
    
    # Seed to database
    print(f"\nSeeding to database: {db_path}")
    seed_claims_to_db(claims, db_path, clean=args.clean)
    
    print("\n✓ Pilot data seeding complete!")


if __name__ == "__main__":
    main()
