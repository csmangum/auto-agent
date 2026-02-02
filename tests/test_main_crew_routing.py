"""Unit tests for main_crew routing helpers: keyword detection and economic total loss."""

import json
from unittest.mock import patch


# --- Catastrophic event keywords ---


def test_has_catastrophic_event_keywords_detects_flood_fire_rollover():
    from claim_agent.crews.main_crew import _has_catastrophic_event_keywords

    assert _has_catastrophic_event_keywords("Vehicle was flooded") is True
    assert _has_catastrophic_event_keywords("Engine fire") is True
    assert _has_catastrophic_event_keywords("Rollover on highway") is True
    assert _has_catastrophic_event_keywords("Car was submerged") is True
    assert _has_catastrophic_event_keywords("Roof crushed") is True
    assert _has_catastrophic_event_keywords("Burned interior") is True


def test_has_catastrophic_event_keywords_ignores_explicit_total_loss_only():
    from claim_agent.crews.main_crew import _has_catastrophic_event_keywords

    # Explicit total-loss wording without event keywords
    assert _has_catastrophic_event_keywords("Vehicle totaled") is False
    assert _has_catastrophic_event_keywords("Destroyed beyond repair") is False
    assert _has_catastrophic_event_keywords("Frame bent") is False


def test_has_catastrophic_event_keywords_empty_or_none():
    from claim_agent.crews.main_crew import _has_catastrophic_event_keywords

    assert _has_catastrophic_event_keywords(None) is False
    assert _has_catastrophic_event_keywords("") is False
    assert _has_catastrophic_event_keywords("  ") is False


# --- Explicit total-loss keywords ---


def test_has_explicit_total_loss_keywords_detects_totaled_destroyed():
    from claim_agent.crews.main_crew import _has_explicit_total_loss_keywords

    assert _has_explicit_total_loss_keywords("Vehicle totaled") is True
    assert _has_explicit_total_loss_keywords("Total loss") is True
    assert _has_explicit_total_loss_keywords("Destroyed") is True
    assert _has_explicit_total_loss_keywords("Beyond repair") is True
    assert _has_explicit_total_loss_keywords("Unrepairable") is True
    assert _has_explicit_total_loss_keywords("Complete loss") is True
    assert _has_explicit_total_loss_keywords("Write-off") is True
    assert _has_explicit_total_loss_keywords("Frame bent") is True
    assert _has_explicit_total_loss_keywords("Frame damage") is True


def test_has_explicit_total_loss_keywords_ignores_event_only():
    from claim_agent.crews.main_crew import _has_explicit_total_loss_keywords

    assert _has_explicit_total_loss_keywords("Flood damage") is False
    assert _has_explicit_total_loss_keywords("Fire in engine") is False
    assert _has_explicit_total_loss_keywords("Rollover accident") is False


# --- Combined catastrophic (any total-loss signal) ---


def test_has_catastrophic_keywords_event_or_explicit():
    from claim_agent.crews.main_crew import _has_catastrophic_keywords

    assert _has_catastrophic_keywords("Flood") is True
    assert _has_catastrophic_keywords("Totaled") is True
    assert _has_catastrophic_keywords("Door dent") is False


# --- Repairable damage keywords ---


def test_has_repairable_damage_keywords_detects_parts():
    from claim_agent.crews.main_crew import _has_repairable_damage_keywords

    assert _has_repairable_damage_keywords("Door damaged") is True
    assert _has_repairable_damage_keywords("Fender and bumper") is True
    assert _has_repairable_damage_keywords("Scratch on hood") is True
    assert _has_repairable_damage_keywords("Windshield crack") is True


def test_has_repairable_damage_keywords_false_when_catastrophic_present():
    from claim_agent.crews.main_crew import _has_repairable_damage_keywords

    # Repairable keywords present but catastrophic too -> not repairable
    assert _has_repairable_damage_keywords("Door damaged and vehicle totaled") is False
    assert _has_repairable_damage_keywords("Fender bent, car flooded") is False


def test_has_repairable_damage_keywords_false_when_no_repairable_keywords():
    from claim_agent.crews.main_crew import _has_repairable_damage_keywords

    assert _has_repairable_damage_keywords("Engine failure") is False
    assert _has_repairable_damage_keywords("") is False


# --- Economic total loss (_check_economic_total_loss) ---


@patch("claim_agent.tools.logic.fetch_vehicle_value_impl")
def test_check_economic_total_loss_strictly_cost_based_no_damage_keyword_override(mock_fetch):
    """is_economic_total_loss is True only when cost >= threshold; damage keywords do not set it True."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    mock_fetch.return_value = json.dumps({"value": 20000})
    # Cost 10k < 75% of 20k (15k) -> not economic total loss even with "totaled" in damage
    claim = {
        "vin": "VIN1",
        "vehicle_year": 2020,
        "vehicle_make": "Honda",
        "vehicle_model": "Civic",
        "damage_description": "Vehicle totaled",
        "incident_description": "Collision",
        "estimated_damage": 10000,
    }
    out = _check_economic_total_loss(claim)
    assert out["is_economic_total_loss"] is False
    assert out["damage_indicates_total_loss"] is True
    assert out["is_catastrophic_event"] is False


@patch("claim_agent.tools.logic.fetch_vehicle_value_impl")
def test_check_economic_total_loss_true_when_cost_exceeds_threshold(mock_fetch):
    """is_economic_total_loss True when estimated_damage >= 75% of vehicle value."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    mock_fetch.return_value = json.dumps({"value": 20000})
    # 75% of 20k = 15k; 16k >= 15k
    claim = {
        "vin": "VIN1",
        "vehicle_year": 2020,
        "vehicle_make": "Honda",
        "vehicle_model": "Civic",
        "damage_description": "Severe damage",
        "incident_description": "Collision",
        "estimated_damage": 16000,
    }
    out = _check_economic_total_loss(claim)
    assert out["is_economic_total_loss"] is True
    assert out["damage_to_value_ratio"] == 0.8


@patch("claim_agent.tools.logic.fetch_vehicle_value_impl")
def test_check_economic_total_loss_repairable_parts_high_cost_ratio_below_100(mock_fetch):
    """When damage is repairable-only and ratio < 100%, is_economic_total_loss is False."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    mock_fetch.return_value = json.dumps({"value": 20000})
    # 16k/20k = 80% (above 75%) but damage is doors/bumper only -> partial_loss
    claim = {
        "vin": "VIN1",
        "vehicle_year": 2020,
        "vehicle_make": "Honda",
        "vehicle_model": "Civic",
        "damage_description": "Door and bumper damage",
        "incident_description": "Parking lot",
        "estimated_damage": 16000,
    }
    out = _check_economic_total_loss(claim)
    assert out["damage_is_repairable"] is True
    assert out["damage_to_value_ratio"] == 0.8
    assert out["is_economic_total_loss"] is False


@patch("claim_agent.tools.logic.fetch_vehicle_value_impl")
def test_check_economic_total_loss_repairable_parts_ratio_100_or_more_still_true(mock_fetch):
    """When cost >= 100% of value, is_economic_total_loss True even if damage is repairable-only."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    mock_fetch.return_value = json.dumps({"value": 20000})
    claim = {
        "vin": "VIN1",
        "vehicle_year": 2020,
        "vehicle_make": "Honda",
        "vehicle_model": "Civic",
        "damage_description": "Door and bumper damage",
        "incident_description": "Parking lot",
        "estimated_damage": 20000,
    }
    out = _check_economic_total_loss(claim)
    assert out["damage_is_repairable"] is True
    assert out["damage_to_value_ratio"] == 1.0
    assert out["is_economic_total_loss"] is True


def test_check_economic_total_loss_no_estimated_damage_returns_context_only():
    """When estimated_damage missing or <= 0, is_economic_total_loss False; other flags still set."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    claim = {
        "vin": "VIN1",
        "damage_description": "Vehicle totaled in flood",
        "incident_description": "Flooded during storm",
    }
    out = _check_economic_total_loss(claim)
    assert out["is_economic_total_loss"] is False
    assert out["is_catastrophic_event"] is True
    assert out["damage_indicates_total_loss"] is True


def test_check_economic_total_loss_is_catastrophic_from_incident_description():
    """is_catastrophic_event True when incident_description has event keywords (e.g. flood)."""
    from claim_agent.crews.main_crew import _check_economic_total_loss

    claim = {
        "damage_description": "Water damage to interior",
        "incident_description": "Car was flooded in storm",
    }
    out = _check_economic_total_loss(claim)
    assert out["is_catastrophic_event"] is True
    # Damage text does not have explicit total-loss or event keywords (flood is in incident)
    assert out["damage_indicates_total_loss"] is False
