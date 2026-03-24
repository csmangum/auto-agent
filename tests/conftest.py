"""Shared pytest fixtures for all test files."""

pytest_plugins = ["tests.conftest_shared", "tests.conftest_embedding_mocks"]

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
os.environ.setdefault(
    "MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json")
)

from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection, init_db


def _seed_test_data(db_path: str) -> None:
    """Insert test claims, audit log entries, and workflow runs for API tests."""
    with get_connection(db_path) as conn:
        # Claims
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status, payout_amount)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status, :payout_amount)
            """),
            {
                "id": "CLM-TEST001",
                "policy_number": "POL-001",
                "vin": "1HGBH41JXMN109186",
                "vehicle_year": 2021,
                "vehicle_make": "Honda",
                "vehicle_model": "Accord",
                "incident_date": "2025-01-15",
                "incident_description": "Rear-ended at stoplight",
                "damage_description": "Rear bumper damage",
                "estimated_damage": 2500.0,
                "claim_type": "new",
                "status": "open",
                "payout_amount": 2500.0,
            },
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status)
            """),
            {
                "id": "CLM-TEST002",
                "policy_number": "POL-002",
                "vin": "5YJSA1E26HF123456",
                "vehicle_year": 2020,
                "vehicle_make": "Tesla",
                "vehicle_model": "Model 3",
                "incident_date": "2025-01-20",
                "incident_description": "Flash flood",
                "damage_description": "Vehicle submerged",
                "estimated_damage": 45000.0,
                "claim_type": "total_loss",
                "status": "closed",
            },
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status, loss_state)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status, :loss_state)
            """),
            {
                "id": "CLM-TEST003",
                "policy_number": "POL-003",
                "vin": "3VWDX7AJ5DM999999",
                "vehicle_year": 2019,
                "vehicle_make": "Volkswagen",
                "vehicle_model": "Jetta",
                "incident_date": "2025-01-22",
                "incident_description": "Staged accident",
                "damage_description": "Front bumper destroyed",
                "estimated_damage": 35000.0,
                "claim_type": "fraud",
                "status": "fraud_suspected",
                "loss_state": "California",
            },
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status, priority, due_at)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status, :priority, :due_at)
            """),
            {
                "id": "CLM-TEST004",
                "policy_number": "POL-004",
                "vin": "2HGFG3B54CH123456",
                "vehicle_year": 2022,
                "vehicle_make": "Toyota",
                "vehicle_model": "Camry",
                "incident_date": "2025-01-25",
                "incident_description": "Low confidence routing",
                "damage_description": "Minor scratch",
                "estimated_damage": 500.0,
                "claim_type": "new",
                "status": "needs_review",
                "priority": "high",
                "due_at": "2025-01-26T12:00:00Z",
            },
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status)
            """),
            {
                "id": "CLM-TEST005",
                "policy_number": "POL-005",
                "vin": "2T1BURHE5JC073987",
                "vehicle_year": 2022,
                "vehicle_make": "Toyota",
                "vehicle_model": "Corolla",
                "incident_date": "2025-01-25",
                "incident_description": "Backed into pole",
                "damage_description": "Rear bumper cracked, taillight broken",
                "estimated_damage": 1800.0,
                "claim_type": "partial_loss",
                "status": "processing",
            },
        )
        # Eligible third-party portal party for CLM-TEST005 (id 1 — first row in claim_parties)
        conn.execute(
            text("""
            INSERT INTO claim_parties (claim_id, party_type, name, email)
            VALUES ('CLM-TEST005', 'witness', 'Seed Third-Party Portal Witness', 'tp-witness-seed@example.com')
            """),
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status)
            """),
            {
                "id": "CLM-ARCHIVED",
                "policy_number": "POL-006",
                "vin": "1HGBH41JXMN109999",
                "vehicle_year": 2018,
                "vehicle_make": "Honda",
                "vehicle_model": "Civic",
                "incident_date": "2024-06-10",
                "incident_description": "Old claim",
                "damage_description": "Minor dent",
                "estimated_damage": 800.0,
                "claim_type": "partial_loss",
                "status": "archived",
            },
        )
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status, archived_at, purged_at)
            VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                    :incident_date, :incident_description, :damage_description,
                    :estimated_damage, :claim_type, :status, :archived_at, :purged_at)
            """),
            {
                "id": "CLM-PURGED",
                "policy_number": "POL-007",
                "vin": "1HGBH41JXMN109888",
                "vehicle_year": 2015,
                "vehicle_make": "Ford",
                "vehicle_model": "Focus",
                "incident_date": "2019-06-10",
                "incident_description": "Purged seed claim",
                "damage_description": "n/a",
                "estimated_damage": 100.0,
                "claim_type": "partial_loss",
                "status": "purged",
                "archived_at": "2022-01-01T00:00:00",
                "purged_at": "2024-01-01T00:00:00",
            },
        )
        conn.execute(text("UPDATE claims SET retention_tier = 'cold' WHERE status = 'closed'"))
        conn.execute(
            text("UPDATE claims SET retention_tier = 'archived' WHERE status = 'archived'")
        )
        conn.execute(text("UPDATE claims SET retention_tier = 'purged' WHERE status = 'purged'"))

        # Audit log entries
        conn.execute(
            text("""
            INSERT INTO claim_audit_log (claim_id, action, new_status, details, actor_id, after_state)
            VALUES (:claim_id, :action, :new_status, :details, :actor_id, :after_state)
            """),
            {
                "claim_id": "CLM-TEST001",
                "action": "created",
                "new_status": "pending",
                "details": "Claim record created",
                "actor_id": "workflow",
                "after_state": '{"status": "pending", "claim_type": null, "payout_amount": null}',
            },
        )
        conn.execute(
            text("""
            INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id, before_state, after_state)
            VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id, :before_state, :after_state)
            """),
            {
                "claim_id": "CLM-TEST001",
                "action": "status_change",
                "old_status": "pending",
                "new_status": "open",
                "details": "Processed successfully",
                "actor_id": "workflow",
                "before_state": '{"status": "pending", "claim_type": null, "payout_amount": null}',
                "after_state": '{"status": "open", "claim_type": "new", "payout_amount": null}',
            },
        )

        # Workflow run
        conn.execute(
            text("""
            INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
            VALUES (:claim_id, :claim_type, :router_output, :workflow_output)
            """),
            {
                "claim_id": "CLM-TEST001",
                "claim_type": "new",
                "router_output": "new\nFirst-time claim",
                "workflow_output": "Claim assigned and opened",
            },
        )
        partial_loss_output = json.dumps(
            {
                "total_estimate": 2100.0,
                "parts_cost": 550.0,
                "labor_cost": 337.50,
                "insurance_pays": 1600.0,
                "authorization_id": "RA-ABC12345",
                "shop_id": "SHOP-001",
                "shop_name": "Quality Auto Repair",
            }
        )
        conn.execute(
            text("""
            INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
            VALUES (:claim_id, :claim_type, :router_output, :workflow_output)
            """),
            {
                "claim_id": "CLM-TEST005",
                "claim_type": "partial_loss",
                "router_output": "partial_loss",
                "workflow_output": partial_loss_output,
            },
        )

        # Fraud report filings for compliance tests (CLM-TEST003)
        conn.execute(
            text("""
            INSERT INTO fraud_report_filings
            (claim_id, siu_case_id, filing_type, state, report_id, filed_at, filed_by,
             indicators_count, template_version, metadata)
            VALUES (:claim_id, :siu_case_id, :filing_type, :state, :report_id, :filed_at,
                    :filed_by, :indicators_count, :template_version, :metadata)
            """),
            {
                "claim_id": "CLM-TEST003",
                "siu_case_id": "SIU-SEED-001",
                "filing_type": "state_bureau",
                "state": "California",
                "report_id": "FRB-SEED-001",
                "filed_at": "2025-01-23T10:00:00Z",
                "filed_by": "siu_crew",
                "indicators_count": 2,
                "template_version": None,
                "metadata": None,
            },
        )
        conn.execute(
            text("""
            INSERT INTO fraud_report_filings
            (claim_id, siu_case_id, filing_type, state, report_id, filed_at, filed_by,
             indicators_count, template_version, metadata)
            VALUES (:claim_id, :siu_case_id, :filing_type, :state, :report_id, :filed_at,
                    :filed_by, :indicators_count, :template_version, :metadata)
            """),
            {
                "claim_id": "CLM-TEST003",
                "siu_case_id": "SIU-SEED-001",
                "filing_type": "nicb",
                "state": "California",
                "report_id": "NICB-SEED-001",
                "filed_at": "2025-01-23T11:00:00Z",
                "filed_by": "siu_crew",
                "indicators_count": 2,
                "template_version": None,
                "metadata": None,
            },
        )


@pytest.fixture(autouse=True)
def _reset_settings(request):
    """Reset the settings singleton so each test gets fresh config from env."""
    import claim_agent.config as _cfg
    import claim_agent.api.deps as _deps
    from claim_agent.db.database import reset_engine_cache

    _cfg._settings = None
    _deps._auth_warning_logged = False
    # Unit tests use SQLite; unset DATABASE_URL so we don't connect to PostgreSQL.
    # Preserve DATABASE_URL for PostgreSQL integration tests (test_postgres module).
    is_postgres_test = request.module is not None and "test_postgres" in getattr(
        request.module, "__name__", ""
    )
    _prev_db_url = os.environ.pop("DATABASE_URL", None) if not is_postgres_test else None
    reset_engine_cache()
    yield
    _cfg._settings = None
    _deps._auth_warning_logged = False
    reset_engine_cache()
    if _prev_db_url is not None:
        os.environ["DATABASE_URL"] = _prev_db_url


@pytest.fixture(autouse=True)
def temp_db():
    """Use a temporary SQLite DB for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    reload_settings()  # Ensure settings pick up CLAIMS_DB_PATH for API routes
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
def reset_diary_listener():
    """Reset diary listener registration state between tests."""
    import claim_agent.diary.auto_create as diary_module
    from claim_agent.events import unregister_claim_event_listener

    # Store original state
    original_state = diary_module._diary_listener_registered

    # Reset to initial state
    if diary_module._diary_listener_registered:
        try:
            unregister_claim_event_listener(diary_module._on_claim_status_change)
        except Exception:
            pass
    diary_module._diary_listener_registered = False

    yield

    # Clean up after test
    if diary_module._diary_listener_registered:
        try:
            unregister_claim_event_listener(diary_module._on_claim_status_change)
        except Exception:
            pass
    diary_module._diary_listener_registered = original_state


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


@pytest.fixture(autouse=True)
def _reset_mock_crew_stores():
    """Clear all in-memory mock crew stores between tests."""
    from claim_agent.mock_crew.notifier import clear_all_pending_mock_responses
    from claim_agent.mock_crew.repair_shop import clear_all_pending_repair_shop_responses
    from claim_agent.mock_crew.webhook import clear_captured_webhooks

    clear_all_pending_mock_responses()
    clear_all_pending_repair_shop_responses()
    clear_captured_webhooks()
    yield
    clear_all_pending_mock_responses()
    clear_all_pending_repair_shop_responses()
    clear_captured_webhooks()


@pytest.fixture()
def claim_context(temp_db):
    """Provide a ClaimContext wired to the per-test temp DB."""
    from claim_agent.context import ClaimContext

    return ClaimContext.from_defaults(db_path=temp_db)


@pytest.fixture()
def mock_crew(monkeypatch):
    """Enable Mock Crew for tests: mock vision, claim generation, etc.

    Sets MOCK_CREW_ENABLED=true, VISION_ADAPTER=mock, and optional seed.
    Resets env after test. Use with temp_db, seeded_temp_db, claim_context.
    """
    monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
    monkeypatch.setenv("VISION_ADAPTER", "mock")
    monkeypatch.setenv("MOCK_IMAGE_VISION_ANALYSIS_SOURCE", "claim_context")
    monkeypatch.setenv("MOCK_CREW_SEED", "42")
    reload_settings()
    yield
