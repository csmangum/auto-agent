"""Tests for payment repository and payment workflow."""

import tempfile
from pathlib import Path

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError, PaymentAuthorityError
from claim_agent.models.payment import (
    ClaimPaymentCreate,
    PaymentMethod,
    PaymentStatus,
    PayeeType,
)


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
