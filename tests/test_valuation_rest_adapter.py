"""Tests for REST valuation adapter and JSON normalization (issue #271)."""

from claim_agent.adapters.real.valuation_rest import (
    RestValuationAdapter,
    normalize_valuation_response,
)


def test_normalize_acv_and_comparables():
    raw = {
        "acv": 18500.5,
        "vehicle_condition": "excellent",
        "comps": [
            {
                "vin": "V2",
                "year": 2020,
                "make": "Honda",
                "model": "Civic",
                "amount": 18200,
                "mileage": 41000,
                "source": "comp_db",
            }
        ],
    }
    out = normalize_valuation_response(raw, default_source="ccc")
    assert out is not None
    assert out["value"] == 18500.5
    assert out["condition"] == "excellent"
    assert out["source"] == "ccc"
    assert len(out["comparables"]) == 1
    assert out["comparables"][0]["price"] == 18200
    assert out["comparables"][0]["vin"] == "V2"


def test_normalize_missing_value_returns_none():
    assert normalize_valuation_response({"condition": "good"}, default_source="x") is None
    assert normalize_valuation_response([], default_source="x") is None


def test_rest_valuation_adapter_get_vehicle_value(monkeypatch):
    class HC:
        def __init__(self, **kw):
            self.kw = kw

        def get(self, path, params=None):
            assert "vin=VIN99" in path
            assert "year=2019" in path

            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {
                        "data": {
                            "vehicle_value": 16000,
                            "comparables": [],
                        }
                    }

            return R()

        def health_check(self, path="/health"):
            return True, "ok"

    monkeypatch.setattr(
        "claim_agent.adapters.real.valuation_rest.AdapterHttpClient",
        HC,
    )
    ad = RestValuationAdapter(
        provider="audatex",
        base_url="https://example.com",
        path_template="/v?vin={vin}&year={year}",
        response_key="data",
    )
    out = ad.get_vehicle_value("VIN99", 2019, "Ford", "F-150")
    assert out is not None
    assert out["value"] == 16000
    assert out["source"] == "audatex"
