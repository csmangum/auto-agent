"""Test that non-retryable HTTP errors record metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from claim_agent.adapters.http_client import AdapterHttpClient
from claim_agent.observability.adapter_metrics import unregister_adapter_http_metrics_for_tests


@pytest.fixture(autouse=True)
def _cleanup_metrics():
    """Clean up Prometheus metrics before and after each test."""
    unregister_adapter_http_metrics_for_tests()
    yield
    unregister_adapter_http_metrics_for_tests()


def test_non_retryable_400_records_metrics():
    """Non-retryable 400 should record metrics with status_class=4xx."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        adapter_name="test_adapter",
        max_retries=2,
    )

    bad_response = MagicMock()
    bad_response.status_code = 400
    bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad request",
        request=MagicMock(),
        response=bad_response,
    )

    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad_response)

    with patch.object(client, "_get_client", return_value=mock_http):
        with patch("claim_agent.adapters.http_client.record_adapter_http_request") as mock_record:
            with pytest.raises(httpx.HTTPStatusError):
                client.get("/resource")

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["adapter_name"] == "test_adapter"
    assert call_kwargs["method"] == "GET"
    assert call_kwargs["status_class"] == "4xx"
    assert call_kwargs["duration_seconds"] >= 0


def test_non_retryable_401_records_metrics():
    """Non-retryable 401 should record metrics with status_class=4xx."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        adapter_name="policy_adapter",
        max_retries=2,
    )

    bad_response = MagicMock()
    bad_response.status_code = 401
    bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized",
        request=MagicMock(),
        response=bad_response,
    )

    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad_response)

    with patch.object(client, "_get_client", return_value=mock_http):
        with patch("claim_agent.adapters.http_client.record_adapter_http_request") as mock_record:
            with pytest.raises(httpx.HTTPStatusError):
                client.post("/resource", json={"key": "value"})

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["adapter_name"] == "policy_adapter"
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["status_class"] == "4xx"
    assert call_kwargs["duration_seconds"] >= 0


def test_non_retryable_404_records_metrics():
    """Non-retryable 404 should record metrics with status_class=4xx."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        adapter_name="valuation_adapter",
        max_retries=3,
    )

    bad_response = MagicMock()
    bad_response.status_code = 404
    bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found",
        request=MagicMock(),
        response=bad_response,
    )

    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad_response)

    with patch.object(client, "_get_client", return_value=mock_http):
        with patch("claim_agent.adapters.http_client.record_adapter_http_request") as mock_record:
            with pytest.raises(httpx.HTTPStatusError):
                client.get("/resource")

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["adapter_name"] == "valuation_adapter"
    assert call_kwargs["method"] == "GET"
    assert call_kwargs["status_class"] == "4xx"
    assert call_kwargs["duration_seconds"] >= 0


def test_non_retryable_422_records_metrics():
    """Non-retryable 422 should record metrics with status_class=4xx."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        adapter_name="repair_adapter",
        max_retries=2,
    )

    bad_response = MagicMock()
    bad_response.status_code = 422
    bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unprocessable entity",
        request=MagicMock(),
        response=bad_response,
    )

    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad_response)

    with patch.object(client, "_get_client", return_value=mock_http):
        with patch("claim_agent.adapters.http_client.record_adapter_http_request") as mock_record:
            with pytest.raises(httpx.HTTPStatusError):
                client.post("/resource", json={"key": "value"})

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["adapter_name"] == "repair_adapter"
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["status_class"] == "4xx"
    assert call_kwargs["duration_seconds"] >= 0
