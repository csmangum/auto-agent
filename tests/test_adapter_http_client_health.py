"""Tests for AdapterHttpClient health probes and /health fallback behavior."""

from unittest.mock import patch

from claim_agent.adapters.http_client import AdapterHttpClient


def test_health_check_with_fallback_retries_slash_when_primary_is_404():
    with patch.object(AdapterHttpClient, "_probe_health_path") as probe:
        probe.side_effect = [
            (False, "status=404", 404),
            (True, "ok", 200),
        ]
        client = AdapterHttpClient(base_url="https://example.com/api")
        ok, msg = client.health_check_with_fallback("/health")
    assert ok is True
    assert msg == "ok"
    assert probe.call_count == 2


def test_health_check_with_fallback_no_retry_when_not_404():
    with patch.object(AdapterHttpClient, "_probe_health_path") as probe:
        probe.return_value = (False, "status=403", 403)
        client = AdapterHttpClient(base_url="https://example.com/api")
        ok, msg = client.health_check_with_fallback("/health")
    assert ok is False
    assert "403" in msg
    assert probe.call_count == 1


def test_health_check_with_fallback_no_retry_when_transport_error():
    with patch.object(AdapterHttpClient, "_probe_health_path") as probe:
        probe.return_value = (False, "connection refused", None)
        client = AdapterHttpClient(base_url="https://example.com/api")
        ok, msg = client.health_check_with_fallback("/health")
    assert ok is False
    assert msg == "connection refused"
    assert probe.call_count == 1
