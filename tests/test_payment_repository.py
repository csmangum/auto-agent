"""Tests for payment repository and payment workflow."""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.payment_repository import (
    PaymentRepository,
    settlement_claim_party_id_from_claim_data,
    settlement_payee_from_claim_data,
)
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError, PaymentAuthorityError
from claim_agent.models.payment import (
    ClaimPaymentCreate,
    PaymentMethod,
    PaymentStatus,
    PayeeType,
)


def _insert_claim_party(db_path: str, claim_id: str, party_type: str, name: str) -> int:
    """Helper: insert a claim party row and return its ID."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO claim_parties (claim_id, party_type, name) VALUES (?, ?, ?)",
        (claim_id, party_type, name),
    )
    party_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return int(party_id)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        init_db(path)
        yield path
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.fixture
def seeded_db(temp_db):
    import sqlite3

    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO claims (id, policy_number, vin, status) VALUES (?, ?, ?, ?)",
        ("CLM-TEST01", "POL-001", "VIN123", "open"),
    )
    conn.commit()
    conn.close()
    return temp_db


def test_create_payment(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=1500.0,
        payee="ABC Repair Shop",
        payee_type=PayeeType.REPAIR_SHOP,
        payment_method=PaymentMethod.CHECK,
    )
    pid = repo.create_payment(data, actor_id="adj-1", role="adjuster")
    assert pid > 0
    payment = repo.get_payment(pid)
    assert payment is not None
    assert payment["claim_id"] == "CLM-TEST01"
    assert payment["amount"] == 1500.0
    assert payment["payee"] == "ABC Repair Shop"
    assert payment["payee_type"] == "repair_shop"
    assert payment["status"] == PaymentStatus.AUTHORIZED.value
    assert payment["authorized_by"] == "adj-1"


def test_create_payment_two_party_check(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=5000.0,
        payee="John Doe (Insured)",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        payee_secondary="First National Bank (Lienholder)",
        payee_secondary_type=PayeeType.LIENHOLDER,
    )
    pid = repo.create_payment(data, actor_id="adj-1", role="supervisor", skip_authority_check=True)
    payment = repo.get_payment(pid)
    assert payment["payee_secondary"] == "First National Bank (Lienholder)"
    assert payment["payee_secondary_type"] == "lienholder"


def test_create_payment_claim_not_found(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-NOTFOUND",
        amount=100.0,
        payee="X",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
    )
    with pytest.raises(ClaimNotFoundError):
        repo.create_payment(data, actor_id="adj-1")


def test_create_payment_authority_exceeded(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=10000.0,
        payee="X",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
    )
    with pytest.raises(PaymentAuthorityError):
        repo.create_payment(data, actor_id="adj-1", role="adjuster")


def test_payment_status_transitions(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=500.0,
        payee="ABC Shop",
        payee_type=PayeeType.REPAIR_SHOP,
        payment_method=PaymentMethod.ACH,
    )
    pid = repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)

    # authorized -> issued
    issued = repo.issue_payment(pid, check_number="CHK-123", actor_id="adj-1")
    assert issued["status"] == PaymentStatus.ISSUED.value
    assert issued["check_number"] == "CHK-123"
    assert issued["issued_at"] is not None

    # issued -> cleared
    cleared = repo.clear_payment(pid, actor_id="adj-1")
    assert cleared["status"] == PaymentStatus.CLEARED.value
    assert cleared["cleared_at"] is not None

    # cleared -> voided is invalid
    with pytest.raises(DomainValidationError):
        repo.void_payment(pid, actor_id="adj-1")


def test_void_payment_from_authorized(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=500.0,
        payee="X",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
    )
    pid = repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)
    voided = repo.void_payment(pid, reason="Duplicate payment", actor_id="adj-1")
    assert voided["status"] == PaymentStatus.VOIDED.value
    assert voided["void_reason"] == "Duplicate payment"
    assert voided["voided_at"] is not None


def test_void_payment_from_issued(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=500.0,
        payee="X",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
    )
    pid = repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)
    repo.issue_payment(pid, actor_id="adj-1")
    voided = repo.void_payment(pid, reason="Check lost", actor_id="adj-1")
    assert voided["status"] == PaymentStatus.VOIDED.value


def test_get_payments_for_claim(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    for i in range(3):
        data = ClaimPaymentCreate(
            claim_id="CLM-TEST01",
            amount=100.0 * (i + 1),
            payee=f"Payee{i}",
            payee_type=PayeeType.CLAIMANT,
            payment_method=PaymentMethod.CHECK,
        )
        repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)

    payments, total = repo.get_payments_for_claim("CLM-TEST01")
    assert total == 3
    assert len(payments) == 3


def test_workflow_bypasses_authority(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=150000.0,
        payee="Large Claim",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.WIRE,
    )
    pid = repo.create_payment(data, actor_id="workflow", skip_authority_check=True)
    assert pid > 0


def test_create_payment_external_ref_idempotent(seeded_db):
    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=100.0,
        payee="A",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="idem-1",
    )
    pid1 = repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)
    data2 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=999.0,
        payee="B",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="idem-1",
    )
    pid2 = repo.create_payment(data2, actor_id="adj-1", skip_authority_check=True)
    assert pid1 == pid2
    row = repo.get_payment(pid1)
    assert row is not None
    assert row["amount"] == 100.0
    assert row["external_ref"] == "idem-1"


def test_record_claim_payment_impl(monkeypatch, seeded_db):
    from claim_agent.tools.payment_logic import record_claim_payment_impl

    monkeypatch.setattr("claim_agent.tools.payment_logic.get_db_path", lambda: seeded_db)
    raw = record_claim_payment_impl(
        "CLM-TEST01",
        200.0,
        "Quick Fix Shop",
        "repair_shop",
        "ach",
        external_ref="tool-1",
    )
    data = json.loads(raw)
    assert data["success"] is True
    assert data["payment_id"] > 0


def test_settlement_payee_from_claim_data():
    assert settlement_payee_from_claim_data({}) == "Claimant"
    assert (
        settlement_payee_from_claim_data(
            {"parties": [{"party_type": "claimant", "name": "  Sam  "}]}
        )
        == "Sam"
    )
    assert (
        settlement_payee_from_claim_data(
            {
                "parties": [
                    {"party_type": "witness", "name": "W"},
                    {"party_type": "policyholder", "name": "PH"},
                ]
            }
        )
        == "PH"
    )
    # Edge case: name with only control characters sanitizes to empty, should fallback
    assert (
        settlement_payee_from_claim_data(
            {"parties": [{"party_type": "claimant", "name": "\x01\x02\x03"}]}
        )
        == "Claimant"
    )
    # Edge case: first party has control-only name, second has valid name
    assert (
        settlement_payee_from_claim_data(
            {
                "parties": [
                    {"party_type": "claimant", "name": "\x01"},
                    {"party_type": "claimant", "name": "Valid Name"},
                ]
            }
        )
        == "Valid Name"
    )


def test_create_payment_external_ref_recovers_after_unique_violation(seeded_db, monkeypatch):
    """Stale idempotency read then INSERT unique error: return existing row id."""
    import claim_agent.db.payment_repository as pr_mod

    repo = PaymentRepository(db_path=seeded_db)
    base = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=77.0,
        payee="Primary",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="stale-read-race",
    )
    pid1 = repo.create_payment(base, actor_id="a1", skip_authority_check=True)

    orig_gc = pr_mod.get_connection

    class _ConnProxy:
        __slots__ = ("_real", "_execute_fn")

        def __init__(self, real_conn, execute_fn):
            object.__setattr__(self, "_real", real_conn)
            object.__setattr__(self, "_execute_fn", execute_fn)

        def execute(self, statement, parameters=None, **kwargs):
            return self._execute_fn(statement, parameters, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    @contextmanager
    def flaky_gc(path=None):
        with orig_gc(path) as conn:
            orig_ex = conn.execute
            miss_once = {"due": True}

            def wrapped_execute(statement, parameters=None, **kwargs):
                sql = str(statement)
                if (
                    miss_once["due"]
                    and "SELECT" in sql.upper()
                    and "claim_payments" in sql
                    and parameters
                    and parameters.get("external_ref") == "stale-read-race"
                ):
                    miss_once["due"] = False

                    class _Empty:
                        def fetchone(self):
                            return None

                    return _Empty()
                return orig_ex(statement, parameters, **kwargs)

            yield _ConnProxy(conn, wrapped_execute)

    monkeypatch.setattr(pr_mod, "get_connection", flaky_gc)
    dup = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=999.0,
        payee="Other",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="stale-read-race",
    )
    pid2 = repo.create_payment(dup, actor_id="a2", skip_authority_check=True)
    assert pid1 == pid2
    row = repo.get_payment(pid1)
    assert row is not None
    assert row["amount"] == 77.0


def test_settlement_claim_party_id_from_claim_data():
    assert (
        settlement_claim_party_id_from_claim_data(
            {
                "parties": [
                    {"party_type": "policyholder", "id": 10, "name": "PH"},
                    {"party_type": "claimant", "id": 20, "name": "Jane"},
                ]
            }
        )
        == 20
    )
    assert settlement_claim_party_id_from_claim_data({"parties": []}) is None
    assert (
        settlement_claim_party_id_from_claim_data(
            {"parties": [{"party_type": "claimant", "name": "No id"}]}
        )
        is None
    )


def test_create_payment_with_claim_party_id(seeded_db):
    import sqlite3

    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "INSERT INTO claim_parties (claim_id, party_type, name) VALUES (?, ?, ?)",
        ("CLM-TEST01", "claimant", "Jane Claimant"),
    )
    party_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=100.0,
        payee="Jane Claimant",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        claim_party_id=int(party_id),
    )
    pid = repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)
    payment = repo.get_payment(pid)
    assert payment is not None
    assert payment["claim_party_id"] == int(party_id)


def test_create_payment_claim_party_id_wrong_claim(seeded_db):
    import sqlite3

    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "INSERT INTO claims (id, policy_number, vin, status) VALUES (?, ?, ?, ?)",
        ("CLM-OTHER", "POL-002", "VIN999", "open"),
    )
    conn.execute(
        "INSERT INTO claim_parties (claim_id, party_type, name) VALUES (?, ?, ?)",
        ("CLM-OTHER", "claimant", "Other"),
    )
    party_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    repo = PaymentRepository(db_path=seeded_db)
    data = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=50.0,
        payee="X",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        claim_party_id=int(party_id),
    )
    with pytest.raises(DomainValidationError):
        repo.create_payment(data, actor_id="adj-1", skip_authority_check=True)


def test_idempotent_payment_backfills_null_claim_party_id(seeded_db):
    """When an idempotent payment has NULL claim_party_id, a retry with a valid party should backfill it."""
    party_id = _insert_claim_party(seeded_db, "CLM-TEST01", "claimant", "Jane Claimant")

    repo = PaymentRepository(db_path=seeded_db)
    # First call: no claim_party_id
    data1 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=100.0,
        payee="Jane Claimant",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="backfill-test-1",
    )
    pid1 = repo.create_payment(data1, actor_id="adj-1", skip_authority_check=True)
    payment = repo.get_payment(pid1)
    assert payment is not None
    assert payment["claim_party_id"] is None

    # Second call (retry): same external_ref but now includes claim_party_id
    data2 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=100.0,
        payee="Jane Claimant",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="backfill-test-1",
        claim_party_id=int(party_id),
    )
    pid2 = repo.create_payment(data2, actor_id="adj-1", skip_authority_check=True)
    assert pid1 == pid2
    payment = repo.get_payment(pid1)
    assert payment is not None
    assert payment["claim_party_id"] == int(party_id)


def test_idempotent_payment_raises_on_claim_party_id_mismatch(seeded_db):
    """When an idempotent payment already has a non-NULL claim_party_id, a retry with a different
    party id should raise DomainValidationError rather than silently ignoring the conflict."""
    party_id_a = _insert_claim_party(seeded_db, "CLM-TEST01", "claimant", "Jane Claimant")
    party_id_b = _insert_claim_party(seeded_db, "CLM-TEST01", "policyholder", "PH")

    repo = PaymentRepository(db_path=seeded_db)
    # First call: party_id_a
    data1 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=50.0,
        payee="Jane Claimant",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="mismatch-test-1",
        claim_party_id=int(party_id_a),
    )
    pid1 = repo.create_payment(data1, actor_id="adj-1", skip_authority_check=True)
    payment = repo.get_payment(pid1)
    assert payment is not None
    assert payment["claim_party_id"] == int(party_id_a)

    # Retry with party_id_b: should raise
    data2 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=50.0,
        payee="Jane Claimant",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="mismatch-test-1",
        claim_party_id=int(party_id_b),
    )
    with pytest.raises(DomainValidationError, match="mismatch"):
        repo.create_payment(data2, actor_id="adj-1", skip_authority_check=True)


def test_idempotent_payment_backfill_wrong_claim_party_raises(seeded_db):
    """Backfilling claim_party_id from a different claim should raise DomainValidationError."""
    import sqlite3

    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "INSERT INTO claims (id, policy_number, vin, status) VALUES (?, ?, ?, ?)",
        ("CLM-BACKFILL-OTHER", "POL-BK1", "VIN-BK1", "open"),
    )
    conn.commit()
    conn.close()
    wrong_party_id = _insert_claim_party(seeded_db, "CLM-BACKFILL-OTHER", "claimant", "Other Claimant")

    repo = PaymentRepository(db_path=seeded_db)
    # First call: no claim_party_id
    data1 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=30.0,
        payee="Someone",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="backfill-wrong-party",
    )
    pid1 = repo.create_payment(data1, actor_id="adj-1", skip_authority_check=True)

    # Retry with a party from a different claim
    data2 = ClaimPaymentCreate(
        claim_id="CLM-TEST01",
        amount=30.0,
        payee="Someone",
        payee_type=PayeeType.CLAIMANT,
        payment_method=PaymentMethod.CHECK,
        external_ref="backfill-wrong-party",
        claim_party_id=int(wrong_party_id),
    )
    with pytest.raises(DomainValidationError):
        repo.create_payment(data2, actor_id="adj-1", skip_authority_check=True)

    # Confirm no changes were made to the existing payment
    payment = repo.get_payment(pid1)
    assert payment is not None
    assert payment["claim_party_id"] is None

