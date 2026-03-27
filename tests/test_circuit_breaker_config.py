"""Tests for circuit breaker configuration wiring in REST adapters.

Validates that circuit_failure_threshold and circuit_recovery_timeout settings
are properly propagated from *RestConfig classes through each adapter's
__init__ to the underlying AdapterHttpClient.
"""

import pytest

from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError


# ---------------------------------------------------------------------------
# AdapterHttpClient circuit breaker behaviour
# ---------------------------------------------------------------------------

class TestAdapterHttpClientCircuitBreaker:
    """Unit tests for the built-in circuit breaker in AdapterHttpClient."""

    def _make_client(self, threshold: int = 3, recovery: float = 60.0) -> AdapterHttpClient:
        return AdapterHttpClient(
            base_url="https://example.com",
            circuit_failure_threshold=threshold,
            circuit_recovery_timeout=recovery,
        )

    def test_circuit_opens_after_threshold_failures(self):
        client = self._make_client(threshold=3)
        assert not client._circuit_open

        client._record_failure()
        client._record_failure()
        assert not client._circuit_open  # still under threshold

        client._record_failure()
        assert client._circuit_open  # at threshold → open

    def test_circuit_raises_when_open(self):
        client = self._make_client(threshold=1)
        client._record_failure()
        assert client._circuit_open

        with pytest.raises(CircuitOpenError):
            client._check_circuit()

    def test_circuit_resets_on_success(self):
        client = self._make_client(threshold=1)
        client._record_failure()
        assert client._circuit_open

        client._record_success()
        assert not client._circuit_open
        assert client._failure_count == 0

    def test_circuit_half_opens_after_recovery_timeout(self, monkeypatch):
        import time

        client = self._make_client(threshold=1, recovery=30.0)
        client._record_failure()
        assert client._circuit_open

        # Simulate recovery timeout elapsed
        monkeypatch.setattr(time, "monotonic", lambda: client._last_failure_time + 31.0)

        # Should not raise – circuit transitions to half-open
        client._check_circuit()
        assert not client._circuit_open

    def test_custom_threshold_and_timeout_stored(self):
        client = AdapterHttpClient(
            base_url="https://example.com",
            circuit_failure_threshold=7,
            circuit_recovery_timeout=120.0,
        )
        assert client._circuit_failure_threshold == 7
        assert client._circuit_recovery_timeout == 120.0


# ---------------------------------------------------------------------------
# REST adapter __init__ wiring
# ---------------------------------------------------------------------------

class TestRestAdapterCircuitBreakerWiring:
    """Verify circuit breaker params flow from adapter __init__ to AdapterHttpClient."""

    def test_policy_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.policy_rest import RestPolicyAdapter
        adapter = RestPolicyAdapter(
            base_url="https://pas.example.com",
            circuit_failure_threshold=4,
            circuit_recovery_timeout=90.0,
        )
        assert adapter._client._circuit_failure_threshold == 4
        assert adapter._client._circuit_recovery_timeout == 90.0

    def test_valuation_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.valuation_rest import RestValuationAdapter
        adapter = RestValuationAdapter(
            provider="ccc",
            base_url="https://val.example.com",
            path_template="/v?vin={vin}&year={year}",
            circuit_failure_threshold=6,
            circuit_recovery_timeout=45.0,
        )
        assert adapter._client._circuit_failure_threshold == 6
        assert adapter._client._circuit_recovery_timeout == 45.0

    def test_fraud_reporting_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.fraud_reporting_rest import RestFraudReportingAdapter
        adapter = RestFraudReportingAdapter(
            base_url="https://fraud.example.com",
            circuit_failure_threshold=3,
            circuit_recovery_timeout=30.0,
        )
        assert adapter._client._circuit_failure_threshold == 3
        assert adapter._client._circuit_recovery_timeout == 30.0

    def test_state_bureau_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.state_bureau_rest import RestStateBureauAdapter
        adapter = RestStateBureauAdapter(
            state_endpoints={"CA": "https://ca.example.com"},
            circuit_failure_threshold=5,
            circuit_recovery_timeout=120.0,
        )
        assert adapter._circuit_failure_threshold == 5
        assert adapter._circuit_recovery_timeout == 120.0
        # Also verify per-state clients inherit the settings
        client = adapter._get_client_for_state("CA")
        assert client._circuit_failure_threshold == 5
        assert client._circuit_recovery_timeout == 120.0

    def test_state_bureau_rest_health_check_probes_each_configured_client(self):
        from unittest.mock import MagicMock, patch

        from claim_agent.adapters.real.state_bureau_rest import RestStateBureauAdapter

        def client_factory(**kw):
            m = MagicMock()
            if "ca.example" in kw.get("base_url", ""):
                m.health_check_with_fallback.return_value = (True, "ok")
            else:
                m.health_check_with_fallback.return_value = (False, "timeout")
            return m

        with patch(
            "claim_agent.adapters.real.state_bureau_rest.AdapterHttpClient",
            side_effect=client_factory,
        ):
            adapter = RestStateBureauAdapter(
                state_endpoints={
                    "CA": "https://ca.example.com",
                    "TX": "https://tx.example.com",
                }
            )
            ok, msg = adapter.health_check()
        assert ok is False
        assert "TX:timeout" in msg

    def test_state_bureau_rest_health_check_no_endpoints(self):
        from claim_agent.adapters.real.state_bureau_rest import RestStateBureauAdapter

        adapter = RestStateBureauAdapter(state_endpoints={})
        assert adapter.health_check() == (False, "no state bureau endpoints configured")

    def test_claim_search_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.claim_search_rest import RestClaimSearchAdapter
        adapter = RestClaimSearchAdapter(
            base_url="https://cs.example.com",
            circuit_failure_threshold=8,
            circuit_recovery_timeout=60.0,
        )
        assert adapter._client._circuit_failure_threshold == 8
        assert adapter._client._circuit_recovery_timeout == 60.0

    def test_erp_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.erp_rest import RestERPAdapter
        adapter = RestERPAdapter(
            base_url="https://erp.example.com",
            circuit_failure_threshold=2,
            circuit_recovery_timeout=300.0,
        )
        assert adapter._client._circuit_failure_threshold == 2
        assert adapter._client._circuit_recovery_timeout == 300.0

    def test_repair_shop_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.repair_shop_rest import RestRepairShopAdapter
        adapter = RestRepairShopAdapter(
            base_url="https://shops.example.com",
            circuit_failure_threshold=10,
            circuit_recovery_timeout=15.0,
        )
        assert adapter._client._circuit_failure_threshold == 10
        assert adapter._client._circuit_recovery_timeout == 15.0

    def test_parts_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.parts_rest import RestPartsAdapter
        adapter = RestPartsAdapter(
            base_url="https://parts.example.com",
            circuit_failure_threshold=3,
            circuit_recovery_timeout=75.0,
        )
        assert adapter._client._circuit_failure_threshold == 3
        assert adapter._client._circuit_recovery_timeout == 75.0

    def test_siu_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.siu_rest import RestSIUAdapter
        adapter = RestSIUAdapter(
            base_url="https://siu.example.com",
            circuit_failure_threshold=5,
            circuit_recovery_timeout=180.0,
        )
        assert adapter._client._circuit_failure_threshold == 5
        assert adapter._client._circuit_recovery_timeout == 180.0

    def test_nmvtis_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.nmvtis_rest import RestNMVTISAdapter
        adapter = RestNMVTISAdapter(
            base_url="https://nmvtis.example.com",
            circuit_failure_threshold=4,
            circuit_recovery_timeout=50.0,
        )
        assert adapter._client._circuit_failure_threshold == 4
        assert adapter._client._circuit_recovery_timeout == 50.0

    def test_gap_insurance_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.gap_insurance_rest import RestGapInsuranceAdapter
        adapter = RestGapInsuranceAdapter(
            base_url="https://gap.example.com",
            circuit_failure_threshold=6,
            circuit_recovery_timeout=90.0,
        )
        assert adapter._client._circuit_failure_threshold == 6
        assert adapter._client._circuit_recovery_timeout == 90.0

    def test_ocr_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.ocr_rest import RestOCRAdapter
        adapter = RestOCRAdapter(
            base_url="https://ocr.example.com",
            circuit_failure_threshold=9,
            circuit_recovery_timeout=200.0,
        )
        assert adapter._client._circuit_failure_threshold == 9
        assert adapter._client._circuit_recovery_timeout == 200.0

    def test_medical_records_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.medical_records_rest import RestMedicalRecordsAdapter
        adapter = RestMedicalRecordsAdapter(
            base_url="https://hie.example.com",
            circuit_failure_threshold=3,
            circuit_recovery_timeout=120.0,
        )
        assert adapter._client._circuit_failure_threshold == 3
        assert adapter._client._circuit_recovery_timeout == 120.0

    def test_cms_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.cms_rest import RestCMSReportingAdapter
        adapter = RestCMSReportingAdapter(
            base_url="https://cms.example.com",
            circuit_failure_threshold=7,
            circuit_recovery_timeout=60.0,
        )
        assert adapter._client._circuit_failure_threshold == 7
        assert adapter._client._circuit_recovery_timeout == 60.0

    def test_reverse_image_rest_adapter_wires_circuit_breaker(self):
        from claim_agent.adapters.real.reverse_image_rest import RestReverseImageAdapter
        adapter = RestReverseImageAdapter(
            base_url="https://img.example.com",
            circuit_failure_threshold=5,
            circuit_recovery_timeout=240.0,
        )
        assert adapter._client._circuit_failure_threshold == 5
        assert adapter._client._circuit_recovery_timeout == 240.0


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class TestRestConfigCircuitBreakerSettings:
    """Verify *RestConfig classes expose circuit breaker fields with correct defaults."""

    def test_policy_rest_config_defaults(self):
        from claim_agent.config.settings_model import PolicyRestConfig
        cfg = PolicyRestConfig()
        assert cfg.circuit_failure_threshold == 5
        assert cfg.circuit_recovery_timeout == 60.0

    def test_valuation_rest_config_defaults(self):
        from claim_agent.config.settings_model import ValuationRestConfig
        cfg = ValuationRestConfig()
        assert cfg.circuit_failure_threshold == 5
        assert cfg.circuit_recovery_timeout == 60.0

    def test_erp_rest_config_defaults(self):
        from claim_agent.config.settings_model import ERPRestConfig
        cfg = ERPRestConfig()
        assert cfg.circuit_failure_threshold == 5
        assert cfg.circuit_recovery_timeout == 60.0

    def test_state_bureau_config_defaults(self):
        from claim_agent.config.settings_model import StateBureauConfig
        cfg = StateBureauConfig()
        assert cfg.circuit_failure_threshold == 5
        assert cfg.circuit_recovery_timeout == 60.0

    def test_all_rest_configs_have_circuit_breaker_fields(self):
        from claim_agent.config.settings_model import (
            CMSRestConfig,
            ClaimSearchRestConfig,
            ERPRestConfig,
            FraudReportingRestConfig,
            GapInsuranceRestConfig,
            MedicalRecordsRestConfig,
            NMVTISRestConfig,
            OCRRestConfig,
            PartsRestConfig,
            PolicyRestConfig,
            RepairShopRestConfig,
            ReverseImageRestConfig,
            SIURestConfig,
            StateBureauConfig,
            ValuationRestConfig,
        )
        config_classes = [
            PolicyRestConfig,
            ValuationRestConfig,
            FraudReportingRestConfig,
            StateBureauConfig,
            ClaimSearchRestConfig,
            ERPRestConfig,
            RepairShopRestConfig,
            PartsRestConfig,
            SIURestConfig,
            NMVTISRestConfig,
            GapInsuranceRestConfig,
            OCRRestConfig,
            MedicalRecordsRestConfig,
            CMSRestConfig,
            ReverseImageRestConfig,
        ]
        for cls in config_classes:
            cfg = cls()
            assert hasattr(cfg, "circuit_failure_threshold"), (
                f"{cls.__name__} missing circuit_failure_threshold"
            )
            assert hasattr(cfg, "circuit_recovery_timeout"), (
                f"{cls.__name__} missing circuit_recovery_timeout"
            )
            assert cfg.circuit_failure_threshold == 5, f"{cls.__name__} wrong default threshold"
            assert cfg.circuit_recovery_timeout == 60.0, f"{cls.__name__} wrong default timeout"
