"""Tests for production health checks and Prometheus metrics."""

from unittest.mock import patch

import pytest

from claim_agent.observability.health import check_health, is_healthy
from claim_agent.observability.prometheus import (
    record_claim_outcome,
    record_llm_tokens,
    generate_metrics,
)


class TestHealth:
    @pytest.fixture(autouse=True)
    def _clear_health_check_notifications_env(self, monkeypatch):
        monkeypatch.delenv("HEALTH_CHECK_NOTIFICATIONS", raising=False)

    def test_check_health_db_ok(self):
        """When DB is connected, status is ok and database check passes."""
        result = check_health()
        assert result["status"] == "ok"
        assert result["checks"]["database"] == "ok"
        assert result["checks"]["llm"] in ("skipped", "ok", "degraded")

    def test_check_health_db_down(self):
        """When DB fails, status is degraded and database check is error."""
        with patch("claim_agent.observability.health.get_connection") as m:
            m.side_effect = Exception("connection refused")
            result = check_health()
        assert result["status"] == "degraded"
        assert result["checks"]["database"] == "error"

    def test_is_healthy_when_db_ok(self):
        """is_healthy returns True when check_health status is ok."""
        assert is_healthy() is True

    def test_is_healthy_when_db_down(self):
        """is_healthy returns False when database is down."""
        with patch("claim_agent.observability.health.get_connection") as m:
            m.side_effect = Exception("db down")
            assert is_healthy() is False

    def test_health_check_llm_skipped_by_default(self, monkeypatch):
        """LLM check is skipped when HEALTH_CHECK_LLM is not set."""
        monkeypatch.delenv("HEALTH_CHECK_LLM", raising=False)
        result = check_health()
        assert result["checks"]["llm"] == "skipped"

    def test_health_check_includes_adapter_policy_skipped_when_mock(self):
        """Adapter checks are skipped when backend is mock."""
        result = check_health()
        assert "adapter_policy" in result["checks"]
        assert result["checks"]["adapter_policy"] == "skipped"

    def test_health_check_adapter_rest_includes_probe(self, monkeypatch):
        """When POLICY_ADAPTER=rest, adapter_policy is probed."""
        from unittest.mock import MagicMock, patch

        from claim_agent.adapters import reset_adapters

        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "rest")
        monkeypatch.setenv("POLICY_REST_BASE_URL", "https://pas.example.com/api/v1")
        from claim_agent.config import reload_settings

        reload_settings()

        with patch(
            "claim_agent.adapters.real.policy_rest.AdapterHttpClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.health_check_with_fallback.return_value = (True, "ok")
            mock_client_cls.return_value = mock_client
            result = check_health()
        assert result["checks"]["adapter_policy"] == "ok"

    def test_health_check_nmvtis_rest_includes_probe(self, monkeypatch):
        """When NMVTIS_ADAPTER=rest, adapter_nmvtis is probed."""
        from unittest.mock import MagicMock, patch

        from claim_agent.adapters import reset_adapters

        reset_adapters()
        monkeypatch.setenv("NMVTIS_ADAPTER", "rest")
        monkeypatch.setenv("NMVTIS_REST_BASE_URL", "https://nmvtis.example.com/api/v1")
        from claim_agent.config import reload_settings

        reload_settings()

        with patch(
            "claim_agent.adapters.real.nmvtis_rest.AdapterHttpClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.health_check_with_fallback.return_value = (True, "ok")
            mock_client_cls.return_value = mock_client
            result = check_health()
        assert result["checks"]["adapter_nmvtis"] == "ok"

    def test_health_check_fraud_reporting_rest_skipped_without_health_method(
        self, monkeypatch
    ):
        """REST fraud adapter has no health_check; report skipped not error."""
        from claim_agent.adapters import reset_adapters

        reset_adapters()
        monkeypatch.setenv("FRAUD_REPORTING_ADAPTER", "rest")
        monkeypatch.setenv(
            "FRAUD_REPORTING_REST_BASE_URL", "https://fraud.example.com/api/v1"
        )
        from claim_agent.config import reload_settings

        reload_settings()
        result = check_health()
        assert result["checks"]["adapter_fraud_reporting"] == "skipped"

    def test_health_check_malformed_adapter_health_check_return(self, monkeypatch):
        """Bad health_check return shape surfaces as error:* without crashing."""
        from unittest.mock import patch

        from claim_agent.adapters import reset_adapters

        reset_adapters()
        monkeypatch.setenv("OCR_ADAPTER", "rest")
        monkeypatch.setenv("OCR_REST_BASE_URL", "https://ocr.example.com/api/v1")
        from claim_agent.config import reload_settings

        reload_settings()

        class BadAdapter:
            def health_check(self):
                return ()

        with patch(
            "claim_agent.adapters.registry.get_ocr_adapter",
            return_value=BadAdapter(),
        ):
            result = check_health()
        assert result["checks"]["adapter_ocr"].startswith("error:")

    def test_health_check_includes_extended_adapter_keys(self):
        """All wired adapter names appear under checks (mock backends → skipped)."""
        result = check_health()
        for key in (
            "adapter_fraud_reporting",
            "adapter_state_bureau",
            "adapter_claim_search",
            "adapter_erp",
            "adapter_nmvtis",
            "adapter_gap_insurance",
            "adapter_ocr",
            "adapter_cms",
            "adapter_reverse_image",
        ):
            assert key in result["checks"], f"missing {key}"
            assert result["checks"][key] == "skipped"

    def test_health_check_notifications_skipped_by_default(self, monkeypatch):
        monkeypatch.delenv("HEALTH_CHECK_NOTIFICATIONS", raising=False)
        result = check_health()
        assert result["checks"]["notifications"] == "skipped"

    def test_health_check_notifications_ok_when_channel_ready(self, monkeypatch):
        monkeypatch.setenv("HEALTH_CHECK_NOTIFICATIONS", "true")
        with patch(
            "claim_agent.notifications.claimant.check_notification_readiness",
            return_value={
                "email_ready": True,
                "sms_ready": False,
                "warnings": [],
            },
        ):
            result = check_health()
        assert result["checks"]["notifications"] == "ok"
        assert result["status"] == "ok"

    def test_health_check_notifications_degraded_when_none_ready(self, monkeypatch):
        monkeypatch.setenv("HEALTH_CHECK_NOTIFICATIONS", "true")
        with patch(
            "claim_agent.notifications.claimant.check_notification_readiness",
            return_value={
                "email_ready": False,
                "sms_ready": False,
                "warnings": ["both off"],
            },
        ):
            result = check_health()
        assert result["checks"]["notifications"] == "degraded:no notification channel ready"
        assert result["status"] == "degraded"


class TestPrometheus:
    def test_record_claim_outcome_escalated(self):
        """record_claim_outcome increments claims_escalated_total."""
        record_claim_outcome("CLM-001", "escalated", 5.0)
        output = generate_metrics().decode()
        assert "claims_escalated_total" in output

    def test_record_claim_outcome_processed(self):
        """record_claim_outcome increments claims_processed_total for success."""
        record_claim_outcome("CLM-002", "settled", 30.0)
        output = generate_metrics().decode()
        assert "claims_processed_total" in output

    def test_record_claim_outcome_failed(self):
        """record_claim_outcome increments claims_failed_total for error."""
        record_claim_outcome("CLM-003", "error", 2.0)
        output = generate_metrics().decode()
        assert "claims_failed_total" in output

    def test_record_llm_tokens(self):
        """record_llm_tokens increments llm_tokens_total."""
        record_llm_tokens(100, 50)
        output = generate_metrics().decode()
        assert "llm_tokens_total" in output
        assert 'type="input"' in output or "type=\"input\"" in output
        assert 'type="output"' in output or "type=\"output\"" in output

    def test_generate_metrics_includes_gauges(self):
        """generate_metrics includes claims_in_progress and review_queue_size."""
        output = generate_metrics().decode()
        assert "claims_in_progress" in output
        assert "review_queue_size" in output

    def test_generate_metrics_prometheus_format(self):
        """generate_metrics returns valid Prometheus text format."""
        output = generate_metrics().decode()
        # Prometheus format: lines are # comments or "name value" or "name{labels} value"
        assert output  # non-empty
        lines = [ln for ln in output.splitlines() if ln and not ln.startswith("#")]
        # Should have at least our metrics
        metric_names = {ln.split()[0].split("{")[0] for ln in lines}
        assert "claims_processed_total" in metric_names or "claims_in_progress" in metric_names


class TestHealthEndpoints:
    """Integration tests for health and metrics endpoints."""

    @pytest.fixture(autouse=True)
    def _clear_health_check_notifications_env(self, monkeypatch):
        monkeypatch.delenv("HEALTH_CHECK_NOTIFICATIONS", raising=False)

    def test_health_returns_200_when_db_ok(self):
        """GET /api/health returns 200 when database is connected."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "ok"

    def test_health_aliases(self):
        """GET /health and /healthz return same response as /api/health."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        for path in ("/health", "/healthz"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_health_trailing_slash(self):
        """GET /api/health/ and /health/ work (path normalization for load balancers)."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        for path in ("/api/v1/health/", "/health/"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_metrics_returns_prometheus_format(self):
        """GET /metrics returns Prometheus text format."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        content = resp.text
        assert "claims_" in content or "llm_tokens" in content

    def test_health_returns_503_when_db_down(self):
        """GET /api/health returns 503 when database is down."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        with patch("claim_agent.observability.health.get_connection") as m:
            m.side_effect = Exception("connection refused")
            client = TestClient(app)
            resp = client.get("/api/v1/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "error"
