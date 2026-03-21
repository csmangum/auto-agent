"""Shared data access for mock database and compliance JSON files.

- MOCK_DB_PATH from settings for policies/claims/vehicle_values.
- CA_COMPLIANCE_PATH from settings for CA compliance reference.
"""

import json
import logging
from pathlib import Path
from typing import Any, cast

from claim_agent.config import get_settings

_DEFAULT_DB: dict[str, Any] = {
    "policies": {},
    "claims": [],
    "vehicle_values": {},
}


def _policy_term_field_present(value: Any) -> bool:
    """True if *value* counts as a set term field (non-empty after strip for strings)."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _merge_policy_term_defaults(data: dict[str, Any]) -> None:
    """Apply _meta.policy_term_defaults to policies missing term dates (in-place)."""
    meta = data.get("_meta")
    if not isinstance(meta, dict):
        return
    defaults = meta.get("policy_term_defaults")
    if not isinstance(defaults, dict):
        return
    eff = defaults.get("effective_date")
    exp = defaults.get("expiration_date")
    if not isinstance(eff, str) or not isinstance(exp, str):
        return
    policies = data.get("policies")
    if not isinstance(policies, dict):
        return
    for pol in policies.values():
        if not isinstance(pol, dict):
            continue
        has_eff = _policy_term_field_present(
            pol.get("effective_date")
        ) or _policy_term_field_present(pol.get("term_start"))
        has_exp = _policy_term_field_present(
            pol.get("expiration_date")
        ) or _policy_term_field_present(pol.get("term_end"))
        if not has_eff:
            pol["effective_date"] = eff
        if not has_exp:
            pol["expiration_date"] = exp


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
                data = cast(dict[str, Any], json.load(f))
            _merge_policy_term_defaults(data)
            return data
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
            return cast(dict[str, Any], json.load(f))
    except (json.JSONDecodeError, OSError):
        return None


_STATE_TO_FILENAME: dict[str, str] = {
    "California": "california_auto_compliance.json",
    "Texas": "texas_auto_compliance.json",
    "Florida": "florida_auto_compliance.json",
    "New York": "new_york_auto_compliance.json",
}


def load_state_compliance(state: str) -> dict[str, Any] | None:
    """Load state auto insurance compliance data from JSON.

    Args:
        state: Canonical state name (California, Texas, Florida, New York).

    Returns:
        Compliance data dict or None if file missing or invalid.
    """
    if state == "California":
        return load_california_compliance()
    filename = _STATE_TO_FILENAME.get(state)
    if not filename:
        return None
    path = _project_data_dir() / filename
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
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
