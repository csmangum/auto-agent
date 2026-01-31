"""Unit tests for CLI (main.py) functions and edge cases."""

import json
import os
import tempfile
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from claim_agent.main import (
    _usage,
    _claim_data_from_row,
    cmd_process,
    cmd_status,
    cmd_history,
    cmd_reprocess,
    main,
)
from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


class TestUsage:
    """Tests for _usage function."""

    def test_usage_returns_string(self):
        """Test _usage returns a non-empty string."""
        result = _usage()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "process" in result
        assert "status" in result
        assert "history" in result
        assert "reprocess" in result


class TestClaimDataFromRow:
    """Tests for _claim_data_from_row function."""

    def test_claim_data_from_row_complete(self):
        """Test with complete row data."""
        row = {
            "policy_number": "POL-001",
            "vin": "VIN123",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Test incident",
            "damage_description": "Test damage",
            "estimated_damage": 5000.0,
        }
        result = _claim_data_from_row(row)
        assert result["policy_number"] == "POL-001"
        assert result["vin"] == "VIN123"
        assert result["vehicle_year"] == 2021
        assert result["estimated_damage"] == 5000.0

    def test_claim_data_from_row_with_none_values(self):
        """Test with None values uses defaults."""
        row = {
            "policy_number": None,
            "vin": None,
            "vehicle_year": None,
            "vehicle_make": None,
            "vehicle_model": None,
            "incident_date": None,
            "incident_description": None,
            "damage_description": None,
            "estimated_damage": None,
        }
        result = _claim_data_from_row(row)
        assert result["policy_number"] == ""
        assert result["vin"] == ""
        assert result["vehicle_year"] == 0
        assert result["estimated_damage"] is None

    def test_claim_data_from_row_partial(self):
        """Test with partially missing data."""
        row = {
            "policy_number": "POL-001",
            "vin": "VIN123",
        }
        result = _claim_data_from_row(row)
        assert result["policy_number"] == "POL-001"
        assert result["vin"] == "VIN123"
        # Missing keys should use defaults
        assert result["vehicle_year"] == 0


class TestCmdStatus:
    """Tests for cmd_status function."""

    def test_cmd_status_found(self):
        """Test cmd_status with existing claim."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            repo = ClaimRepository(db_path=db_path)
            claim_id = repo.create_claim(
                ClaimInput(
                    policy_number="POL-001",
                    vin="VIN123",
                    vehicle_year=2021,
                    vehicle_make="Honda",
                    vehicle_model="Accord",
                    incident_date="2025-01-15",
                    incident_description="Test.",
                    damage_description="Test damage.",
                )
            )
            
            # Capture stdout
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                cmd_status(claim_id)
                output = mock_stdout.getvalue()
            
            data = json.loads(output)
            assert data["id"] == claim_id
            assert data["policy_number"] == "POL-001"
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)

    def test_cmd_status_not_found(self):
        """Test cmd_status with non-existent claim."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            
            with pytest.raises(SystemExit) as exc_info:
                cmd_status("CLM-NONEXISTENT")
            
            assert exc_info.value.code == 1
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)


class TestCmdHistory:
    """Tests for cmd_history function."""

    def test_cmd_history_found(self):
        """Test cmd_history with existing claim."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            repo = ClaimRepository(db_path=db_path)
            claim_id = repo.create_claim(
                ClaimInput(
                    policy_number="POL-001",
                    vin="VIN123",
                    vehicle_year=2021,
                    vehicle_make="Honda",
                    vehicle_model="Accord",
                    incident_date="2025-01-15",
                    incident_description="Test.",
                    damage_description="Test damage.",
                )
            )
            repo.update_claim_status(claim_id, "processing")
            
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                cmd_history(claim_id)
                output = mock_stdout.getvalue()
            
            history = json.loads(output)
            assert len(history) >= 2
            assert history[0]["action"] == "created"
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)

    def test_cmd_history_not_found(self):
        """Test cmd_history with non-existent claim."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            
            with pytest.raises(SystemExit) as exc_info:
                cmd_history("CLM-NONEXISTENT")
            
            assert exc_info.value.code == 1
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)


class TestCmdProcess:
    """Tests for cmd_process function."""

    def test_cmd_process_file_not_found(self):
        """Test cmd_process with non-existent file."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_process(Path("/nonexistent/claim.json"))
        
        assert exc_info.value.code == 1

    def test_cmd_process_invalid_json(self):
        """Test cmd_process with invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {")
            path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                cmd_process(Path(path))
            
            assert exc_info.value.code == 1
        finally:
            os.unlink(path)

    def test_cmd_process_invalid_claim_data(self):
        """Test cmd_process with invalid claim data (missing fields)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"policy_number": "POL-001"}, f)  # Missing required fields
            path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                cmd_process(Path(path))
            
            assert exc_info.value.code == 1
        finally:
            os.unlink(path)


class TestCmdReprocess:
    """Tests for cmd_reprocess function."""

    def test_cmd_reprocess_not_found(self):
        """Test cmd_reprocess with non-existent claim."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            
            with pytest.raises(SystemExit) as exc_info:
                cmd_reprocess("CLM-NONEXISTENT")
            
            assert exc_info.value.code == 1
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)


class TestMain:
    """Tests for main function (CLI entry point)."""

    def test_main_no_args(self):
        """Test main with no arguments shows usage."""
        with patch("sys.argv", ["claim-agent"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_status_no_claim_id(self):
        """Test main status without claim_id."""
        with patch("sys.argv", ["claim-agent", "status"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_history_no_claim_id(self):
        """Test main history without claim_id."""
        with patch("sys.argv", ["claim-agent", "history"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_reprocess_no_claim_id(self):
        """Test main reprocess without claim_id."""
        with patch("sys.argv", ["claim-agent", "reprocess"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_process_no_file(self):
        """Test main process without file path."""
        with patch("sys.argv", ["claim-agent", "process"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_unknown_command(self):
        """Test main with unknown command."""
        with patch("sys.argv", ["claim-agent", "unknown_command"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1

    def test_main_status_with_claim_id(self):
        """Test main status command with claim_id."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            repo = ClaimRepository(db_path=db_path)
            claim_id = repo.create_claim(
                ClaimInput(
                    policy_number="POL-001",
                    vin="VIN123",
                    vehicle_year=2021,
                    vehicle_make="Honda",
                    vehicle_model="Accord",
                    incident_date="2025-01-15",
                    incident_description="Test.",
                    damage_description="Test damage.",
                )
            )
            
            with patch("sys.argv", ["claim-agent", "status", claim_id]):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()
                    output = mock_stdout.getvalue()
            
            data = json.loads(output)
            assert data["id"] == claim_id
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)

    def test_main_history_with_claim_id(self):
        """Test main history command with claim_id."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            repo = ClaimRepository(db_path=db_path)
            claim_id = repo.create_claim(
                ClaimInput(
                    policy_number="POL-001",
                    vin="VIN123",
                    vehicle_year=2021,
                    vehicle_make="Honda",
                    vehicle_model="Accord",
                    incident_date="2025-01-15",
                    incident_description="Test.",
                    damage_description="Test damage.",
                )
            )
            
            with patch("sys.argv", ["claim-agent", "history", claim_id]):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()
                    output = mock_stdout.getvalue()
            
            history = json.loads(output)
            assert len(history) >= 1
        finally:
            os.unlink(db_path)
            os.environ.pop("CLAIMS_DB_PATH", None)

    def test_main_legacy_file_path(self):
        """Test main with legacy file path argument."""
        # Create a valid claim file
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        claim_data = {
            "policy_number": "POL-001",
            "vin": "VIN123",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Test incident.",
            "damage_description": "Test damage.",
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(claim_data, f)
            claim_path = f.name
        
        try:
            init_db(db_path)
            os.environ["CLAIMS_DB_PATH"] = db_path
            
            with patch("sys.argv", ["claim-agent", claim_path]):
                with patch("claim_agent.crews.main_crew.run_claim_workflow") as mock_workflow:
                    mock_workflow.return_value = {"claim_id": "CLM-TEST", "status": "open"}
                    with patch("sys.stdout", new_callable=StringIO):
                        main()
                    
                    mock_workflow.assert_called_once()
        finally:
            os.unlink(db_path)
            os.unlink(claim_path)
            os.environ.pop("CLAIMS_DB_PATH", None)
