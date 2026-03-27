"""Tests for REST fraud reporting adapter."""

from unittest.mock import MagicMock, patch

from claim_agent.adapters.real.fraud_reporting_rest import RestFraudReportingAdapter


def test_rest_fraud_reporting_adapter_state_bureau_merges_payload(monkeypatch):
    posted: dict = {}

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            posted["path"] = path
            posted["json"] = json

            class R:
                status_code = 200

                def json(self):
                    return {
                        "report_id": "FRB-REST-1",
                        "state": "California",
                        "indicators_count": 2,
                        "message": "ok",
                    }

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.fraud_reporting_rest.AdapterHttpClient", HC)
    ad = RestFraudReportingAdapter(base_url="https://fraud.example.com")
    out = ad.file_state_bureau_report(
        claim_id="CLM-REST-SB",
        case_id="SIU-REST-SB",
        state="California",
        indicators=["staged", "inflated"],
        payload={
            "indicators_summary": "staged",
            "vin": "VIN123",
            "policy_number": "POL-1",
        },
    )
    assert posted["path"] == "/fraud/state-bureau"
    body = posted["json"]
    assert body["claim_id"] == "CLM-REST-SB"
    assert body["case_id"] == "SIU-REST-SB"
    assert body["state"] == "California"
    assert body["indicators"] == ["staged", "inflated"]
    assert body["indicators_summary"] == "staged"
    assert body["vin"] == "VIN123"
    assert out["report_id"] == "FRB-REST-1"
    assert out["indicators_count"] == 2


def test_rest_fraud_reporting_adapter_state_bureau_coerces_bad_indicators_count(monkeypatch):
    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return {
                        "report_id": "FRB-REST-2",
                        "indicators_count": "not-a-number",
                    }

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.fraud_reporting_rest.AdapterHttpClient", HC)
    ad = RestFraudReportingAdapter(base_url="https://fraud.example.com")
    out = ad.file_state_bureau_report(
        claim_id="CLM-X",
        case_id="SIU-X",
        state="California",
        indicators=["a", "b"],
        payload=None,
    )
    assert out["indicators_count"] == 2


def test_rest_fraud_reporting_adapter_nicb(monkeypatch):
    class HC:
        def __init__(self, **kw):
            self.kw = kw

        def post(self, path, *, params=None, json=None):
            assert path == "/fraud/nicb"
            assert json is not None
            assert json["claim_id"] == "CLM-REST-1"

            class R:
                status_code = 200

                def json(self):
                    return {
                        "report_id": "NICB-REST-123",
                        "report_type": "theft",
                        "indicators_count": 2,
                        "message": "submitted",
                    }

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.fraud_reporting_rest.AdapterHttpClient", HC)
    ad = RestFraudReportingAdapter(base_url="https://fraud.example.com")
    out = ad.file_nicb_report(
        claim_id="CLM-REST-1",
        case_id="SIU-REST-1",
        report_type="theft",
        indicators=["stolen", "forced_entry"],
    )
    assert out["report_id"] == "NICB-REST-123"
    assert out["report_type"] == "theft"
    assert out["indicators_count"] == 2


def test_rest_fraud_reporting_health_check_delegates_to_http_client():
    with patch(
        "claim_agent.adapters.real.fraud_reporting_rest.AdapterHttpClient"
    ) as mock_cls:
        mock_client = MagicMock()
        mock_client.health_check_with_fallback.return_value = (True, "ok")
        mock_cls.return_value = mock_client
        ad = RestFraudReportingAdapter(base_url="https://fraud.example.com")
        assert ad.health_check() == (True, "ok")
        mock_client.health_check_with_fallback.assert_called_once_with()

