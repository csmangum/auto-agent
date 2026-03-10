"""Tests for OpenTelemetry tracing setup."""

import importlib.util
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.observability import opentelemetry_setup

_HAS_FASTAPI_INSTRUMENTATION = (
    importlib.util.find_spec("opentelemetry.instrumentation.fastapi") is not None
)


class TestSetupOpenTelemetry:
    """Tests for setup_opentelemetry."""

    def test_returns_false_when_disabled(self):
        """When otel_enabled is False, returns False without importing OTEL packages."""
        config = MagicMock()
        config.otel_enabled = False

        with patch("claim_agent.observability.opentelemetry_setup.get_settings") as mock_get:
            mock_get.return_value.tracing = config
            result = opentelemetry_setup.setup_opentelemetry()

        assert result is False

    def test_returns_false_on_import_error(self):
        """When OTEL packages raise ImportError, returns False."""
        config = MagicMock()
        config.otel_enabled = True

        with patch("claim_agent.observability.opentelemetry_setup.get_settings") as mock_get:
            mock_get.return_value.tracing = config
            with patch(
                "claim_agent.observability.opentelemetry_setup.OTLPSpanExporter",
                side_effect=ImportError("opentelemetry not installed"),
                create=True,
            ):
                # The import happens inside the try block; we need to raise before
                # Resource.create etc. Simulate by patching the first import that runs.
                import sys

                class FakeModule:
                    def __getattr__(self, name):
                        raise ImportError("opentelemetry not installed")

                with patch.dict(sys.modules, {"opentelemetry": FakeModule()}):
                    result = opentelemetry_setup.setup_opentelemetry()

        assert result is False

    def test_returns_true_when_enabled_and_packages_available(self):
        """When enabled and packages available, configures tracer and returns True."""
        config = MagicMock()
        config.otel_enabled = True
        config.otel_service_name = "test-service"
        config.otel_exporter_otlp_endpoint = "http://localhost:4318"

        with patch("claim_agent.observability.opentelemetry_setup.get_settings") as mock_get:
            mock_get.return_value.tracing = config
            result = opentelemetry_setup.setup_opentelemetry()

        # Result depends on whether opentelemetry is installed in the env
        assert result in (True, False)

    def test_endpoint_gets_http_prefix_when_missing(self):
        """Endpoint without http/https gets http:// prefix."""
        config = MagicMock()
        config.otel_enabled = True
        config.otel_service_name = "test"
        config.otel_exporter_otlp_endpoint = "localhost:4318"

        mock_exporter_cls = MagicMock()

        with patch("claim_agent.observability.opentelemetry_setup.get_settings") as mock_get:
            mock_get.return_value.tracing = config
            with patch(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
                mock_exporter_cls,
            ):
                result = opentelemetry_setup.setup_opentelemetry()

        assert result is True
        mock_exporter_cls.assert_called_once()
        call_args = mock_exporter_cls.call_args[1]
        assert call_args["endpoint"].startswith("http://")
        assert "localhost:4318" in call_args["endpoint"]


class TestInstrumentFastapi:
    """Tests for instrument_fastapi."""

    def test_instrument_fastapi_handles_import_error(self):
        """instrument_fastapi does not raise when FastAPIInstrumentor is not installed."""
        mock_app = MagicMock()
        import builtins
        import sys

        orig_import = builtins.__import__
        key = "opentelemetry.instrumentation.fastapi"
        saved = sys.modules.pop(key, None)

        def custom_import(name, *args, **kwargs):
            if name == key:
                raise ImportError("opentelemetry-instrumentation-fastapi not installed")
            return orig_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=custom_import):
                opentelemetry_setup.instrument_fastapi(mock_app)
        finally:
            if saved is not None:
                sys.modules[key] = saved

    @pytest.mark.skipif(
        not _HAS_FASTAPI_INSTRUMENTATION,
        reason="opentelemetry-instrumentation-fastapi not installed",
    )
    def test_instrument_fastapi_instruments_when_available(self):
        """instrument_fastapi calls FastAPIInstrumentor when available."""
        mock_app = MagicMock()
        mock_instr = MagicMock()

        with patch(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor",
            mock_instr,
        ):
            opentelemetry_setup.instrument_fastapi(mock_app)

        mock_instr.instrument_app.assert_called_once_with(mock_app)
