"""Lightweight tests for unified portal token verification (no FastAPI import chain)."""

from __future__ import annotations

import sqlite3

import pytest

from claim_agent.services.unified_portal_tokens import (
    create_unified_portal_token,
    verify_unified_portal_token,
)


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


def test_corrupted_scopes_json_returns_none(seeded_temp_db):
    raw = create_unified_portal_token(
        "claimant",
        scopes=["read_claim"],
        claim_id="CLM-TEST001",
        db_path=seeded_temp_db,
    )
    assert verify_unified_portal_token(raw, db_path=seeded_temp_db) is not None
    conn = sqlite3.connect(seeded_temp_db)
    conn.execute("UPDATE external_portal_tokens SET scopes = 'not-json'")
    conn.commit()
    conn.close()
    assert verify_unified_portal_token(raw, db_path=seeded_temp_db) is None


def test_non_list_scopes_returns_none(seeded_temp_db):
    raw = create_unified_portal_token(
        "claimant",
        scopes=["read_claim"],
        claim_id="CLM-TEST001",
        db_path=seeded_temp_db,
    )
    conn = sqlite3.connect(seeded_temp_db)
    conn.execute('UPDATE external_portal_tokens SET scopes = \'"read_claim"\'')
    conn.commit()
    conn.close()
    assert verify_unified_portal_token(raw, db_path=seeded_temp_db) is None
