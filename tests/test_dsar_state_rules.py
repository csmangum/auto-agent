"""Tests for state-specific DSAR rules, form schemas, and access export metadata."""

import pytest

from claim_agent.compliance.dsar_state_rules import (
    get_dsar_form_schema,
    get_dsar_state_rules,
    get_response_deadline_days,
    get_state_response_metadata,
    get_supported_dsar_states,
)
from claim_agent.db.database import init_db
from claim_agent.services.dsar import (
    fulfill_access_request,
    submit_access_request,
    submit_deletion_request,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dsar_db(tmp_path):
    """Minimal DB with a claim and party for state-DSAR tests."""
    db_path = str(tmp_path / "state_dsar.db")
    init_db(db_path)
    from claim_agent.db.database import get_connection
    from sqlalchemy import text

    with get_connection(db_path) as conn:
        conn.execute(
            text("""
            INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                vehicle_model, incident_date, incident_description, damage_description,
                status, claim_type)
            VALUES ('CLM-STATE1', 'POL-CA1', '1HGCM82633A000001', 2021, 'Toyota', 'Camry',
                '2024-06-01', 'Side collision', 'Door damage', 'open', 'partial_loss')
            """)
        )
        conn.execute(
            text("""
            INSERT INTO claim_parties (claim_id, party_type, name, email, consent_status)
            VALUES ('CLM-STATE1', 'claimant', 'Maria Lopez', 'maria@example.com', 'granted')
            """)
        )
    return db_path


# ---------------------------------------------------------------------------
# DSARStateRules lookup
# ---------------------------------------------------------------------------


class TestGetDSARStateRules:
    def test_california_rules_returned(self):
        rules = get_dsar_state_rules("California")
        assert rules is not None
        assert rules.state == "California"
        assert rules.law_name == "CCPA/CPRA"

    def test_california_abbreviation(self):
        rules = get_dsar_state_rules("CA")
        assert rules is not None
        assert rules.state == "California"

    def test_virginia_rules_returned(self):
        rules = get_dsar_state_rules("Virginia")
        assert rules is not None
        assert rules.law_name == "VCDPA"

    def test_colorado_rules_returned(self):
        rules = get_dsar_state_rules("Colorado")
        assert rules is not None
        assert rules.law_name == "CPA"

    def test_texas_rules_returned(self):
        rules = get_dsar_state_rules("Texas")
        assert rules is not None
        assert rules.law_name == "TDPSA"

    def test_unsupported_state_returns_none(self):
        assert get_dsar_state_rules("Wyoming") is None

    def test_none_state_returns_none(self):
        assert get_dsar_state_rules(None) is None

    def test_empty_string_returns_none(self):
        assert get_dsar_state_rules("") is None


# ---------------------------------------------------------------------------
# Supported states list
# ---------------------------------------------------------------------------


class TestGetSupportedDSARStates:
    def test_returns_list(self):
        states = get_supported_dsar_states()
        assert isinstance(states, list)
        assert len(states) >= 4

    def test_california_in_list(self):
        assert "California" in get_supported_dsar_states()

    def test_virginia_in_list(self):
        assert "Virginia" in get_supported_dsar_states()

    def test_colorado_in_list(self):
        assert "Colorado" in get_supported_dsar_states()


# ---------------------------------------------------------------------------
# Response deadline helper
# ---------------------------------------------------------------------------


class TestGetResponseDeadlineDays:
    def test_california_45_days(self):
        assert get_response_deadline_days("California") == 45

    def test_virginia_45_days(self):
        assert get_response_deadline_days("Virginia") == 45

    def test_unknown_state_fallback(self):
        assert get_response_deadline_days("Wyoming") == 30

    def test_none_fallback(self):
        assert get_response_deadline_days(None) == 30


# ---------------------------------------------------------------------------
# Form schema
# ---------------------------------------------------------------------------


class TestGetDSARFormSchema:
    def test_california_schema_fields(self):
        schema = get_dsar_form_schema("California", "access")
        assert schema["state"] == "California"
        assert schema["law_name"] == "CCPA/CPRA"
        assert schema["request_type"] == "access"
        assert schema["response_deadline_days"] == 45
        assert schema["extension_days"] == 45
        assert "right_to_know" in schema["consumer_rights"]
        assert "right_to_delete" in schema["consumer_rights"]
        assert "full_name" in schema["required_fields"]
        assert "email_address" in schema["required_fields"]
        assert "identifiers" in schema["data_categories"]

    def test_california_deletion_schema(self):
        schema = get_dsar_form_schema("California", "deletion")
        assert schema["request_type"] == "deletion"
        assert schema["state"] == "California"

    def test_virginia_schema(self):
        schema = get_dsar_form_schema("Virginia", "access")
        assert schema["law_name"] == "VCDPA"
        assert "right_to_access" in schema["consumer_rights"]
        assert "right_to_portability" in schema["consumer_rights"]

    def test_colorado_schema(self):
        schema = get_dsar_form_schema("Colorado", "access")
        assert schema["law_name"] == "CPA"
        assert "right_to_opt_out" in schema["consumer_rights"]

    def test_abbreviation_resolved(self):
        schema = get_dsar_form_schema("CA", "access")
        assert schema["state"] == "California"

    def test_unsupported_state_generic_schema(self):
        schema = get_dsar_form_schema("Wyoming", "access")
        assert schema["state"] == "Wyoming"
        assert schema["law_name"] == "Generic Privacy Law"
        assert schema["response_deadline_days"] == 30
        assert "right_to_access" in schema["consumer_rights"]

    def test_none_state_generic_schema(self):
        schema = get_dsar_form_schema(None, "access")
        assert schema["law_name"] == "Generic Privacy Law"

    def test_annual_request_limit_california(self):
        schema = get_dsar_form_schema("California")
        assert schema["annual_request_limit"] == 2

    def test_annual_request_limit_virginia_none(self):
        schema = get_dsar_form_schema("Virginia")
        assert schema["annual_request_limit"] is None

    def test_schema_includes_opt_out_mechanisms(self):
        schema = get_dsar_form_schema("California")
        assert "do_not_sell_or_share_link" in schema["opt_out_mechanisms"]

    def test_schema_includes_response_format_notes(self):
        schema = get_dsar_form_schema("California")
        assert "45" in schema["response_format_notes"]


# ---------------------------------------------------------------------------
# State response metadata
# ---------------------------------------------------------------------------


class TestGetStateResponseMetadata:
    def test_california_metadata(self):
        meta = get_state_response_metadata("California")
        assert meta["state"] == "California"
        assert meta["applicable_law"] == "CCPA/CPRA"
        assert meta["response_deadline_days"] == 45
        assert meta["extension_days"] == 45
        assert "right_to_know" in meta["consumer_rights"]
        assert "45" in meta["response_format_notes"]

    def test_unknown_state_fallback(self):
        meta = get_state_response_metadata("Wyoming")
        assert meta["applicable_law"] is None
        assert meta["response_deadline_days"] == 30
        assert "right_to_access" in meta["consumer_rights"]

    def test_none_state_fallback(self):
        meta = get_state_response_metadata(None)
        assert meta["applicable_law"] is None


# ---------------------------------------------------------------------------
# Access export includes state_response_info
# ---------------------------------------------------------------------------


class TestAccessExportStateMetadata:
    def test_california_state_info_in_export(self, state_dsar_db):
        request_id = submit_access_request(
            claimant_identifier="maria@example.com",
            verification_data={"claim_id": "CLM-STATE1"},
            state="California",
            db_path=state_dsar_db,
        )
        export = fulfill_access_request(request_id, db_path=state_dsar_db)
        assert "state_response_info" in export
        info = export["state_response_info"]
        assert info["state"] == "California"
        assert info["applicable_law"] == "CCPA/CPRA"
        assert info["response_deadline_days"] == 45
        assert info["extension_days"] == 45

    def test_no_state_returns_generic_info(self, state_dsar_db):
        request_id = submit_access_request(
            claimant_identifier="maria@example.com",
            verification_data={"claim_id": "CLM-STATE1"},
            db_path=state_dsar_db,
        )
        export = fulfill_access_request(request_id, db_path=state_dsar_db)
        info = export["state_response_info"]
        assert info["applicable_law"] is None
        assert info["response_deadline_days"] == 30

    def test_state_stored_in_deletion_verification_data(self, state_dsar_db):
        """State is persisted in verification_data for deletion requests."""
        from claim_agent.services.dsar import get_dsar_request
        import json

        request_id = submit_deletion_request(
            claimant_identifier="maria@example.com",
            verification_data={"claim_id": "CLM-STATE1"},
            state="Virginia",
            db_path=state_dsar_db,
        )
        req = get_dsar_request(request_id, db_path=state_dsar_db)
        assert req is not None
        vdata = json.loads(req["verification_data"])
        assert vdata.get("state") == "Virginia"

    def test_state_stored_in_access_verification_data(self, state_dsar_db):
        """State is persisted in verification_data for access requests."""
        from claim_agent.services.dsar import get_dsar_request
        import json

        request_id = submit_access_request(
            claimant_identifier="maria@example.com",
            verification_data={"claim_id": "CLM-STATE1"},
            state="Colorado",
            db_path=state_dsar_db,
        )
        req = get_dsar_request(request_id, db_path=state_dsar_db)
        assert req is not None
        vdata = json.loads(req["verification_data"])
        assert vdata.get("state") == "Colorado"
