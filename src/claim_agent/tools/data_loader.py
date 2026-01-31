"""Load mock database for tools. Uses MOCK_DB_PATH env or default data/mock_db.json."""

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_DB = {
    "policies": {},
    "claims": [],
    "vehicle_values": {},
}


def _resolve_db_path() -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent
    path = os.environ.get("MOCK_DB_PATH")
    if path:
        return Path(path)
    return base / "data" / "mock_db.json"


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
