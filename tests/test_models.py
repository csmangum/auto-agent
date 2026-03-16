"""Tests for Pydantic claim models."""

from datetime import date

import pytest
from pydantic import ValidationError

from claim_agent.models.claim import (
    AttachmentType,
    ClaimInput,
    ClaimOutput,
    ClaimType,
    EscalationOutput,
)


class TestClaimType:
    """Test ClaimType enum."""

    def test_all_values(self):
        assert ClaimType.NEW.value == "new"
        assert ClaimType.DUPLICATE.value == "duplicate"
        assert ClaimType.TOTAL_LOSS.value == "total_loss"
        assert ClaimType.FRAUD.value == "fraud"
        assert ClaimType.PARTIAL_LOSS.value == "partial_loss"

    def test_from_string(self):
        assert ClaimType("new") == ClaimType.NEW
        assert ClaimType("total_loss") == ClaimType.TOTAL_LOSS


class TestClaimInput:
    """Test ClaimInput validation."""

    def test_valid_minimal(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended at stoplight.",
            "damage_description": "Rear bumper damage.",
        }
        claim = ClaimInput(**data)
        assert claim.policy_number == "POL-001"
        assert claim.vin == "1HGBH41JXMN109186"
        assert claim.vehicle_year == 2021
        assert claim.incident_date == date(2025, 1, 15)
        assert claim.estimated_damage is None

    def test_valid_with_estimated_damage(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
            "estimated_damage": 3500.0,
        }
        claim = ClaimInput(**data)
        assert claim.estimated_damage == 3500.0

    def test_missing_required_field_raises(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            # Missing damage_description
        }
        with pytest.raises(ValidationError):
            ClaimInput(**data)

    def test_invalid_incident_date_raises(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "not-a-date",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
        }
        with pytest.raises(ValidationError):
            ClaimInput(**data)

    def test_invalid_vehicle_year_raises(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": "not-an-int",
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
        }
        with pytest.raises(ValidationError):
            ClaimInput(**data)

    def test_model_dump_json(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
        }
        claim = ClaimInput(**data)
        dumped = claim.model_dump(mode="json")
        assert dumped["incident_date"] == "2025-01-15"

    def test_valid_with_loss_state(self):
        """ClaimInput accepts optional loss_state for state-specific compliance."""
        data = {
            "policy_number": "POL-001",
            "vin": "VIN123",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Test",
            "damage_description": "Test",
            "loss_state": "California",
        }
        claim = ClaimInput(**data)
        assert claim.loss_state == "California"

    def test_valid_with_attachments(self):
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
            "attachments": [
                {"url": "https://example.com/photo.jpg", "type": "photo", "description": "Damage photo"},
                {"url": "https://example.com/estimate.pdf", "type": "estimate"},
            ],
        }
        claim = ClaimInput(**data)
        assert len(claim.attachments) == 2
        assert claim.attachments[0].type == AttachmentType.PHOTO
        assert claim.attachments[0].description == "Damage photo"
        assert claim.attachments[1].type == AttachmentType.ESTIMATE
        assert claim.attachments[1].description is None

    def test_valid_with_parties(self):
        """ClaimInput accepts optional parties for claim identity management."""
        data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended.",
            "damage_description": "Bumper damage.",
            "parties": [
                {"party_type": "claimant", "name": "Jane Doe", "email": "jane@example.com"},
                {"party_type": "policyholder", "name": "John Doe", "phone": "555-123-4567"},
            ],
        }
        claim = ClaimInput(**data)
        assert claim.parties is not None
        assert len(claim.parties) == 2
        assert claim.parties[0].party_type == "claimant"
        assert claim.parties[0].email == "jane@example.com"
        assert claim.parties[1].party_type == "policyholder"
        assert claim.parties[1].phone == "555-123-4567"


class TestClaimOutput:
    """Test ClaimOutput validation."""

    def test_valid_minimal(self):
        data = {
            "claim_type": "new",
            "status": "open",
        }
        out = ClaimOutput(**data)
        assert out.claim_id is None
        assert out.claim_type == ClaimType.NEW
        assert out.status == "open"
        assert out.actions_taken == []
        assert out.payout_amount is None
        assert out.message is None

    def test_valid_full(self):
        data = {
            "claim_id": "CLM-123",
            "claim_type": "total_loss",
            "status": "closed",
            "actions_taken": ["Processed", "Evaluated"],
            "payout_amount": 15000.0,
            "message": "Total loss confirmed.",
        }
        out = ClaimOutput(**data)
        assert out.claim_id == "CLM-123"
        assert out.claim_type == ClaimType.TOTAL_LOSS
        assert out.payout_amount == 15000.0

    def test_invalid_claim_type_raises(self):
        data = {
            "claim_type": "invalid_type",
            "status": "open",
        }
        with pytest.raises(ValidationError):
            ClaimOutput(**data)


class TestEscalationOutput:
    """Test EscalationOutput validation."""

    def test_valid_minimal(self):
        data = {
            "claim_id": "CLM-123",
            "needs_review": True,
            "priority": "high",
        }
        out = EscalationOutput(**data)
        assert out.claim_id == "CLM-123"
        assert out.needs_review is True
        assert out.priority == "high"
        assert out.escalation_reasons == []
        assert out.recommended_action == ""
        assert out.fraud_indicators == []

    def test_valid_full(self):
        data = {
            "claim_id": "CLM-123",
            "needs_review": True,
            "escalation_reasons": ["high_value", "low_confidence"],
            "priority": "critical",
            "recommended_action": "Review manually.",
            "fraud_indicators": ["staged"],
        }
        out = EscalationOutput(**data)
        assert out.escalation_reasons == ["high_value", "low_confidence"]
        assert out.priority == "critical"
        assert out.recommended_action == "Review manually."
        assert out.fraud_indicators == ["staged"]

    def test_invalid_priority_raises(self):
        data = {
            "claim_id": "CLM-123",
            "needs_review": True,
            "priority": "invalid",
        }
        with pytest.raises(ValidationError):
            EscalationOutput(**data)

    def test_all_priority_values(self):
        for p in ("low", "medium", "high", "critical"):
            out = EscalationOutput(claim_id="CLM-1", needs_review=True, priority=p)
            assert out.priority == p


class TestUserType:
    """Test UserType enum and UserContext model."""

    def test_all_user_types(self):
        from claim_agent.models.user import UserType

        assert UserType.CLAIMANT.value == "claimant"
        assert UserType.POLICYHOLDER.value == "policyholder"
        assert UserType.ADJUSTER.value == "adjuster"
        assert UserType.REPAIR_SHOP.value == "repair_shop"
        assert UserType.SIU.value == "siu"
        assert UserType.OTHER.value == "other"

    def test_user_context_to_actor_id(self):
        from claim_agent.models.user import UserContext, UserType

        ctx = UserContext(user_type=UserType.CLAIMANT, identifier="claim-123")
        assert ctx.to_actor_id() == "claimant:claim-123"

    def test_user_context_with_contact(self):
        from claim_agent.models.user import UserContext, UserType

        ctx = UserContext(
            user_type=UserType.REPAIR_SHOP,
            identifier="SHOP-001",
            email="shop@example.com",
        )
        assert ctx.user_type == UserType.REPAIR_SHOP
        assert ctx.identifier == "SHOP-001"
        assert ctx.email == "shop@example.com"
