"""Unit tests for portal token hashing and last-used inactivity helper."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from unittest.mock import MagicMock

from claim_agent.services.portal_token_utils import (
    hash_portal_token,
    portal_token_last_used_rejects,
    refresh_portal_token_last_used,
    verify_inactivity_then_touch_last_used,
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


def test_refresh_portal_token_last_used_executes_allowlisted_sql() -> None:
    conn = MagicMock()
    now = datetime.now(timezone.utc)
    refresh_portal_token_last_used(conn, "claim_access_tokens", 7, now)
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    assert "claim_access_tokens" in str(call_args.args[0])
    assert call_args.args[1] == {"now": now, "token_id": 7}


def test_refresh_portal_token_last_used_unknown_table_raises() -> None:
    conn = MagicMock()
    with pytest.raises(ValueError, match="Unknown portal token table"):
        refresh_portal_token_last_used(conn, "not_a_real_table", 1, datetime.now(timezone.utc))


def test_verify_inactivity_then_touch_last_used_false_when_stale() -> None:
    cutoff = datetime.now(timezone.utc)
    old = (cutoff - timedelta(days=5)).isoformat()
    conn = MagicMock()
    row = {"id": 3, "last_used_at": old}
    ok = verify_inactivity_then_touch_last_used(
        conn,
        row=row,
        table="claim_access_tokens",
        now=cutoff,
        inactivity_cutoff=cutoff,
        logger=logging.getLogger("test_touch"),
        inactive_log="inactive",
        inactive_args=(),
    )
    assert ok is False
    conn.execute.assert_not_called()


def test_verify_inactivity_then_touch_last_used_true_updates_db() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=3)
    conn = MagicMock()
    row = {"id": 9, "last_used_at": now.isoformat()}
    ok = verify_inactivity_then_touch_last_used(
        conn,
        row=row,
        table="repair_shop_access_tokens",
        now=now,
        inactivity_cutoff=cutoff,
        logger=logging.getLogger("test_touch_ok"),
        inactive_log="inactive",
        inactive_args=(),
    )
    assert ok is True
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    assert "repair_shop_access_tokens" in str(call_args.args[0])
    assert call_args.args[1] == {"now": now, "token_id": 9}
