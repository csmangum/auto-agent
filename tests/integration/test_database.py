"""Database and repository integration tests.

These tests verify that the database layer works correctly with the rest of
the system, testing CRUD operations, audit logging, and search functionality.
"""

import os
import tempfile
from datetime import datetime

import pytest

from claim_agent.db.constants import (
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_OPEN,
    STATUS_CLOSED,
    STATUS_FAILED,
)


# ============================================================================
# Database Initialization Tests
# ============================================================================


class TestDatabaseInit:
    """Test database initialization and schema."""
    
    @pytest.mark.integration
    def test_init_creates_required_tables(self, integration_db):
        """Verify all required tables are created."""
        from claim_agent.db.database import get_connection
        
        with get_connection(integration_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
        
        assert "claims" in tables
        assert "claim_audit_log" in tables
        assert "workflow_runs" in tables
    
    @pytest.mark.integration
    def test_claims_table_has_required_columns(self, integration_db):
        """Verify claims table has all required columns."""
        from claim_agent.db.database import get_connection
        
        with get_connection(integration_db) as conn:
            cursor = conn.execute("PRAGMA table_info(claims)")
            columns = {row[1] for row in cursor.fetchall()}
        
        required_columns = {
            "id", "policy_number", "vin", "vehicle_year", "vehicle_make",
            "vehicle_model", "incident_date", "incident_description",
            "damage_description", "estimated_damage", "claim_type",
            "status", "payout_amount", "created_at", "updated_at"
        }
        
        assert required_columns.issubset(columns)
    
    @pytest.mark.integration
    def test_reinit_db_is_idempotent(self, integration_db):
        """Verify re-initializing the database is safe."""
        from claim_agent.db.database import init_db, get_connection
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        # Create a claim
        repo = ClaimRepository(db_path=integration_db)
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        # Re-init the database (should use CREATE TABLE IF NOT EXISTS)
        init_db(integration_db)
        
        # Claim should still exist
        claim = repo.get_claim(claim_id)
        assert claim is not None


# ============================================================================
# Repository CRUD Tests
# ============================================================================


class TestRepositoryCRUD:
    """Test repository CRUD operations."""
    
    @pytest.mark.integration
    def test_create_claim_generates_unique_ids(self, integration_db):
        """Verify that created claims get unique IDs."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        ids = set()
        for i in range(10):
            claim_id = repo.create_claim(ClaimInput(
                policy_number=f"POL-{i:03d}",
                vin=f"VIN{i:010d}",
                vehicle_year=2020 + i,
                vehicle_make="Test",
                vehicle_model="Model",
                incident_date="2025-01-15",
                incident_description=f"Test incident {i}",
                damage_description=f"Test damage {i}",
            ))
            ids.add(claim_id)
        
        assert len(ids) == 10
        assert all(cid.startswith("CLM-") for cid in ids)
    
    @pytest.mark.integration
    def test_get_claim_returns_all_fields(self, integration_db):
        """Verify get_claim returns all claim fields."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_input = ClaimInput(
            policy_number="POL-TEST",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Rear-ended at stoplight.",
            damage_description="Rear bumper damaged.",
            estimated_damage=3500,
        )
        
        claim_id = repo.create_claim(claim_input)
        claim = repo.get_claim(claim_id)
        
        assert claim["id"] == claim_id
        assert claim["policy_number"] == "POL-TEST"
        assert claim["vin"] == "1HGBH41JXMN109186"
        assert claim["vehicle_year"] == 2021
        assert claim["vehicle_make"] == "Honda"
        assert claim["vehicle_model"] == "Accord"
        assert claim["incident_date"] == "2025-01-15"
        assert claim["estimated_damage"] == 3500
        assert claim["status"] == STATUS_PENDING
    
    @pytest.mark.integration
    def test_update_claim_status_changes_status(self, integration_db):
        """Verify status updates work correctly."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        assert repo.get_claim(claim_id)["status"] == STATUS_PENDING
        
        repo.update_claim_status(claim_id, STATUS_PROCESSING)
        assert repo.get_claim(claim_id)["status"] == STATUS_PROCESSING
        
        repo.update_claim_status(claim_id, STATUS_OPEN)
        assert repo.get_claim(claim_id)["status"] == STATUS_OPEN
    
    @pytest.mark.integration
    def test_update_claim_status_with_payout(self, integration_db):
        """Verify status updates can include payout amount."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        repo.update_claim_status(
            claim_id,
            STATUS_CLOSED,
            claim_type="total_loss",
            payout_amount=15000.00,
            details="Settlement completed"
        )
        
        claim = repo.get_claim(claim_id)
        assert claim["status"] == STATUS_CLOSED
        assert claim["claim_type"] == "total_loss"
        assert claim["payout_amount"] == 15000.00


# ============================================================================
# Audit Log Tests
# ============================================================================


class TestAuditLog:
    """Test audit log functionality."""
    
    @pytest.mark.integration
    def test_claim_creation_logs_audit_entry(self, integration_db):
        """Verify claim creation adds an audit entry."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        history = repo.get_claim_history(claim_id)
        
        assert len(history) == 1
        assert history[0]["action"] == "created"
        assert history[0]["new_status"] == STATUS_PENDING
    
    @pytest.mark.integration
    def test_status_changes_log_audit_entries(self, integration_db):
        """Verify status changes add audit entries."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        repo.update_claim_status(claim_id, STATUS_PROCESSING, details="Starting workflow")
        repo.update_claim_status(claim_id, STATUS_OPEN, details="Intake complete")
        repo.update_claim_status(claim_id, STATUS_CLOSED, details="Claim resolved")
        
        history = repo.get_claim_history(claim_id)
        
        assert len(history) == 4  # created + 3 status changes
        
        # Check transitions
        assert history[0]["action"] == "created"
        assert history[1]["action"] == "status_changed"
        assert history[1]["old_status"] == STATUS_PENDING
        assert history[1]["new_status"] == STATUS_PROCESSING
        assert history[2]["old_status"] == STATUS_PROCESSING
        assert history[2]["new_status"] == STATUS_OPEN
        assert history[3]["old_status"] == STATUS_OPEN
        assert history[3]["new_status"] == STATUS_CLOSED
    
    @pytest.mark.integration
    def test_audit_entries_have_timestamps(self, integration_db):
        """Verify audit entries include timestamps."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        history = repo.get_claim_history(claim_id)
        
        assert history[0]["created_at"] is not None


# ============================================================================
# Search Tests
# ============================================================================


class TestClaimSearch:
    """Test claim search functionality."""
    
    @pytest.mark.integration
    def test_search_by_vin(self, seeded_db):
        """Test searching claims by VIN."""
        from claim_agent.db.repository import ClaimRepository
        
        repo = ClaimRepository(db_path=seeded_db)
        
        results = repo.search_claims(vin="1HGBH41JXMN109186")
        
        assert len(results) == 1
        assert results[0]["vin"] == "1HGBH41JXMN109186"
    
    @pytest.mark.integration
    def test_search_by_incident_date(self, seeded_db):
        """Test searching claims by incident date."""
        from claim_agent.db.repository import ClaimRepository
        
        repo = ClaimRepository(db_path=seeded_db)
        
        results = repo.search_claims(incident_date="2025-01-15")
        
        assert len(results) >= 1
        assert all(r["incident_date"] == "2025-01-15" for r in results)
    
    @pytest.mark.integration
    def test_search_by_vin_and_date(self, seeded_db):
        """Test searching claims by VIN and date."""
        from claim_agent.db.repository import ClaimRepository
        
        repo = ClaimRepository(db_path=seeded_db)
        
        results = repo.search_claims(
            vin="1HGBH41JXMN109186",
            incident_date="2025-01-15"
        )
        
        assert len(results) == 1
        assert results[0]["vin"] == "1HGBH41JXMN109186"
        assert results[0]["incident_date"] == "2025-01-15"
    
    @pytest.mark.integration
    def test_search_with_no_matches(self, seeded_db):
        """Test search with no matching results."""
        from claim_agent.db.repository import ClaimRepository
        
        repo = ClaimRepository(db_path=seeded_db)
        
        results = repo.search_claims(vin="NONEXISTENT_VIN")
        
        assert results == []
    
    @pytest.mark.integration
    def test_search_with_empty_criteria_returns_empty(self, seeded_db):
        """Test search with no criteria returns empty list."""
        from claim_agent.db.repository import ClaimRepository
        
        repo = ClaimRepository(db_path=seeded_db)
        
        results = repo.search_claims()
        
        assert results == []


# ============================================================================
# Workflow Runs Table Tests
# ============================================================================


class TestWorkflowRuns:
    """Test workflow runs persistence."""
    
    @pytest.mark.integration
    def test_save_workflow_result(self, integration_db):
        """Test saving workflow results."""
        from claim_agent.db.database import get_connection
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        repo.save_workflow_result(
            claim_id=claim_id,
            claim_type="new",
            router_output="new\nStandard claim submission.",
            workflow_output="Claim processed successfully. Assigned to adjuster.",
        )
        
        with get_connection(integration_db) as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE claim_id = ?",
                (claim_id,)
            ).fetchone()
        
        assert row is not None
        assert row["claim_type"] == "new"
        assert "new" in row["router_output"]
        assert "processed" in row["workflow_output"].lower()
    
    @pytest.mark.integration
    def test_multiple_workflow_runs_for_same_claim(self, integration_db):
        """Test that multiple workflow runs can be saved for reprocessed claims."""
        from claim_agent.db.database import get_connection
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        repo = ClaimRepository(db_path=integration_db)
        
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Test",
            vehicle_model="Model",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        ))
        
        # First workflow run
        repo.save_workflow_result(claim_id, "new", "new", "First run")
        
        # Second workflow run (reprocessed)
        repo.save_workflow_result(claim_id, "partial_loss", "partial_loss", "Second run")
        
        with get_connection(integration_db) as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs WHERE claim_id = ? ORDER BY created_at",
                (claim_id,)
            ).fetchall()
        
        assert len(rows) == 2
        assert rows[0]["claim_type"] == "new"
        assert rows[1]["claim_type"] == "partial_loss"


# ============================================================================
# Concurrent Access Tests
# ============================================================================


class TestConcurrentAccess:
    """Test database behavior under concurrent access."""
    
    @pytest.mark.integration
    def test_concurrent_claim_creation(self, integration_db):
        """Test that concurrent claim creation works correctly."""
        import threading
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        created_ids = []
        errors = []
        
        def create_claim(index):
            try:
                repo = ClaimRepository(db_path=integration_db)
                claim_id = repo.create_claim(ClaimInput(
                    policy_number=f"POL-{index:03d}",
                    vin=f"VIN{index:010d}",
                    vehicle_year=2021,
                    vehicle_make="Test",
                    vehicle_model="Model",
                    incident_date="2025-01-15",
                    incident_description=f"Test {index}",
                    damage_description=f"Damage {index}",
                ))
                created_ids.append(claim_id)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=create_claim, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors during concurrent creation: {errors}"
        assert len(set(created_ids)) == 5  # All unique IDs
