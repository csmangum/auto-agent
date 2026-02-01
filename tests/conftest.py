"""Shared pytest fixtures for all test files."""

import os
import tempfile
from pathlib import Path

import pytest

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
def reset_global_metrics():
    """Reset the global ClaimMetrics singleton before and after each test."""
    try:
        from claim_agent.observability.metrics import reset_metrics
        reset_metrics()
    except ImportError:
        # Metrics module is optional in some test environments; proceed without resetting.
        pass
    yield
    try:
        from claim_agent.observability.metrics import reset_metrics
        reset_metrics()
    except ImportError:
        # Metrics module is optional in some test environments; proceed without resetting.
        pass
