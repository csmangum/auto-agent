"""Unit tests for portal token hashing and last-used inactivity helper."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from claim_agent.services.portal_token_utils import (
    hash_portal_token,
    portal_token_last_used_rejects,
)


def test_hash_portal_token_is_deterministic_sha256() -> None:
    h = hash_portal_token("same-secret")
    assert h == hash_portal_token("same-secret")
    assert len(h) == 64


def test_last_used_none_never_rejects() -> None:
    cutoff = datetime.now(timezone.utc)
    assert not portal_token_last_used_rejects(
        None,
        cutoff,
        logger=logging.getLogger("test"),
        inactive_log="x",
        inactive_args=(),
        token_id=1,
    )


def test_last_used_recent_never_rejects() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=3)
    assert not portal_token_last_used_rejects(
        now.isoformat(),
        cutoff,
        logger=logging.getLogger("test"),
        inactive_log="inactive %s",
        inactive_args=("x",),
        token_id=1,
    )


def test_last_used_stale_rejects() -> None:
    log = logging.getLogger("test_inactive")
    cutoff = datetime.now(timezone.utc)
    old = (cutoff - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    assert portal_token_last_used_rejects(
        old,
        cutoff,
        logger=log,
        inactive_log="gone %s",
        inactive_args=("cid",),
        token_id=99,
    )


def test_last_used_unparseable_rejects_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("test_bad_ts")
    cutoff = datetime.now(timezone.utc)
    with caplog.at_level(logging.WARNING, logger="test_bad_ts"):
        assert portal_token_last_used_rejects(
            "not-a-date",
            cutoff,
            logger=log,
            inactive_log="inactive",
            inactive_args=(),
            token_id=42,
        )
    assert "Unparseable last_used_at" in caplog.text
    assert "42" in caplog.text
