"""Load mock database and compliance data for tools.

- MOCK_DB_PATH env or default data/mock_db.json for policies/claims/vehicle_values.
- CA_COMPLIANCE_PATH env or default data/california_auto_compliance.json for CA compliance reference.
"""

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_DB = {
    "policies": {},
    "claims": [],
    "vehicle_values": {},
}


def _project_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


def _resolve_db_path() -> Path:
    path = os.environ.get("MOCK_DB_PATH")
    if path:
        return Path(path)
    return _project_data_dir() / "mock_db.json"


def _resolve_ca_compliance_path() -> Path:
    path = os.environ.get("CA_COMPLIANCE_PATH")
    if path:
        return Path(path)
    return _project_data_dir() / "california_auto_compliance.json"


def load_mock_db() -> dict[str, Any]:
    """Load mock database from JSON file or return default in-memory structure."""
    path = _resolve_db_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULT_DB.copy()


def load_california_compliance() -> dict[str, Any] | None:
    """Load California auto insurance compliance data from JSON. Returns None if file missing or invalid."""
    path = _resolve_ca_compliance_path()
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
