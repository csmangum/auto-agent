"""Tests for fraud report templates."""

import json

from claim_agent.compliance.fraud_report_templates import get_fraud_report_template
from claim_agent.tools.compliance_tools import get_fraud_report_template_tool


class TestGetFraudReportTemplate:
    def test_returns_template_for_california(self):
        template = get_fraud_report_template("California")
        assert template is not None
        assert template["state"] == "California"
        assert template["form_id"] == "CA-CDI-DFR-1"
        assert "claim_id" in template["required_fields"]
        assert template["filing_deadline_days"] == 30

    def test_returns_template_for_abbreviation(self):
        template = get_fraud_report_template("CA")
        assert template is not None
        assert template["state"] == "California"

    def test_returns_none_for_unsupported_state(self):
        assert get_fraud_report_template("Invalid") is None
        assert get_fraud_report_template("") is None
        assert get_fraud_report_template(None) is None

    def test_tool_returns_json(self):
        result = get_fraud_report_template_tool.run(state="Texas")
        data = json.loads(result)
        assert "template" in data
        assert data["template"]["state"] == "Texas"
        assert data["template"]["form_id"] == "TX-DFR-FR-1"

    def test_returns_template_for_new_jersey(self):
        template = get_fraud_report_template("New Jersey")
        assert template is not None
        assert template["state"] == "New Jersey"
        assert template["form_id"] == "NJ-OIFP-FR-1"
        assert "claim_id" in template["required_fields"]
        assert "estimated_loss" in template["required_fields"]
        assert template["filing_deadline_days"] == 30
        assert template["bureau_name"] == (
            "New Jersey Office of the Insurance Fraud Prosecutor"
        )
        assert template["bureau_url"] is not None

    def test_returns_template_for_pennsylvania(self):
        template = get_fraud_report_template("Pennsylvania")
        assert template is not None
        assert template["state"] == "Pennsylvania"
        assert template["form_id"] == "PA-IFP-FR-1"
        assert "claim_id" in template["required_fields"]
        assert template["filing_deadline_days"] == 30
        assert template["bureau_name"] == (
            "Pennsylvania Insurance Fraud Prevention Authority"
        )
        assert template["bureau_url"] is not None

    def test_returns_template_for_illinois(self):
        template = get_fraud_report_template("Illinois")
        assert template is not None
        assert template["state"] == "Illinois"
        assert template["form_id"] == "IL-DOI-FR-1"
        assert "claim_id" in template["required_fields"]
        assert template["filing_deadline_days"] == 30
        assert template["bureau_name"] == (
            "Illinois Department of Insurance Fraud Division"
        )
        assert template["bureau_url"] is not None

    def test_returns_template_for_new_state_abbreviations(self):
        for abbrev, expected in [("NJ", "New Jersey"), ("PA", "Pennsylvania"),
                                 ("IL", "Illinois")]:
            template = get_fraud_report_template(abbrev)
            assert template is not None, f"Expected template for {abbrev}"
            assert template["state"] == expected
