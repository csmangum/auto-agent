"""Shared data access for mock database and compliance JSON files.

- MOCK_DB_PATH from settings for policies/claims/vehicle_values.
- CA_COMPLIANCE_PATH from settings for CA compliance reference.
"""

import json
import logging
from pathlib import Path
from typing import Any

from claim_agent.config import get_settings

_DEFAULT_DB = {
    "policies": {},
    "claims": [],
    "vehicle_values": {},
}


def _project_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


def _resolve_db_path() -> Path:
    path = get_settings().paths.mock_db_path
    return Path(path)


def _resolve_ca_compliance_path() -> Path:
    path = get_settings().paths.ca_compliance_path
    return Path(path)


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


_log = logging.getLogger(__name__)


def get_compliance_retention_years() -> int | None:
    """Extract retention period from California compliance ECR-003 provision.

    Returns the retention_period_years value if valid (>= 1), or None
    if compliance data is unavailable or the provision is not found.
    """
    data = load_california_compliance()
    if data:
        ecr = data.get("electronic_claims_requirements", {})
        for p in ecr.get("provisions", []):
            if p.get("id") == "ECR-003" and "retention_period_years" in p:
                try:
                    value = int(p["retention_period_years"])
                except (ValueError, TypeError):
                    _log.warning(
                        "Compliance ECR-003 retention_period_years is not a valid integer; ignoring."
                    )
                    return None
                if value >= 1:
                    return value
                _log.warning(
                    "Compliance ECR-003 retention_period_years must be >= 1 (got %s); ignoring.",
                    value,
                )
                return None
    return None
