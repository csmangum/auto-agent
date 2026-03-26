"""Tests for cross-border data transfer controls and DPA registry."""

from __future__ import annotations

import pytest

from claim_agent.db.database import init_db
from claim_agent.privacy.cross_border import (
    JurisdictionZone,
    TransferMechanism,
    check_and_log_llm_transfer,
    check_transfer_permitted,
    classify_jurisdiction,
    get_known_data_flows,
    list_transfer_log,
    log_transfer,
    validate_scc_configuration,
)
from claim_agent.privacy.dpa_registry import (
    deactivate_dpa,
    get_dpa,
    list_dpas,
    register_dpa,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cb_db(tmp_path):
    """Temporary DB with cross-border tables initialised."""
    db_path = str(tmp_path / "cb_test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# classify_jurisdiction
# ---------------------------------------------------------------------------


class TestClassifyJurisdiction:
    def test_us_state_name(self):
        assert classify_jurisdiction("California") == JurisdictionZone.US

    def test_us_state_code(self):
        assert classify_jurisdiction("CA") == JurisdictionZone.US

    def test_us_full_name(self):
        assert classify_jurisdiction("United States") == JurisdictionZone.US

    def test_eu_country_name(self):
        assert classify_jurisdiction("Germany") == JurisdictionZone.EU_EEA

    def test_eu_country_code(self):
        # "DE" is ambiguous: Delaware (US state) vs Germany (EU).
        # In this system, 2-letter US state codes take priority (claim loss_state usage).
        # Use full country names for unambiguous EU classification.
        assert classify_jurisdiction("DE") == JurisdictionZone.US  # Delaware wins
        assert classify_jurisdiction("FR") == JurisdictionZone.EU_EEA
        assert classify_jurisdiction("IT") == JurisdictionZone.EU_EEA
        assert classify_jurisdiction("NL") == JurisdictionZone.EU_EEA

    def test_eu_eea_member(self):
        assert classify_jurisdiction("Norway") == JurisdictionZone.EU_EEA

    def test_adequate_country_uk(self):
        assert classify_jurisdiction("United Kingdom") == JurisdictionZone.ADEQUATE

    def test_adequate_country_code(self):
        assert classify_jurisdiction("CH") == JurisdictionZone.ADEQUATE

    def test_other_country(self):
        assert classify_jurisdiction("Brazil") == JurisdictionZone.OTHER

    def test_empty_string(self):
        assert classify_jurisdiction("") == JurisdictionZone.OTHER
        assert classify_jurisdiction(None) == JurisdictionZone.OTHER  # type: ignore[arg-type]

    def test_data_region_eu_shorthand(self):
        assert classify_jurisdiction("eu") == JurisdictionZone.EU_EEA
        assert classify_jurisdiction("EEA") == JurisdictionZone.EU_EEA

    def test_case_insensitive(self):
        assert classify_jurisdiction("california") == JurisdictionZone.US
        assert classify_jurisdiction("GERMANY") == JurisdictionZone.EU_EEA

    def test_new_york(self):
        assert classify_jurisdiction("New York") == JurisdictionZone.US

    def test_texas_code(self):
        assert classify_jurisdiction("TX") == JurisdictionZone.US

    def test_france(self):
        assert classify_jurisdiction("France") == JurisdictionZone.EU_EEA

    def test_japan(self):
        assert classify_jurisdiction("Japan") == JurisdictionZone.ADEQUATE


# ---------------------------------------------------------------------------
# get_known_data_flows
# ---------------------------------------------------------------------------


class TestKnownDataFlows:
    def test_returns_list(self):
        flows = get_known_data_flows()
        assert isinstance(flows, list)
        assert len(flows) >= 4

    def test_each_flow_has_required_keys(self):
        flows = get_known_data_flows()
        required = {
            "name", "description", "source_zone", "destination_zone",
            "data_categories", "purpose", "mechanism", "legal_basis",
            "is_cross_border", "requires_safeguard",
        }
        for f in flows:
            assert required.issubset(f.keys()), f"Missing keys in flow {f['name']}"

    def test_llm_api_flow_exists(self):
        flows = {f["name"]: f for f in get_known_data_flows()}
        assert "llm_api" in flows
        assert flows["llm_api"]["mechanism"] == TransferMechanism.LEGITIMATE.value

    def test_llm_api_eu_to_us_uses_scc(self):
        flows = {f["name"]: f for f in get_known_data_flows()}
        eu_flow = flows["llm_api_eu_to_us"]
        assert eu_flow["source_zone"] == JurisdictionZone.EU_EEA.value
        assert eu_flow["destination_zone"] == JurisdictionZone.US.value
        assert eu_flow["mechanism"] == TransferMechanism.SCC.value
        assert eu_flow["requires_safeguard"] is True

    def test_cross_border_only_filter(self):
        all_flows = get_known_data_flows()
        cross = get_known_data_flows(cross_border_only=True)
        assert len(cross) < len(all_flows)
        for f in cross:
            assert f["is_cross_border"] is True


# ---------------------------------------------------------------------------
# check_transfer_permitted
# ---------------------------------------------------------------------------


class TestCheckTransferPermitted:
    def test_us_to_us_always_allowed(self, monkeypatch):
        result = check_transfer_permitted(
            source_jurisdiction="California",
            destination_provider="openai",
            data_categories=["claim_data"],
        )
        assert result["permitted"] is True
        assert result["is_cross_border"] is False
        assert result["source_zone"] == JurisdictionZone.US.value
        assert result["destination_zone"] == JurisdictionZone.US.value

    def test_eu_to_us_with_scc_is_allowed(self, monkeypatch):
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("CROSS_BORDER_POLICY", "audit")
        from claim_agent.config import reload_settings
        reload_settings()
        result = check_transfer_permitted(
            source_jurisdiction="Germany",
            destination_provider="OpenAI",
            data_categories=["claim_data"],
            mechanism=TransferMechanism.SCC,
        )
        assert result["permitted"] is True
        assert result["is_cross_border"] is True
        assert result["requires_safeguard"] is True
        assert result["mechanism"] == TransferMechanism.SCC.value

    def test_eu_to_us_no_mechanism_audit_policy(self, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "audit")
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "none")
        from claim_agent.config import reload_settings
        reload_settings()
        result = check_transfer_permitted(
            source_jurisdiction="France",
            destination_provider="openai",
            data_categories=["claim_data"],
            mechanism=TransferMechanism.NONE,
        )
        # audit policy: permit but warn
        assert result["permitted"] is True
        assert result["policy_decision"] == "audit"
        assert len(result["warnings"]) > 0

    def test_eu_to_us_no_mechanism_restrict_policy(self, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "restrict")
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "none")
        from claim_agent.config import reload_settings
        reload_settings()
        result = check_transfer_permitted(
            source_jurisdiction="France",
            destination_provider="openai",
            data_categories=["claim_data"],
            mechanism=TransferMechanism.NONE,
        )
        assert result["permitted"] is False
        assert result["policy_decision"] == "block"

    def test_returns_mechanism_string(self):
        result = check_transfer_permitted(
            source_jurisdiction="California",
            destination_provider="openai",
            data_categories=["claim_data"],
        )
        assert isinstance(result["mechanism"], str)

    def test_adequate_country_no_safeguard_required(self):
        result = check_transfer_permitted(
            source_jurisdiction="Germany",
            destination_provider="UK provider",
            data_categories=["claim_data"],
        )
        # UK is adequate; source is EU but dest is adequate → no safeguard needed
        assert result["requires_safeguard"] is False


# ---------------------------------------------------------------------------
# log_transfer and list_transfer_log
# ---------------------------------------------------------------------------


class TestTransferLog:
    def test_log_and_list(self, cb_db):
        log_transfer(
            flow_name="llm_api",
            source_zone="us",
            destination="OpenAI",
            destination_zone="us",
            data_categories=["claim_data"],
            mechanism="legitimate_interests",
            claim_id="CLM-001",
            permitted=True,
            policy_decision="allow",
            db_path=cb_db,
        )
        items, total = list_transfer_log(db_path=cb_db)
        assert total == 1
        assert items[0]["flow_name"] == "llm_api"
        assert items[0]["claim_id"] == "CLM-001"
        assert isinstance(items[0]["data_categories"], list)

    def test_filter_by_policy_decision(self, cb_db):
        log_transfer(
            flow_name="llm_api",
            source_zone="eu_eea",
            destination="OpenAI",
            destination_zone="us",
            data_categories=["claim_data"],
            mechanism="scc",
            permitted=True,
            policy_decision="audit",
            db_path=cb_db,
        )
        log_transfer(
            flow_name="llm_api",
            source_zone="us",
            destination="OpenAI",
            destination_zone="us",
            data_categories=["claim_data"],
            mechanism="legitimate_interests",
            permitted=True,
            policy_decision="allow",
            db_path=cb_db,
        )
        audit_items, audit_total = list_transfer_log(policy_decision="audit", db_path=cb_db)
        assert audit_total == 1
        assert audit_items[0]["policy_decision"] == "audit"

        allow_items, allow_total = list_transfer_log(policy_decision="allow", db_path=cb_db)
        assert allow_total == 1

    def test_filter_by_flow_name(self, cb_db):
        log_transfer(
            flow_name="webhook_delivery",
            source_zone="us",
            destination="external",
            destination_zone="other",
            data_categories=["claim_id"],
            mechanism="legitimate_interests",
            db_path=cb_db,
        )
        items, total = list_transfer_log(flow_name="webhook_delivery", db_path=cb_db)
        assert total == 1
        items2, total2 = list_transfer_log(flow_name="llm_api", db_path=cb_db)
        assert total2 == 0


# ---------------------------------------------------------------------------
# check_and_log_llm_transfer
# ---------------------------------------------------------------------------


class TestCheckAndLogLlmTransfer:
    def test_us_claim_is_permitted(self, cb_db, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "allow")
        from claim_agent.config import reload_settings
        reload_settings()
        claim = {"claim_id": "CLM-US", "loss_state": "California"}
        result = check_and_log_llm_transfer(claim, db_path=cb_db)
        assert result["permitted"] is True
        # Entry should be logged
        items, total = list_transfer_log(claim_id="CLM-US", db_path=cb_db)
        assert total == 1

    def test_eu_claim_with_scc_is_permitted(self, cb_db, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "audit")
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        from claim_agent.config import reload_settings
        reload_settings()
        claim = {"claim_id": "CLM-EU", "loss_state": "Germany"}
        result = check_and_log_llm_transfer(claim, db_path=cb_db)
        assert result["permitted"] is True

    def test_restrict_policy_no_mechanism_raises(self, cb_db, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "restrict")
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "none")
        from claim_agent.config import reload_settings
        reload_settings()
        claim = {"claim_id": "CLM-EU2", "loss_state": "France"}
        with pytest.raises(PermissionError):
            check_and_log_llm_transfer(claim, db_path=cb_db)

    def test_missing_loss_state_falls_back_to_data_region(self, cb_db, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "allow")
        monkeypatch.setenv("DATA_REGION", "us")
        from claim_agent.config import reload_settings
        reload_settings()
        claim = {"claim_id": "CLM-NOLOSS"}
        result = check_and_log_llm_transfer(claim, db_path=cb_db)
        assert result["permitted"] is True


# ---------------------------------------------------------------------------
# DPA registry
# ---------------------------------------------------------------------------


class TestDPARegistry:
    def test_register_and_get(self, cb_db):
        dpa_id = register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data", "incident_description"],
            purpose="Automated claims processing",
            destination_country="US",
            mechanism="scc",
            legal_basis="GDPR Art. 46(2)(c) SCCs",
            dpa_signed_date="2024-01-15",
            dpa_document_ref="contracts/openai-dpa.pdf",
            supplementary_measures=["PII minimization", "TLS 1.2+"],
            db_path=cb_db,
        )
        assert dpa_id > 0
        dpa = get_dpa(dpa_id, db_path=cb_db)
        assert dpa is not None
        assert dpa["subprocessor_name"] == "OpenAI"
        assert dpa["service_type"] == "llm"
        assert dpa["mechanism"] == "scc"
        assert dpa["destination_zone"] == JurisdictionZone.US.value
        assert dpa["active"] == 1
        assert isinstance(dpa["data_categories"], list)
        assert "claim_data" in dpa["data_categories"]
        assert isinstance(dpa["supplementary_measures"], list)

    def test_list_dpas_active_only(self, cb_db):
        id1 = register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="Processing",
            destination_country="US",
            mechanism="scc",
            db_path=cb_db,
        )
        register_dpa(
            subprocessor_name="AWS",
            service_type="storage",
            data_categories=["claim_documents"],
            purpose="Storage",
            destination_country="US",
            mechanism="legitimate_interests",
            db_path=cb_db,
        )
        # Deactivate one
        deactivate_dpa(id1, db_path=cb_db)

        active, total = list_dpas(active_only=True, db_path=cb_db)
        assert total == 1
        assert active[0]["subprocessor_name"] == "AWS"

        all_dpas, all_total = list_dpas(active_only=False, db_path=cb_db)
        assert all_total == 2

    def test_deactivate_dpa(self, cb_db):
        dpa_id = register_dpa(
            subprocessor_name="SendGrid",
            service_type="notification",
            data_categories=["email"],
            purpose="Email notifications",
            destination_country="US",
            mechanism="scc",
            db_path=cb_db,
        )
        success = deactivate_dpa(dpa_id, db_path=cb_db)
        assert success is True

        dpa = get_dpa(dpa_id, db_path=cb_db)
        assert dpa["active"] == 0

        # Idempotent: deactivating again returns False
        again = deactivate_dpa(dpa_id, db_path=cb_db)
        assert again is False

    def test_filter_by_service_type(self, cb_db):
        register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="LLM processing",
            destination_country="US",
            mechanism="scc",
            db_path=cb_db,
        )
        register_dpa(
            subprocessor_name="Twilio",
            service_type="notification",
            data_categories=["phone"],
            purpose="SMS alerts",
            destination_country="US",
            mechanism="legitimate_interests",
            db_path=cb_db,
        )
        llm_dpas, llm_total = list_dpas(service_type="llm", db_path=cb_db)
        assert llm_total == 1
        assert llm_dpas[0]["subprocessor_name"] == "OpenAI"

    def test_destination_zone_derived_from_country(self, cb_db):
        dpa_id = register_dpa(
            subprocessor_name="EUProvider",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="EU-based LLM",
            destination_country="Germany",
            mechanism="legitimate_interests",
            db_path=cb_db,
        )
        dpa = get_dpa(dpa_id, db_path=cb_db)
        assert dpa["destination_zone"] == JurisdictionZone.EU_EEA.value

    def test_get_nonexistent_returns_none(self, cb_db):
        result = get_dpa(9999, db_path=cb_db)
        assert result is None


# ---------------------------------------------------------------------------
# Privacy settings (cross-border config fields)
# ---------------------------------------------------------------------------


class TestPrivacySettings:
    def test_default_data_region(self):
        from claim_agent.config import get_settings

        settings = get_settings()
        assert hasattr(settings.privacy, "data_region")
        assert settings.privacy.data_region in ("us", "eu", "other", "")

    def test_default_cross_border_policy(self):
        from claim_agent.config import get_settings

        settings = get_settings()
        assert hasattr(settings.privacy, "cross_border_policy")
        assert settings.privacy.cross_border_policy in ("allow", "audit", "restrict")

    def test_default_llm_transfer_mechanism(self):
        from claim_agent.config import get_settings

        settings = get_settings()
        assert hasattr(settings.privacy, "llm_transfer_mechanism")
        assert settings.privacy.llm_transfer_mechanism != ""

    def test_env_override_cross_border_policy(self, monkeypatch):
        monkeypatch.setenv("CROSS_BORDER_POLICY", "restrict")
        from claim_agent.config import reload_settings

        s = reload_settings()
        assert s.privacy.cross_border_policy == "restrict"

    def test_env_override_data_region(self, monkeypatch):
        monkeypatch.setenv("DATA_REGION", "eu")
        from claim_agent.config import reload_settings

        s = reload_settings()
        assert s.privacy.data_region == "eu"

    def test_scc_document_ref_field_exists(self):
        from claim_agent.config import get_settings

        settings = get_settings()
        assert hasattr(settings.privacy, "scc_document_ref")

    def test_env_override_scc_document_ref(self, monkeypatch):
        monkeypatch.setenv("SCC_DOCUMENT_REF", "contracts/openai-dpa-2024.pdf")
        from claim_agent.config import reload_settings

        s = reload_settings()
        assert s.privacy.scc_document_ref == "contracts/openai-dpa-2024.pdf"


# ---------------------------------------------------------------------------
# validate_scc_configuration
# ---------------------------------------------------------------------------


class TestValidateSccConfiguration:
    def test_non_scc_mechanism_is_always_validated(self, monkeypatch):
        """Non-SCC mechanisms do not require SCC document or DPA entry."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "legitimate_interests")
        from claim_agent.config import reload_settings
        reload_settings()
        result = validate_scc_configuration()
        assert result["validated"] is True
        assert result["warnings"] == []
        assert result["mechanism"] == "legitimate_interests"

    def test_scc_mechanism_no_ref_no_dpa_fails(self, cb_db, monkeypatch):
        """SCC mechanism with no document ref and no DPA registry entry → not validated."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.delenv("SCC_DOCUMENT_REF", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        result = validate_scc_configuration(db_path=cb_db)
        assert result["validated"] is False
        assert result["dpa_entries_found"] == 0
        # Expect exactly 2 warnings: one for missing SCC_DOCUMENT_REF, one for missing DPA entry
        assert len(result["warnings"]) == 2
        assert any("SCC_DOCUMENT_REF" in w for w in result["warnings"])
        assert any("DPA registry" in w for w in result["warnings"])

    def test_scc_mechanism_with_ref_no_dpa_still_fails(self, cb_db, monkeypatch):
        """SCC document ref set but no DPA registry entry → not validated."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("SCC_DOCUMENT_REF", "contracts/openai-dpa.pdf")
        from claim_agent.config import reload_settings
        reload_settings()
        result = validate_scc_configuration(db_path=cb_db)
        assert result["validated"] is False
        assert result["dpa_entries_found"] == 0
        assert result["scc_document_ref"] == "contracts/openai-dpa.pdf"
        # Should have exactly 1 warning (missing DPA entry; ref is present)
        assert len(result["warnings"]) == 1
        assert "DPA registry" in result["warnings"][0]

    def test_scc_mechanism_with_dpa_no_ref_still_fails(self, cb_db, monkeypatch):
        """DPA entry registered but SCC_DOCUMENT_REF not set → not validated."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.delenv("SCC_DOCUMENT_REF", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="Automated claims processing",
            destination_country="US",
            mechanism="scc",
            legal_basis="GDPR Art. 46(2)(c)",
            dpa_document_ref="contracts/openai-dpa.pdf",
            db_path=cb_db,
        )
        result = validate_scc_configuration(db_path=cb_db)
        assert result["validated"] is False
        assert result["dpa_entries_found"] == 1
        # Warning should be only about missing SCC_DOCUMENT_REF
        assert len(result["warnings"]) == 1
        assert "SCC_DOCUMENT_REF" in result["warnings"][0]

    def test_scc_fully_documented_is_validated(self, cb_db, monkeypatch):
        """Both SCC_DOCUMENT_REF and a DPA registry entry present → validated."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("SCC_DOCUMENT_REF", "contracts/openai-dpa-2024.pdf")
        from claim_agent.config import reload_settings
        reload_settings()
        register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data", "incident_description"],
            purpose="Automated claims processing",
            destination_country="US",
            mechanism="scc",
            legal_basis="GDPR Art. 46(2)(c) SCCs (EC 2021/914 Module 2)",
            dpa_signed_date="2024-01-15",
            dpa_document_ref="contracts/openai-dpa-2024.pdf",
            supplementary_measures=["PII minimization", "TLS 1.2+"],
            db_path=cb_db,
        )
        result = validate_scc_configuration(db_path=cb_db)
        assert result["validated"] is True
        assert result["warnings"] == []
        assert result["dpa_entries_found"] == 1
        assert result["scc_document_ref"] == "contracts/openai-dpa-2024.pdf"
        assert result["mechanism"] == "scc"

    def test_deactivated_dpa_not_counted(self, cb_db, monkeypatch):
        """A deactivated DPA entry is not counted; validation still fails."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("SCC_DOCUMENT_REF", "contracts/openai-dpa-2024.pdf")
        from claim_agent.config import reload_settings
        reload_settings()
        dpa_id = register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="LLM processing",
            destination_country="US",
            mechanism="scc",
            db_path=cb_db,
        )
        from claim_agent.privacy.dpa_registry import deactivate_dpa
        deactivate_dpa(dpa_id, db_path=cb_db)

        result = validate_scc_configuration(db_path=cb_db)
        assert result["validated"] is False
        assert result["dpa_entries_found"] == 0

    def test_check_and_log_adds_scc_warnings_when_undocumented(self, cb_db, monkeypatch):
        """check_and_log_llm_transfer surfaces SCC validation warnings when undocumented."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("CROSS_BORDER_POLICY", "allow")
        monkeypatch.delenv("SCC_DOCUMENT_REF", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        claim = {"claim_id": "CLM-SCC-WARN", "loss_state": "California"}
        result = check_and_log_llm_transfer(claim, db_path=cb_db)
        # Transfer is still permitted (allow policy), but warnings are surfaced
        assert result["permitted"] is True
        assert any("SCC_DOCUMENT_REF" in w or "No active DPA registry entry" in w for w in result["warnings"])

    def test_check_and_log_no_extra_warnings_when_scc_documented(self, cb_db, monkeypatch):
        """check_and_log_llm_transfer emits no SCC warnings when fully documented."""
        monkeypatch.setenv("LLM_TRANSFER_MECHANISM", "scc")
        monkeypatch.setenv("CROSS_BORDER_POLICY", "allow")
        monkeypatch.setenv("SCC_DOCUMENT_REF", "contracts/openai-dpa-2024.pdf")
        from claim_agent.config import reload_settings
        reload_settings()
        register_dpa(
            subprocessor_name="OpenAI",
            service_type="llm",
            data_categories=["claim_data"],
            purpose="LLM processing",
            destination_country="US",
            mechanism="scc",
            dpa_document_ref="contracts/openai-dpa-2024.pdf",
            db_path=cb_db,
        )
        claim = {"claim_id": "CLM-SCC-OK", "loss_state": "California"}
        result = check_and_log_llm_transfer(claim, db_path=cb_db)
        assert result["permitted"] is True
        # No SCC-related warnings should be present
        scc_warnings = [w for w in result.get("warnings", []) if "SCC_DOCUMENT_REF" in w or "No active DPA registry entry" in w]
        assert scc_warnings == []

