"""Tests for production health checks and Prometheus metrics."""

from unittest.mock import patch

from claim_agent.observability.health import check_health, is_healthy
from claim_agent.observability.prometheus import (
    record_claim_outcome,
    record_llm_tokens,
    generate_metrics,
)


class TestHealth:
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

    def test_health_returns_200_when_db_ok(self):
        """GET /api/health returns 200 when database is connected."""
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        resp = client.get("/api/health")
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
        for path in ("/api/health/", "/health/"):
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
            resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "error"
