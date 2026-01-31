"""Load mock_db.json claims into SQLite so claim search and duplicate detection can see them.

Run from project root:
    python scripts/seed_claims_from_mock_db.py

Uses MOCK_DB_PATH (default data/mock_db.json) and CLAIMS_DB_PATH (default data/claims.db).
Re-running the script does not duplicate claims (INSERT OR IGNORE by claim id).

Standalone: uses only stdlib (json, os, pathlib, sqlite3) so it runs without installing
package dependencies.
"""

import json
import os
import sqlite3
from pathlib import Path

# Project root (parent of scripts/)
_ROOT = Path(__file__).resolve().parent.parent

# Same claims table schema as claim_agent.db.database
_SCHEMA_SQL = """
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
);
CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin);
CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date);
"""

# Active policy numbers for synthetic policy_number (mock claims don't include it)
_SEED_POLICY_NUMBERS = [f"POL-{i:03d}" for i in range(1, 21)]


def _get_mock_db_path() -> Path:
    path = os.environ.get("MOCK_DB_PATH")
    if path:
        return Path(path)
    return _ROOT / "data" / "mock_db.json"


def _get_db_path() -> str:
    path = os.environ.get("CLAIMS_DB_PATH", "data/claims.db")
    if not Path(path).is_absolute():
        path = str(_ROOT / path)
    return path


def main() -> None:
    mock_path = _get_mock_db_path()
    if not mock_path.exists():
        print(f"Mock DB not found: {mock_path}")
        return

    with open(mock_path, encoding="utf-8") as f:
        db = json.load(f)

    claims = db.get("claims", [])
    if not claims:
        print("No claims in mock_db.json; nothing to seed.")
        return

    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        inserted = 0
        skipped = 0

        for i, c in enumerate(claims):
            claim_id = c.get("claim_id") or c.get("id")
            if not claim_id:
                skipped += 1
                continue
            vin = c.get("vin", "")
            incident_date = c.get("incident_date", "")
            incident_description = c.get("incident_description", "")
            policy_number = _SEED_POLICY_NUMBERS[i % len(_SEED_POLICY_NUMBERS)]
            damage_description = c.get("damage_description") or incident_description or ""
            status = c.get("status", "closed")

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                    incident_date, incident_description, damage_description, estimated_damage,
                    claim_type, status, payout_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    policy_number,
                    vin,
                    None,
                    None,
                    None,
                    incident_date,
                    incident_description,
                    damage_description,
                    None,
                    None,
                    status,
                    None,
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1

        conn.commit()

    print(f"Seeded {inserted} claims into {db_path} ({skipped} already present or skipped).")


if __name__ == "__main__":
    main()
