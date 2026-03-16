"""Shared claim data schema and helpers for building claim dicts from DB rows."""

import json

_CLAIM_DATA_KEYS = (
    "policy_number",
    "vin",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "incident_date",
    "incident_description",
    "damage_description",
    "estimated_damage",
    "attachments",
    "claim_type",
    "loss_state",
    "liability_percentage",
    "liability_basis",
)
_CLAIM_DATA_DEFAULTS = {
    "policy_number": "",
    "vin": "",
    "vehicle_year": 0,
    "vehicle_make": "",
    "vehicle_model": "",
    "incident_date": "",
    "incident_description": "",
    "damage_description": "",
    "estimated_damage": None,
    "attachments": [],
    "claim_type": None,
    "loss_state": None,
    "liability_percentage": None,
    "liability_basis": None,
}


def claim_data_from_row(row: dict) -> dict:
    """Build claim_data dict from claim row for reprocess. Uses defaults for None."""
    result = {}
    for k in _CLAIM_DATA_KEYS:
        if row.get(k) is not None:
            result[k] = row[k]
        else:
            default = _CLAIM_DATA_DEFAULTS[k]
            result[k] = list(default) if isinstance(default, list) else default
    if isinstance(result.get("attachments"), str):
        result["attachments"] = json.loads(result["attachments"])
    return result
