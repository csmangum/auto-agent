"""Shared pytest fixtures for all test files."""

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

from claim_agent.db.database import init_db


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
