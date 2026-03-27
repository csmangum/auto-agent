"""AdapterHttpClient records low-cardinality Prometheus metrics per logical request."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from prometheus_client import REGISTRY, generate_latest

from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError
from claim_agent.observability.adapter_metrics import unregister_adapter_http_metrics_for_tests


@pytest.fixture(autouse=True)
def _clean_adapter_metrics():
    unregister_adapter_http_metrics_for_tests()
    yield
    unregister_adapter_http_metrics_for_tests()


def test_adapter_http_success_emits_counter_and_histogram():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=10,
        adapter_name="policy",
    )
    good = MagicMock()
    good.status_code = 200
    good.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=good)

    with patch.object(client, "_get_client", return_value=mock_http):
        client.get("/x")

    text = generate_latest(REGISTRY).decode()
    assert "adapter_http_requests_total" in text
    assert 'adapter="policy"' in text
    assert 'method="GET"' in text
    assert 'status_class="2xx"' in text
    assert "adapter_http_request_duration_seconds" in text


def test_adapter_http_failure_emits_error_status_class():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=100,
        adapter_name="parts",
    )
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "err",
        request=MagicMock(),
        response=bad,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad)

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("/p")

    text = generate_latest(REGISTRY).decode()
    assert 'adapter="parts"' in text
    assert 'status_class="5xx"' in text


def test_adapter_http_circuit_open_records_circuit_open_label():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=1,
        adapter_name="siu",
    )
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "err",
        request=MagicMock(),
        response=bad,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad)

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("/c")
        with pytest.raises(CircuitOpenError):
            client.get("/c")

    text = generate_latest(REGISTRY).decode()
    assert 'status_class="circuit_open"' in text


def test_post_multipart_records_post_method():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=10,
        adapter_name="ocr",
    )
    good = MagicMock()
    good.status_code = 201
    good.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=good)

    with patch.object(client, "_get_client", return_value=mock_http):
        client.post_multipart("/upload", files={"f": ("a.txt", b"x")})

    text = generate_latest(REGISTRY).decode()
    assert 'method="POST"' in text
    assert 'adapter="ocr"' in text
