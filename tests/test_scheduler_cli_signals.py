"""Tests for dedicated scheduler CLI: signal wiring and wait loop."""

from __future__ import annotations

import signal
import threading
from unittest.mock import patch

from claim_agent.main import _register_scheduler_shutdown_signals, _run_scheduler_until_stopped


def test_register_scheduler_shutdown_signals_invokes_handlers():
    stop = threading.Event()

    registered: dict[int, object] = {}

    def fake_signal(sig: int, handler: object) -> object:
        registered[sig] = handler
        return signal.SIG_DFL

    with patch("claim_agent.main.signal.signal", side_effect=fake_signal):
        _register_scheduler_shutdown_signals(stop)

    assert signal.SIGINT in registered
    if hasattr(signal, "SIGTERM"):
        assert signal.SIGTERM in registered
        registered[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[misc]
    assert stop.is_set()


def test_run_scheduler_until_stopped_returns_when_event_set():
    ev = threading.Event()
    ev.set()
    _run_scheduler_until_stopped(ev)  # should return immediately
