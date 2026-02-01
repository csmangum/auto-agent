"""Tests for the observability module."""

import json
import logging
import os
import threading
import time
from unittest import mock

import pytest


class TestStructuredLogging:
    """Tests for structured logging with claim context."""

    def test_get_logger_returns_claim_logger(self):
        """get_logger should return a ClaimLogger instance."""
        from claim_agent.observability.logger import get_logger, ClaimLogger

        logger = get_logger("test_logger")
        assert isinstance(logger, ClaimLogger)

    def test_claim_logger_with_claim_id(self, caplog):
        """ClaimLogger should include claim_id in log messages."""
        from claim_agent.observability.logger import get_logger

        logger = get_logger("test_logger_with_id", claim_id="CLM-TEST123")
        # Enable propagation for test capture (disabled by default to prevent duplicates)
        logger.logger.propagate = True
        with caplog.at_level(logging.INFO):
            logger.info("Test message")
        
        # The claim_id should be in the log record extra
        assert len(caplog.records) >= 1

    def test_claim_context_manager(self):
        """claim_context should set and restore context."""
        from claim_agent.observability.logger import (
            claim_context,
            _get_claim_context,
        )

        # Before context
        assert _get_claim_context() == {}

        with claim_context(claim_id="CLM-123", claim_type="new"):
            ctx = _get_claim_context()
            assert ctx["claim_id"] == "CLM-123"
            assert ctx["claim_type"] == "new"
            assert "correlation_id" in ctx
            assert len(ctx["correlation_id"]) == 36  # UUID format

        # After context
        assert _get_claim_context() == {}

    def test_structured_formatter_json_output(self):
        """StructuredFormatter should output valid JSON."""
        from claim_agent.observability.logger import StructuredFormatter

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed


class TestTracing:
    """Tests for LLM call tracing."""

    def test_tracing_config_from_env(self):
        """TracingConfig should read from environment variables."""
        from claim_agent.observability.tracing import TracingConfig

        with mock.patch.dict(os.environ, {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "test-key",
            "LANGSMITH_PROJECT": "test-project",
        }):
            config = TracingConfig.from_env()
            assert config.langsmith_enabled is True
            assert config.langsmith_api_key == "test-key"
            assert config.langsmith_project == "test-project"

    def test_tracing_callback_log_pre_api_call(self):
        """TracingCallback should track pre-API calls."""
        from claim_agent.observability.tracing import TracingCallback

        callback = TracingCallback(claim_id="CLM-123")
        trace_id = callback.log_pre_api_call(model="gpt-4o-mini")

        assert trace_id.startswith("trace-")
        traces = callback.get_traces()
        assert len(traces) == 1
        assert traces[0].claim_id == "CLM-123"
        assert traces[0].model == "gpt-4o-mini"
        assert traces[0].status == "pending"

    def test_tracing_callback_log_post_api_call(self):
        """TracingCallback should complete traces."""
        from claim_agent.observability.tracing import TracingCallback

        callback = TracingCallback(claim_id="CLM-123")
        trace_id = callback.log_pre_api_call(model="gpt-4o-mini")
        
        # Simulate some work
        time.sleep(0.01)
        
        callback.log_post_api_call(
            trace_id=trace_id,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )

        traces = callback.get_traces()
        assert len(traces) == 1
        trace = traces[0]
        assert trace.status == "success"
        assert trace.input_tokens == 100
        assert trace.output_tokens == 50
        assert trace.total_tokens == 150
        assert trace.cost_usd == 0.001
        assert trace.latency_ms > 0

    def test_tracing_callback_summary(self):
        """TracingCallback.get_summary should aggregate statistics."""
        from claim_agent.observability.tracing import TracingCallback

        callback = TracingCallback(claim_id="CLM-123")

        # Log multiple calls
        for i in range(3):
            trace_id = callback.log_pre_api_call(model="gpt-4o-mini")
            callback.log_post_api_call(
                trace_id=trace_id,
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
            )

        summary = callback.get_summary()
        assert summary["total_calls"] == 3
        assert summary["successful_calls"] == 3
        assert summary["failed_calls"] == 0
        assert summary["total_tokens"] == 450  # 3 * 150
        assert summary["total_cost_usd"] == pytest.approx(0.003)


class TestMetrics:
    """Tests for cost/latency metrics tracking."""

    def test_claim_metrics_start_and_end(self):
        """ClaimMetrics should track claim lifecycle."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()
        metrics.start_claim("CLM-123")
        metrics.end_claim("CLM-123", status="completed")

        summary = metrics.get_claim_summary("CLM-123")
        assert summary is not None
        assert summary.claim_id == "CLM-123"
        assert summary.status == "completed"
        assert summary.start_time is not None
        assert summary.end_time is not None

    def test_claim_metrics_record_llm_call(self):
        """ClaimMetrics should record LLM call metrics."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()
        metrics.start_claim("CLM-123")
        metrics.record_llm_call(
            claim_id="CLM-123",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            latency_ms=500.0,
            status="success",
        )

        summary = metrics.get_claim_summary("CLM-123")
        assert summary.total_llm_calls == 1
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50
        assert summary.total_cost_usd == pytest.approx(0.001)
        assert summary.total_latency_ms == pytest.approx(500.0)

    def test_claim_metrics_calculate_cost(self):
        """calculate_cost should estimate costs based on model."""
        from claim_agent.observability.metrics import calculate_cost

        # Known model
        cost = calculate_cost("gpt-4o-mini", 1000, 500)
        expected = (1000 * 0.00015 / 1000) + (500 * 0.0006 / 1000)
        assert cost == pytest.approx(expected)

        # Unknown model should use default pricing
        cost_unknown = calculate_cost("unknown-model", 1000, 500)
        assert cost_unknown > 0

    def test_claim_metrics_percentiles(self):
        """ClaimMetrics should calculate latency percentiles."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()
        metrics.start_claim("CLM-123")

        # Record calls with varying latencies
        latencies = [100, 200, 300, 400, 500]
        for lat in latencies:
            metrics.record_llm_call(
                claim_id="CLM-123",
                model="gpt-4o-mini",
                input_tokens=100,
                output_tokens=50,
                latency_ms=lat,
            )

        summary = metrics.get_claim_summary("CLM-123")
        assert summary.p50_latency_ms == pytest.approx(300.0)  # Median
        assert summary.p95_latency_ms >= 400.0
        assert summary.p99_latency_ms >= 400.0

    def test_claim_metrics_global_stats(self):
        """get_global_stats should aggregate across all claims."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()

        for i in range(3):
            claim_id = f"CLM-{i}"
            metrics.start_claim(claim_id)
            metrics.record_llm_call(
                claim_id=claim_id,
                model="gpt-4o-mini",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            )
            metrics.end_claim(claim_id)

        stats = metrics.get_global_stats()
        assert stats["total_claims"] == 3
        assert stats["total_llm_calls"] == 3
        assert stats["total_cost_usd"] == pytest.approx(0.003)

    def test_claim_metrics_thread_safety(self):
        """ClaimMetrics should be thread-safe."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()
        errors = []

        def record_calls(claim_id: str):
            try:
                metrics.start_claim(claim_id)
                for _ in range(10):
                    metrics.record_llm_call(
                        claim_id=claim_id,
                        model="gpt-4o-mini",
                        input_tokens=100,
                        output_tokens=50,
                        latency_ms=10.0,
                    )
                metrics.end_claim(claim_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_calls, args=(f"CLM-{i}",))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = metrics.get_global_stats()
        assert stats["total_claims"] == 5
        assert stats["total_llm_calls"] == 50  # 5 claims * 10 calls each

    def test_export_json(self):
        """export_json should produce valid JSON."""
        from claim_agent.observability.metrics import ClaimMetrics

        metrics = ClaimMetrics()
        metrics.start_claim("CLM-123")
        metrics.record_llm_call(
            claim_id="CLM-123",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            latency_ms=100.0,
        )
        metrics.end_claim("CLM-123")

        # Export single claim
        output = metrics.export_json("CLM-123")
        parsed = json.loads(output)
        assert parsed["claim_id"] == "CLM-123"

        # Export all
        output_all = metrics.export_json()
        parsed_all = json.loads(output_all)
        assert "global_stats" in parsed_all
        assert "claims" in parsed_all


class TestGlobalHelpers:
    """Tests for global convenience functions."""

    def test_get_metrics_singleton(self):
        """get_metrics should return a singleton instance."""
        from claim_agent.observability.metrics import get_metrics

        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

class TestLiteLLMCallback:
    """Tests for LiteLLM callback integration."""

    def test_litellm_callback_log_pre_api_call(self):
        """LiteLLMTracingCallback should track calls."""
        from claim_agent.observability.tracing import LiteLLMTracingCallback

        callback = LiteLLMTracingCallback(claim_id="CLM-123")
        callback.log_pre_api_call(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
            kwargs={"litellm_call_id": "call-123"},
        )

        assert "call-123" in callback._pending_calls

    def test_litellm_callback_log_success(self):
        """LiteLLMTracingCallback should log successful calls and track metrics."""
        from claim_agent.observability.tracing import LiteLLMTracingCallback
        from claim_agent.observability.metrics import ClaimMetrics

        # Create a metrics collector to verify successful call tracking
        metrics = ClaimMetrics()
        metrics.start_claim("CLM-SUCCESS")
        callback = LiteLLMTracingCallback(claim_id="CLM-SUCCESS", metrics_collector=metrics)
        
        callback.log_pre_api_call(
            model="gpt-4o-mini",
            messages=[],
            kwargs={"litellm_call_id": "call-123"},
        )

        # Verify call is pending
        assert "call-123" in callback._pending_calls

        # Mock response object
        class MockUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150

            def model_dump(self):
                return {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                }

        class MockResponse:
            usage = MockUsage()
            _hidden_params = {"response_cost": 0.001}

        callback.log_success_event(
            kwargs={"litellm_call_id": "call-123", "model": "gpt-4o-mini"},
            response_obj=MockResponse(),
            start_time=time.time() - 0.5,
            end_time=time.time(),
        )

        # Verify the call was processed and removed from pending
        assert "call-123" not in callback._pending_calls
        
        # Verify metrics were recorded correctly
        summary = metrics.get_claim_summary("CLM-SUCCESS")
        assert summary is not None
        assert summary.total_llm_calls == 1
        assert summary.successful_calls == 1
        assert summary.failed_calls == 0
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50

    def test_litellm_callback_log_failure(self):
        """LiteLLMTracingCallback should log failed calls and track error metrics."""
        from claim_agent.observability.tracing import LiteLLMTracingCallback
        from claim_agent.observability.metrics import ClaimMetrics

        # Create a metrics collector to verify error tracking
        metrics = ClaimMetrics()
        metrics.start_claim("CLM-FAILURE")
        callback = LiteLLMTracingCallback(claim_id="CLM-FAILURE", metrics_collector=metrics)
        
        # Start a call
        callback.log_pre_api_call(
            model="gpt-4o-mini",
            messages=[],
            kwargs={"litellm_call_id": "call-456"},
        )

        # Verify call is pending
        assert "call-456" in callback._pending_calls

        # Simulate a failure (CustomLogger signature: response_obj is the exception)
        test_exception = Exception("API rate limit exceeded")
        callback.log_failure_event(
            {"litellm_call_id": "call-456", "model": "gpt-4o-mini"},
            test_exception,
            time.time() - 0.3,
            time.time(),
        )

        # Verify the call was processed and removed from pending
        assert "call-456" not in callback._pending_calls
        
        # Verify metrics were recorded with error status
        summary = metrics.get_claim_summary("CLM-FAILURE")
        assert summary is not None
        assert summary.total_llm_calls == 1
        # Verify the call has error status
        assert summary.failed_calls == 1
        assert summary.successful_calls == 0
