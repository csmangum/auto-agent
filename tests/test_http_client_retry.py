"""AdapterHttpClient: retry exhaustion should record a single circuit-breaker failure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError


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


# ---------------------------------------------------------------------------
# post_multipart — same retry / circuit semantics as JSON _request
# ---------------------------------------------------------------------------


def _sample_multipart_files() -> dict[str, tuple[str, bytes]]:
    return {"file": ("doc.txt", b"payload")}


def test_post_multipart_success_records_success_no_circuit_open():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=2,
        circuit_failure_threshold=3,
    )
    client._record_failure()
    client._record_failure()
    assert client._failure_count == 2

    files = _sample_multipart_files()
    good = MagicMock()
    good.status_code = 200
    good.raise_for_status = MagicMock()
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=good)

    with patch.object(client, "_get_client", return_value=mock_http):
        resp = client.post_multipart("/upload", files=files)

    assert resp.status_code == 200
    assert client._failure_count == 0
    assert not client._circuit_open
    mock_http.request.assert_called_once()
    args, kwargs = mock_http.request.call_args
    assert args[0] == "POST"
    assert "/upload" in args[1]
    assert kwargs.get("files") is files


def test_post_multipart_503_exhaustion_opens_circuit_at_threshold():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=1,
    )
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=MagicMock(),
        response=bad,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad)

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            client.post_multipart("/upload", files=_sample_multipart_files())

    assert client._circuit_open
    with pytest.raises(CircuitOpenError):
        client.post_multipart("/upload", files=_sample_multipart_files())


def test_post_multipart_503_exhaustion_increments_failure_count_once():
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
            client.post_multipart("/upload", files=_sample_multipart_files())

    assert mock_http.request.call_count == 3
    assert client._failure_count == 1


def test_post_multipart_connect_error_exhaustion_increments_failure_count_once():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=2,
        circuit_failure_threshold=100,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(
        side_effect=[httpx.ConnectError("connection refused") for _ in range(3)]
    )

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.ConnectError):
            client.post_multipart("/upload", files=_sample_multipart_files())

    assert mock_http.request.call_count == 3
    assert client._failure_count == 1


def test_repeated_404_responses_do_not_trip_circuit_breaker():
    """Client errors must not increment the circuit failure counter (availability)."""
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=0,
        circuit_failure_threshold=3,
    )
    bad = MagicMock()
    bad.status_code = 404
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found",
        request=MagicMock(),
        response=bad,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad)

    with patch.object(client, "_get_client", return_value=mock_http):
        for _ in range(5):
            with pytest.raises(httpx.HTTPStatusError):
                client.get("/missing")

    assert client._failure_count == 0
    assert not client._circuit_open
    assert mock_http.request.call_count == 5


def test_post_multipart_non_retryable_404_single_attempt():
    client = AdapterHttpClient(
        base_url="http://example.test",
        max_retries=2,
        circuit_failure_threshold=100,
    )
    bad = MagicMock()
    bad.status_code = 404
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found",
        request=MagicMock(),
        response=bad,
    )
    mock_http = MagicMock()
    mock_http.request = MagicMock(return_value=bad)

    with patch.object(client, "_get_client", return_value=mock_http):
        with pytest.raises(httpx.HTTPStatusError):
            client.post_multipart("/upload", files=_sample_multipart_files())

    mock_http.request.assert_called_once()


def test_post_multipart_eventual_success_after_transient_503_clears_failure_count():
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
        resp = client.post_multipart("/upload", files=_sample_multipart_files())

    assert resp.status_code == 200
    assert client._failure_count == 0
