"""Tests for REST fraud reporting adapter."""

from claim_agent.adapters.real.fraud_reporting_rest import RestFraudReportingAdapter


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

