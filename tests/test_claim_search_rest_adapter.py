"""Tests for REST ClaimSearch adapter."""

from unittest.mock import MagicMock, patch

import pytest

from claim_agent.adapters.real.claim_search_rest import RestClaimSearchAdapter


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------


def test_rest_claim_search_posts_vin_and_claimant(monkeypatch):
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
                    return {"results": []}

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    adapter.search_claims(vin="VIN12345", claimant_name="Jane Doe")
    assert posted["path"] == "/claims/search"
    body = posted["json"]
    assert body["vin"] == "VIN12345"
    assert body["claimant_name"] == "Jane Doe"


def test_rest_claim_search_includes_date_range(monkeypatch):
    posted: dict = {}

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            posted["json"] = json

            class R:
                status_code = 200

                def json(self):
                    return []

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    adapter.search_claims(vin="VIN999", date_range=("2024-01-01", "2024-02-01"))
    assert posted["json"]["date_from"] == "2024-01-01"
    assert posted["json"]["date_to"] == "2024-02-01"


def test_rest_claim_search_omits_empty_fields(monkeypatch):
    posted: dict = {}

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            posted["json"] = json

            class R:
                status_code = 200

                def json(self):
                    return []

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    adapter.search_claims(vin="VIN-ONLY")
    assert "claimant_name" not in posted["json"]
    assert "date_from" not in posted["json"]


def test_rest_claim_search_uses_custom_path(monkeypatch):
    posted: dict = {}

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            posted["path"] = path

            class R:
                status_code = 200

                def json(self):
                    return []

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(
        base_url="https://cs.example.com", search_path="/v2/search"
    )
    adapter.search_claims(vin="VIN123")
    assert posted["path"] == "/v2/search"


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


def test_rest_claim_search_normalises_results_key(monkeypatch):
    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return {
                        "results": [
                            {
                                "external_claim_id": "ISO-001",
                                "source": "iso",
                                "vin": "VIN123",
                                "claimant_name": "John Smith",
                                "status": "open",
                            }
                        ]
                    }

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    results = adapter.search_claims(vin="VIN123")
    assert len(results) == 1
    assert results[0]["external_claim_id"] == "ISO-001"
    assert results[0]["source"] == "iso"
    assert results[0]["status"] == "open"


def test_rest_claim_search_explicit_response_key(monkeypatch):
    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return {
                        "data": [
                            {
                                "id": "NICB-999",
                                "provider": "nicb",
                                "status": "under_investigation",
                            }
                        ]
                    }

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(
        base_url="https://cs.example.com", response_key="data"
    )
    results = adapter.search_claims(vin="VIN-TEST")
    assert len(results) == 1
    assert results[0]["external_claim_id"] == "NICB-999"
    assert results[0]["source"] == "nicb"
    assert results[0]["status"] == "under_investigation"


def test_rest_claim_search_falls_back_claim_id_field(monkeypatch):
    """The adapter maps ``claim_id`` to ``external_claim_id`` when the latter is absent."""

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return [{"claim_id": "ALT-123", "source": "iso", "status": "closed"}]

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    results = adapter.search_claims(vin="VIN-ALT")
    assert results[0]["external_claim_id"] == "ALT-123"


def test_rest_claim_search_empty_response(monkeypatch):
    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return {"results": []}

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    assert adapter.search_claims(vin="VIN-NONE") == []


def test_rest_claim_search_list_response_without_envelope(monkeypatch):
    """A bare list response (no envelope) is handled correctly."""

    class HC:
        def __init__(self, **kw):
            pass

        def post(self, path, *, params=None, json=None):
            class R:
                status_code = 200

                def json(self):
                    return [
                        {"external_claim_id": "X-1", "source": "iso", "status": "open"}
                    ]

            return R()

    monkeypatch.setattr("claim_agent.adapters.real.claim_search_rest.AdapterHttpClient", HC)
    adapter = RestClaimSearchAdapter(base_url="https://cs.example.com")
    results = adapter.search_claims(vin="VIN-BARE")
    assert len(results) == 1
    assert results[0]["external_claim_id"] == "X-1"


def test_rest_claim_search_health_check_delegates_to_http_client():
    with patch(
        "claim_agent.adapters.real.claim_search_rest.AdapterHttpClient"
    ) as mock_cls:
        mock_client = MagicMock()
        mock_client.health_check_with_fallback.return_value = (False, "timeout")
        mock_cls.return_value = mock_client
        ad = RestClaimSearchAdapter(base_url="https://cs.example.com")
        assert ad.health_check() == (False, "timeout")
        mock_client.health_check_with_fallback.assert_called_once_with()


# ---------------------------------------------------------------------------
# Factory / registry wiring
# ---------------------------------------------------------------------------


def test_create_rest_claim_search_adapter_raises_without_base_url(monkeypatch):
    """Factory raises ValueError when CLAIM_SEARCH_REST_BASE_URL is not set."""
    from claim_agent.config.settings_model import ClaimSearchRestConfig

    mock_config = ClaimSearchRestConfig()  # base_url defaults to ""

    class FakeSettings:
        claim_search_rest = mock_config

    monkeypatch.setattr(
        "claim_agent.adapters.real.claim_search_rest.get_settings", lambda: FakeSettings()
    )

    from claim_agent.adapters.real.claim_search_rest import create_rest_claim_search_adapter

    with pytest.raises(ValueError, match="CLAIM_SEARCH_REST_BASE_URL"):
        create_rest_claim_search_adapter()


def test_create_rest_claim_search_adapter_builds_correctly(monkeypatch):
    """Factory produces a RestClaimSearchAdapter with correct config."""
    from claim_agent.config.settings_model import ClaimSearchRestConfig

    from pydantic import SecretStr

    cfg = ClaimSearchRestConfig()
    cfg.base_url = "https://cs.example.com/v1"
    cfg.auth_value = SecretStr("Bearer tok")
    cfg.search_path = "/search"
    cfg.timeout = 30.0

    class FakeSettings:
        claim_search_rest = cfg

    monkeypatch.setattr(
        "claim_agent.adapters.real.claim_search_rest.get_settings", lambda: FakeSettings()
    )
    monkeypatch.setattr(
        "claim_agent.adapters.real.claim_search_rest.AdapterHttpClient",
        lambda **kw: object(),
    )

    from claim_agent.adapters.real.claim_search_rest import create_rest_claim_search_adapter

    adapter = create_rest_claim_search_adapter()
    assert isinstance(adapter, RestClaimSearchAdapter)
    assert adapter._search_path == "/search"


def test_registry_claim_search_rest_capable(monkeypatch):
    """REST_CAPABLE_ADAPTERS now includes claim_search."""
    from claim_agent.config.settings_model import REST_CAPABLE_ADAPTERS

    assert "claim_search" in REST_CAPABLE_ADAPTERS


def test_registry_get_claim_search_adapter_rest(monkeypatch):
    """Registry routes CLAIM_SEARCH_ADAPTER=rest through the REST factory."""
    import claim_agent.adapters.registry as reg
    from claim_agent.config import reload_settings

    reg.reset_adapters()
    monkeypatch.setenv("CLAIM_SEARCH_ADAPTER", "rest")
    reload_settings()

    # Monkeypatch the underlying factory that the registry delegates to
    built = []

    def fake_create():
        instance = RestClaimSearchAdapter(base_url="https://cs.example.com")
        built.append(instance)
        return instance

    monkeypatch.setattr(
        "claim_agent.adapters.real.claim_search_rest.AdapterHttpClient",
        lambda **kw: object(),
    )
    monkeypatch.setattr(
        "claim_agent.adapters.real.claim_search_rest.create_rest_claim_search_adapter",
        fake_create,
    )

    adapter = reg.get_claim_search_adapter()
    assert len(built) == 1
    assert isinstance(adapter, RestClaimSearchAdapter)

    reg.reset_adapters()
    monkeypatch.delenv("CLAIM_SEARCH_ADAPTER", raising=False)
    reload_settings()
