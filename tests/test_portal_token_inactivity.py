"""Tests for portal token inactivity timeout enforcement.

Validates that all four portal token verification functions:
1. Accept tokens that have been used recently (within the inactivity window).
2. Reject tokens that have NOT been used within the inactivity window.
3. Update ``last_used_at`` on each successful verification.
4. Accept tokens that have never been used (NULL last_used_at) regardless of age,
   since there is no evidence of inactivity yet — the token may simply be new.
5. Reject tokens when ``last_used_at`` is present but unparseable (fail closed).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from claim_agent.services.portal_verification import (
    create_claim_access_token,
    get_claim_ids_for_claimant,
    verify_claimant_access,
)
from claim_agent.services.repair_shop_portal_tokens import (
    create_repair_shop_access_token,
    verify_repair_shop_token,
)
from claim_agent.services.third_party_portal_tokens import (
    create_third_party_access_token,
    verify_third_party_token,
)
from claim_agent.services.unified_portal_tokens import (
    create_unified_portal_token,
    verify_unified_portal_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_last_used(db_path: str, table: str, days_ago: float) -> None:
    """Directly set last_used_at to *days_ago* days before now in *table*."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"UPDATE {table} SET last_used_at = ?", (ts,))  # noqa: S608
        conn.commit()


def _get_last_used(db_path: str, table: str) -> str | None:
    """Fetch last_used_at from *table* (expects a single row)."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(f"SELECT last_used_at FROM {table}").fetchone()  # noqa: S608
    return row[0] if row else None


def _set_last_used_raw(db_path: str, table: str, value: str) -> None:
    """Set last_used_at to an arbitrary string (for malformed-value tests)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"UPDATE {table} SET last_used_at = ?", (value,))  # noqa: S608
        conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _enable_portals(monkeypatch):
    """Enable all three portals for the duration of each test."""
    monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
    monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
    monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
    # Use a short inactivity timeout (3 days) so tests can simulate expiry easily
    monkeypatch.setenv("CLAIM_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    monkeypatch.setenv("THIRD_PARTY_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    from claim_agent.config import reload_settings

    reload_settings()
    yield
    reload_settings()


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


# ---------------------------------------------------------------------------
# Claimant portal – verify_claimant_access
# ---------------------------------------------------------------------------

class TestClaimantInactivityVerifyAccess:
    def test_fresh_token_no_last_used_is_accepted(self, seeded_temp_db):
        """Tokens with NULL last_used_at should be accepted (they are new)."""
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        result = verify_claimant_access(
            "CLM-TEST001", token=raw, db_path=seeded_temp_db
        )
        assert result is not None
        assert result.claim_id == "CLM-TEST001"

    def test_recently_used_token_is_accepted(self, seeded_temp_db):
        """Tokens used 1 day ago (within 3-day window) should be accepted."""
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "claim_access_tokens", days_ago=1)
        result = verify_claimant_access(
            "CLM-TEST001", token=raw, db_path=seeded_temp_db
        )
        assert result is not None

    def test_inactive_token_is_rejected(self, seeded_temp_db):
        """Tokens not used for more than the inactivity timeout should be rejected."""
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "claim_access_tokens", days_ago=5)
        result = verify_claimant_access(
            "CLM-TEST001", token=raw, db_path=seeded_temp_db
        )
        assert result is None

    def test_last_used_at_is_updated_on_success(self, seeded_temp_db):
        """Successful verification must update last_used_at."""
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        before = _get_last_used(seeded_temp_db, "claim_access_tokens")
        assert before is None  # Not yet used
        verify_claimant_access("CLM-TEST001", token=raw, db_path=seeded_temp_db)
        after = _get_last_used(seeded_temp_db, "claim_access_tokens")
        assert after is not None


# ---------------------------------------------------------------------------
# Claimant portal – get_claim_ids_for_claimant
# ---------------------------------------------------------------------------

class TestClaimantInactivityGetClaimIds:
    def test_fresh_token_returns_claims(self, seeded_temp_db):
        """Tokens with NULL last_used_at should be included."""
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        ids = get_claim_ids_for_claimant(token=raw, db_path=seeded_temp_db)
        assert "CLM-TEST001" in ids

    def test_recently_used_token_returns_claims(self, seeded_temp_db):
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "claim_access_tokens", days_ago=1)
        ids = get_claim_ids_for_claimant(token=raw, db_path=seeded_temp_db)
        assert "CLM-TEST001" in ids

    def test_inactive_token_excluded(self, seeded_temp_db):
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "claim_access_tokens", days_ago=10)
        ids = get_claim_ids_for_claimant(token=raw, db_path=seeded_temp_db)
        assert ids == []

    def test_last_used_at_is_updated(self, seeded_temp_db):
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "claim_access_tokens") is None
        get_claim_ids_for_claimant(token=raw, db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "claim_access_tokens") is not None


# ---------------------------------------------------------------------------
# Repair shop portal – verify_repair_shop_token
# ---------------------------------------------------------------------------

class TestRepairShopInactivity:
    def test_fresh_token_accepted(self, seeded_temp_db):
        raw = create_repair_shop_access_token("CLM-TEST001", db_path=seeded_temp_db)
        result = verify_repair_shop_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is not None
        assert result.claim_id == "CLM-TEST001"

    def test_recently_used_token_accepted(self, seeded_temp_db):
        raw = create_repair_shop_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "repair_shop_access_tokens", days_ago=2)
        result = verify_repair_shop_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is not None

    def test_inactive_token_rejected(self, seeded_temp_db):
        raw = create_repair_shop_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "repair_shop_access_tokens", days_ago=7)
        result = verify_repair_shop_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is None

    def test_last_used_at_updated_on_success(self, seeded_temp_db):
        raw = create_repair_shop_access_token("CLM-TEST001", db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "repair_shop_access_tokens") is None
        verify_repair_shop_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "repair_shop_access_tokens") is not None


# ---------------------------------------------------------------------------
# Third-party portal – verify_third_party_token
# ---------------------------------------------------------------------------

class TestThirdPartyInactivity:
    def test_fresh_token_accepted(self, seeded_temp_db):
        raw = create_third_party_access_token("CLM-TEST001", db_path=seeded_temp_db)
        result = verify_third_party_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is not None
        assert result.claim_id == "CLM-TEST001"

    def test_recently_used_token_accepted(self, seeded_temp_db):
        raw = create_third_party_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "third_party_access_tokens", days_ago=1)
        result = verify_third_party_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is not None

    def test_inactive_token_rejected(self, seeded_temp_db):
        raw = create_third_party_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used(seeded_temp_db, "third_party_access_tokens", days_ago=10)
        result = verify_third_party_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert result is None

    def test_last_used_at_updated_on_success(self, seeded_temp_db):
        raw = create_third_party_access_token("CLM-TEST001", db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "third_party_access_tokens") is None
        verify_third_party_token("CLM-TEST001", raw, db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "third_party_access_tokens") is not None


# ---------------------------------------------------------------------------
# Unified portal – verify_unified_portal_token
# ---------------------------------------------------------------------------

class TestUnifiedPortalInactivity:
    def test_fresh_token_accepted(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            db_path=seeded_temp_db,
        )
        result = verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert result is not None
        assert result.role == "claimant"

    def test_recently_used_token_accepted(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            db_path=seeded_temp_db,
        )
        _set_last_used(seeded_temp_db, "external_portal_tokens", days_ago=1)
        result = verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert result is not None

    def test_inactive_token_rejected(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            db_path=seeded_temp_db,
        )
        _set_last_used(seeded_temp_db, "external_portal_tokens", days_ago=5)
        result = verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert result is None

    def test_last_used_at_updated_on_success(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim", "update_repair_status"],
            claim_id="CLM-TEST001",
            shop_id="SHOP-1",
            db_path=seeded_temp_db,
        )
        assert _get_last_used(seeded_temp_db, "external_portal_tokens") is None
        verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert _get_last_used(seeded_temp_db, "external_portal_tokens") is not None

    def test_inactive_repair_shop_token_rejected(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            shop_id="SHOP-1",
            db_path=seeded_temp_db,
        )
        _set_last_used(seeded_temp_db, "external_portal_tokens", days_ago=4)
        result = verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert result is None

    def test_inactive_tpa_token_rejected(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "tpa",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            db_path=seeded_temp_db,
        )
        _set_last_used(seeded_temp_db, "external_portal_tokens", days_ago=4)
        result = verify_unified_portal_token(raw, db_path=seeded_temp_db)
        assert result is None


# ---------------------------------------------------------------------------
# Malformed last_used_at (fail closed)
# ---------------------------------------------------------------------------


class TestMalformedLastUsedAt:
    def test_claimant_verify_rejects(self, seeded_temp_db):
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used_raw(seeded_temp_db, "claim_access_tokens", "not-a-date")
        assert (
            verify_claimant_access("CLM-TEST001", token=raw, db_path=seeded_temp_db)
            is None
        )

    def test_claimant_list_claim_ids_empty(self, seeded_temp_db):
        raw = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used_raw(seeded_temp_db, "claim_access_tokens", "bogus")
        assert get_claim_ids_for_claimant(token=raw, db_path=seeded_temp_db) == []

    def test_repair_shop_rejects(self, seeded_temp_db):
        raw = create_repair_shop_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used_raw(seeded_temp_db, "repair_shop_access_tokens", "x")
        assert verify_repair_shop_token("CLM-TEST001", raw, db_path=seeded_temp_db) is None

    def test_third_party_rejects(self, seeded_temp_db):
        raw = create_third_party_access_token("CLM-TEST001", db_path=seeded_temp_db)
        _set_last_used_raw(seeded_temp_db, "third_party_access_tokens", "x")
        assert verify_third_party_token("CLM-TEST001", raw, db_path=seeded_temp_db) is None

    def test_unified_claimant_rejects(self, seeded_temp_db):
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
            db_path=seeded_temp_db,
        )
        _set_last_used_raw(seeded_temp_db, "external_portal_tokens", "nope")
        assert verify_unified_portal_token(raw, db_path=seeded_temp_db) is None
