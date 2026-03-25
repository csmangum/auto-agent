"""AdapterHttpClient: retry exhaustion should record a single circuit-breaker failure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from claim_agent.adapters.http_client import AdapterHttpClient


def test_retry_exhaustion_on_503_increments_failure_count_once():
    """Previously each retry attempt called ``_record_failure``; now one tick per logical request."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=2,
        circuit_failure_threshold=100,
    )

    def _make_503_response() -> MagicMock:
        r = MagicMock()
        r.status_code = 503
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=r,
        )
        return r

    mock_http = MagicMock()
    mock_http.request = MagicMock(side_effect=[_make_503_response() for _ in range(3)])

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("/resource")

    assert mock_http.request.call_count == 3  # 1 + max_retries
    assert client._failure_count == 1


def test_eventual_success_after_transient_503_clears_failure_count():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=3,
        circuit_failure_threshold=100,
    )
    responses: list[MagicMock] = []
    for _ in range(2):
        bad = MagicMock()
        bad.status_code = 503
        bad.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=bad,
        )
        responses.append(bad)
    good = MagicMock()
    good.status_code = 200
    good.raise_for_status = MagicMock()
    responses.append(good)

    mock_http = MagicMock()
    mock_http.request = MagicMock(side_effect=responses)

    with patch.object(client, "_get_client", return_value=mock_http):
        resp = client.get("/resource")

    assert resp.status_code == 200
    assert client._failure_count == 0
