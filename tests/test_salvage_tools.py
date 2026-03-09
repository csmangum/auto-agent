"""Unit tests for salvage tools."""

import json

from claim_agent.tools.salvage_logic import (
    get_salvage_value_impl,
    initiate_title_transfer_impl,
    record_salvage_disposition_impl,
)


class TestGetSalvageValue:
    def test_high_damage_flood(self):
        result = get_salvage_value_impl(
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            make="Honda",
            model="Accord",
            damage_description="Vehicle flooded and submerged.",
            vehicle_value=20000.0,
        )
        data = json.loads(result)
        assert "salvage_value" in data
        assert data["vehicle_value_used"] == 20000.0
        assert data["disposition_recommendation"] in ("auction", "owner_retention", "scrap")
        assert data["salvage_value"] == 20000.0 * 0.15

    def test_medium_damage_collision(self):
        result = get_salvage_value_impl(
            vin="1HGBH41JXMN109186",
            vehicle_year=2020,
            make="Toyota",
            model="Camry",
            damage_description="Totaled in collision. Vehicle destroyed.",
            vehicle_value=15000.0,
        )
        data = json.loads(result)
        assert data["salvage_value"] == 15000.0 * 0.20
        assert data["disposition_recommendation"] in ("auction", "owner_retention", "scrap")

    def test_uses_estimated_value_when_none_provided(self):
        result = get_salvage_value_impl(
            vin="",
            vehicle_year=2020,
            make="Ford",
            model="F-150",
            damage_description="Total loss.",
        )
        data = json.loads(result)
        assert "salvage_value" in data
        assert data["vehicle_value_used"] >= 5000
        assert data["source"] == "estimated"


class TestInitiateTitleTransfer:
    def test_auction_disposition(self):
        result = initiate_title_transfer_impl(
            claim_id="CLM-123",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            make="Honda",
            model="Accord",
            disposition_type="auction",
        )
        data = json.loads(result)
        assert data["transfer_id"].startswith("SALV-")
        assert data["claim_id"] == "CLM-123"
        assert data["disposition_type"] == "auction"
        assert "dmv_reference" in data
        assert data["status"] == "initiated"

    def test_owner_retention(self):
        result = initiate_title_transfer_impl(
            claim_id="CLM-456",
            vin="5YJSA1E26HF123456",
            vehicle_year=2017,
            make="Tesla",
            model="Model S",
            disposition_type="owner_retention",
        )
        data = json.loads(result)
        assert data["disposition_type"] == "owner_retention"
        assert "initiated_at" in data

    def test_invalid_disposition_type_falls_back_to_auction(self):
        result = initiate_title_transfer_impl(
            claim_id="CLM-789",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            make="Honda",
            model="Accord",
            disposition_type="invalid",
        )
        data = json.loads(result)
        assert data["disposition_type"] == "auction"


class TestRecordSalvageDisposition:
    def test_record_pending(self):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="auction",
            status="pending",
        )
        data = json.loads(result)
        assert data["claim_id"] == "CLM-123"
        assert data["disposition_type"] == "auction"
        assert data["status"] == "pending"
        assert "recorded_at" in data

    def test_record_auction_complete(self):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="auction",
            salvage_amount=3500.0,
            status="auction_complete",
            notes="Sold at Copart.",
        )
        data = json.loads(result)
        assert data["salvage_amount"] == 3500.0
        assert data["status"] == "auction_complete"
        assert data["notes"] == "Sold at Copart."

    def test_invalid_status_falls_back_to_pending(self):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="auction",
            status="invalid_status",
        )
        data = json.loads(result)
        assert data["status"] == "pending"

    def test_invalid_disposition_type_falls_back_to_auction(self):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="unknown",
            status="pending",
        )
        data = json.loads(result)
        assert data["disposition_type"] == "auction"
