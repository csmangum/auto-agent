"""Shared pytest fixtures for all test files."""

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv


class LogCaptureHandler(logging.Handler):
    """Capture log records for assertions. Use with the logger that emits the log."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]

# Load .env before any tests run (API keys, etc.). override=False so existing
# env vars (e.g. CLAIMS_DB_PATH from fixtures) are not overwritten.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

from claim_agent.db.database import get_connection, init_db


def _seed_test_data(db_path: str) -> None:
    """Insert test claims, audit log entries, and workflow runs for API tests."""
    with get_connection(db_path) as conn:
        # Claims
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST001", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord",
             "2025-01-15", "Rear-ended at stoplight", "Rear bumper damage", 2500.0,
             "new", "open"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST002", "POL-002", "5YJSA1E26HF123456", 2020, "Tesla", "Model 3",
             "2025-01-20", "Flash flood", "Vehicle submerged", 45000.0,
             "total_loss", "closed"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST003", "POL-003", "3VWDX7AJ5DM999999", 2019, "Volkswagen", "Jetta",
             "2025-01-22", "Staged accident", "Front bumper destroyed", 35000.0,
             "fraud", "fraud_suspected"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status, priority, due_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST004", "POL-004", "2HGFG3B54CH123456", 2022, "Toyota", "Camry",
             "2025-01-25", "Low confidence routing", "Minor scratch", 500.0,
             "new", "needs_review", "high", "2025-01-26T12:00:00Z"),
        )
        conn.execute(
            "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, "
            "vehicle_model, incident_date, incident_description, damage_description, "
            "estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CLM-TEST005", "POL-005", "2T1BURHE5JC073987", 2022, "Toyota", "Corolla",
             "2025-01-25", "Backed into pole", "Rear bumper cracked, taillight broken", 1800.0,
             "partial_loss", "processing"),
        )

        # Audit log entries (with actor_id, before_state, after_state for audit trail)
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "CLM-TEST001",
                "created",
                "pending",
                "Claim record created",
                "workflow",
                '{"status": "pending", "claim_type": null, "payout_amount": null}',
            ),
        )
        conn.execute(
            "INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "CLM-TEST001",
                "status_change",
                "pending",
                "open",
                "Processed successfully",
                "workflow",
                '{"status": "pending", "claim_type": null, "payout_amount": null}',
                '{"status": "open", "claim_type": "new", "payout_amount": null}',
            ),
        )

        # Workflow run
        conn.execute(
            "INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output) "
            "VALUES (?, ?, ?, ?)",
            ("CLM-TEST001", "new", "new\nFirst-time claim", "Claim assigned and opened"),
        )
        # Partial loss workflow run (for supplemental tests)
        partial_loss_output = json.dumps({
            "total_estimate": 2100.0,
            "parts_cost": 550.0,
            "labor_cost": 337.50,
            "insurance_pays": 1600.0,
            "authorization_id": "RA-ABC12345",
            "shop_id": "SHOP-001",
            "shop_name": "Quality Auto Repair",
        })
        conn.execute(
            "INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output) "
            "VALUES (?, ?, ?, ?)",
            ("CLM-TEST005", "partial_loss", "partial_loss", partial_loss_output),
        )


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset the settings singleton so each test gets fresh config from env."""
    import claim_agent.config as _cfg
    _cfg._settings = None
    yield
    _cfg._settings = None


@pytest.fixture(autouse=True)
def temp_db():
    """Use a temporary SQLite DB for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            # Ignore errors when cleaning up the temporary DB file (e.g., if already removed).
            pass


@pytest.fixture()
def seeded_temp_db(temp_db):
    """Temp DB with API-style seed data. Use for tests that need pre-populated claims."""
    _seed_test_data(temp_db)
    return temp_db


@pytest.fixture(autouse=True)
def reset_adapters():
    """Clear adapter singletons so each test gets a fresh instance."""
    from claim_agent.adapters.registry import reset_adapters as _reset
    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def reset_global_metrics():
    """Reset the global ClaimMetrics singleton before and after each test."""
    try:
        from claim_agent.observability.metrics import reset_metrics
        reset_metrics()
    except ImportError:
        pass
    yield
    try:
        from claim_agent.observability.metrics import reset_metrics
        reset_metrics()
    except ImportError:
        pass


@pytest.fixture()
def claim_context(temp_db):
    """Provide a ClaimContext wired to the per-test temp DB."""
    from claim_agent.context import ClaimContext

    return ClaimContext.from_defaults(db_path=temp_db)
