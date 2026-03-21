"""Unit tests for salvage tools."""

import json
import tempfile

import pytest

from claim_agent.tools.salvage_logic import (
    get_salvage_value_impl,
    initiate_title_transfer_impl,
    record_dmv_salvage_report_impl,
    record_salvage_disposition_impl,
    submit_nmvtis_report_impl,
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
    @pytest.fixture
    def temp_claim_db(self, monkeypatch):
        import os
        import sqlite3

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("CLM-123", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord", "processing"),
            )
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_record_pending(self, temp_claim_db):
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
        assert "nmvtis_reference" not in data
        from claim_agent.db.repository import ClaimRepository

        meta = ClaimRepository().get_claim_total_loss_metadata("CLM-123")
        assert meta["salvage_disposition_status"] == "pending"

    def test_record_auction_complete(self, temp_claim_db):
        from claim_agent.adapters.registry import reset_adapters

        reset_adapters()
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
        assert data["nmvtis_reference"].startswith("NMVTIS-MOCK-")
        assert data["nmvtis_status"] == "accepted"

    def test_invalid_status_falls_back_to_pending(self, temp_claim_db):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="auction",
            status="invalid_status",
        )
        data = json.loads(result)
        assert data["status"] == "pending"

    def test_invalid_disposition_type_falls_back_to_auction(self, temp_claim_db):
        result = record_salvage_disposition_impl(
            claim_id="CLM-123",
            disposition_type="unknown",
            status="pending",
        )
        data = json.loads(result)
        assert data["disposition_type"] == "auction"

    def test_missing_claim_returns_error(self, monkeypatch):
        import os

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        try:
            result = record_salvage_disposition_impl(
                claim_id="CLM-MISSING",
                disposition_type="auction",
                status="pending",
            )
            data = json.loads(result)
            assert "error" in data
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class TestRecordDmvSalvageReport:
    @pytest.fixture
    def temp_claim_db(self, monkeypatch):
        """Create temp DB with a claim for DMV report testing."""
        import os
        import sqlite3

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("CLM-DMV-001", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord", "processing"),
            )
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_record_dmv_report(self, temp_claim_db):
        from claim_agent.adapters.registry import reset_adapters
        from claim_agent.db.repository import ClaimRepository

        reset_adapters()
        # Uses CLAIMS_DB_PATH from monkeypatch in temp_claim_db fixture
        result = record_dmv_salvage_report_impl(
            claim_id="CLM-DMV-001",
            dmv_reference="DMV-12345678-20260316",
            salvage_title_status="dmv_reported",
            ctx=None,
        )
        data = json.loads(result)
        assert data["claim_id"] == "CLM-DMV-001"
        assert data["dmv_reference"] == "DMV-12345678-20260316"
        assert data["salvage_title_status"] == "dmv_reported"
        assert "reported_at" in data

        repo = ClaimRepository()
        meta = repo.get_claim_total_loss_metadata("CLM-DMV-001")
        assert meta is not None
        assert meta["dmv_reference"] == "DMV-12345678-20260316"
        assert meta["salvage_title_status"] == "dmv_reported"
        assert meta["nmvtis_reference"].startswith("NMVTIS-MOCK-")
        assert meta["nmvtis_status"] == "accepted"

    def test_record_dmv_second_call_skips_nmvtis_when_accepted(self, temp_claim_db):
        from claim_agent.adapters.registry import reset_adapters
        from claim_agent.db.repository import ClaimRepository

        reset_adapters()
        record_dmv_salvage_report_impl(
            claim_id="CLM-DMV-001",
            dmv_reference="DMV-FIRST",
            ctx=None,
        )
        result2 = record_dmv_salvage_report_impl(
            claim_id="CLM-DMV-001",
            dmv_reference="DMV-SECOND",
            ctx=None,
        )
        data = json.loads(result2)
        assert data.get("nmvtis_skipped") is True
        meta = ClaimRepository().get_claim_total_loss_metadata("CLM-DMV-001")
        assert meta["dmv_reference"] == "DMV-SECOND"

    def test_record_dmv_retries_transient_nmvtis_failures(self, monkeypatch):
        import os
        import sqlite3

        from claim_agent.adapters.registry import reset_adapters
        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        cid = "CLM-NMVTIS-FAILTWICE-001"
        try:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cid, "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord", "processing"),
                )
            reset_adapters()
            result = record_dmv_salvage_report_impl(
                claim_id=cid,
                dmv_reference="DMV-FAIL",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "accepted"
            assert data["nmvtis_submission_attempts"] == 3
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_record_dmv_stub_nmvtis_sets_not_configured(self, temp_claim_db, monkeypatch):
        from claim_agent.adapters.registry import reset_adapters
        from claim_agent.config import reload_settings

        reset_adapters()
        monkeypatch.setenv("NMVTIS_ADAPTER", "stub")
        reload_settings()
        try:
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-DMV-001",
                dmv_reference="DMV-STUB",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "not_configured"
            assert "nmvtis_coordination_error" in data
        finally:
            monkeypatch.delenv("NMVTIS_ADAPTER", raising=False)
            reload_settings()
            reset_adapters()

    def test_record_dmv_nmvtis_skipped_without_vin(self, monkeypatch):
        import os
        import sqlite3

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        try:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("CLM-NOVIN", "POL-001", "", 2021, "Honda", "Accord", "processing"),
                )
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-NOVIN",
                dmv_reference="DMV-NOVIN",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "skipped"
            from claim_agent.db.repository import ClaimRepository

            meta = ClaimRepository().get_claim_total_loss_metadata("CLM-NOVIN")
            assert meta["nmvtis_skip_reason"] == "missing_vin"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _make_temp_db_with_claim(self, monkeypatch, claim_row: tuple):
        import sqlite3

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                claim_row,
            )
        return path

    def test_record_dmv_nmvtis_skipped_invalid_vin(self, monkeypatch):
        """NMVTIS is skipped (not fabricated) when VIN is present but not a valid 17-char VIN."""
        import os

        from claim_agent.db.repository import ClaimRepository

        path = self._make_temp_db_with_claim(
            monkeypatch,
            ("CLM-BADVIN", "POL-001", "TOOSHORT", 2021, "Honda", "Accord", "processing"),
        )
        try:
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-BADVIN",
                dmv_reference="DMV-BADVIN",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "skipped"
            assert data["nmvtis_skip_reason"] == "invalid_vin"
            meta = ClaimRepository().get_claim_total_loss_metadata("CLM-BADVIN")
            assert meta["nmvtis_skip_reason"] == "invalid_vin"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_record_dmv_nmvtis_skipped_missing_year(self, monkeypatch):
        """NMVTIS is skipped when vehicle_year is absent/zero instead of using a fabricated year."""
        import os

        from claim_agent.db.repository import ClaimRepository

        path = self._make_temp_db_with_claim(
            monkeypatch,
            ("CLM-NOYEAR", "POL-001", "1HGBH41JXMN109186", 0, "Honda", "Accord", "processing"),
        )
        try:
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-NOYEAR",
                dmv_reference="DMV-NOYEAR",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "skipped"
            assert data["nmvtis_skip_reason"] == "missing_vehicle_year"
            meta = ClaimRepository().get_claim_total_loss_metadata("CLM-NOYEAR")
            assert meta["nmvtis_skip_reason"] == "missing_vehicle_year"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_record_dmv_nmvtis_skipped_missing_make(self, monkeypatch):
        """NMVTIS is skipped when vehicle_make is absent instead of using 'Unknown'."""
        import os

        from claim_agent.db.repository import ClaimRepository

        path = self._make_temp_db_with_claim(
            monkeypatch,
            ("CLM-NOMAKE", "POL-001", "1HGBH41JXMN109186", 2021, "", "Accord", "processing"),
        )
        try:
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-NOMAKE",
                dmv_reference="DMV-NOMAKE",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "skipped"
            assert data["nmvtis_skip_reason"] == "missing_vehicle_make"
            meta = ClaimRepository().get_claim_total_loss_metadata("CLM-NOMAKE")
            assert meta["nmvtis_skip_reason"] == "missing_vehicle_make"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_record_dmv_nmvtis_skipped_missing_model(self, monkeypatch):
        """NMVTIS is skipped when vehicle_model is absent instead of using 'Unknown'."""
        import os

        from claim_agent.db.repository import ClaimRepository

        path = self._make_temp_db_with_claim(
            monkeypatch,
            ("CLM-NOMODEL", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "", "processing"),
        )
        try:
            result = record_dmv_salvage_report_impl(
                claim_id="CLM-NOMODEL",
                dmv_reference="DMV-NOMODEL",
                ctx=None,
            )
            data = json.loads(result)
            assert data["nmvtis_status"] == "skipped"
            assert data["nmvtis_skip_reason"] == "missing_vehicle_model"
            meta = ClaimRepository().get_claim_total_loss_metadata("CLM-NOMODEL")
            assert meta["nmvtis_skip_reason"] == "missing_vehicle_model"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_record_dmv_report_nonexistent_claim_returns_error(self, temp_claim_db):
        """When claim does not exist, return JSON with error and claim_id."""
        result = record_dmv_salvage_report_impl(
            claim_id="CLM-NONEXISTENT",
            dmv_reference="DMV-999",
            ctx=None,
        )
        data = json.loads(result)
        assert "error" in data
        assert data["claim_id"] == "CLM-NONEXISTENT"


class TestSubmitNmvtisReport:
    @pytest.fixture
    def temp_claim_db(self, monkeypatch):
        import os
        import sqlite3

        from claim_agent.config import reload_settings
        from claim_agent.db.database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        monkeypatch.setenv("CLAIMS_DB_PATH", path)
        reload_settings()
        init_db(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("CLM-NM-1", "POL-001", "1HGBH41JXMN109186", 2021, "Honda", "Accord", "processing"),
            )
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_manual_submit_after_dmv(self, temp_claim_db):
        from claim_agent.adapters.registry import reset_adapters

        reset_adapters()
        record_dmv_salvage_report_impl(
            claim_id="CLM-NM-1",
            dmv_reference="DMV-M",
            ctx=None,
        )
        result = submit_nmvtis_report_impl("CLM-NM-1", force_resubmit=False, ctx=None)
        data = json.loads(result)
        assert data.get("nmvtis_skipped") is True

    def test_force_resubmit_calls_adapter_again(self, temp_claim_db):
        from claim_agent.adapters.registry import reset_adapters

        reset_adapters()
        record_dmv_salvage_report_impl(
            claim_id="CLM-NM-1",
            dmv_reference="DMV-M2",
            ctx=None,
        )
        result = submit_nmvtis_report_impl("CLM-NM-1", force_resubmit=True, ctx=None)
        data = json.loads(result)
        assert data["nmvtis_status"] == "accepted"
        assert "nmvtis_reference" in data
