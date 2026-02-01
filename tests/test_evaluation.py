"""Tests for the evaluation script and scenarios.

These tests verify:
- Scenario definitions are valid
- Script components work correctly
- Evaluation engine functions properly

Note: Actual claim processing tests require OPENAI_API_KEY.
"""

import json
import os
from pathlib import Path

import pytest

# Set mock DB path
os.environ.setdefault(
    "MOCK_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"),
)

from evaluate_claim_processing import (
    ALL_SCENARIOS,
    EvaluationReport,
    EvaluationResult,
    EvaluationScenario,
    compare_reports,
    filter_scenarios_by_tags,
    generate_report,
    load_previous_report,
    load_sample_claims_scenarios,
)


class TestScenarioDefinitions:
    """Test that scenario definitions are valid."""

    def test_all_scenarios_have_required_fields(self):
        """Every scenario should have required fields populated."""
        for group_name, scenarios in ALL_SCENARIOS.items():
            for scenario in scenarios:
                assert scenario.name, f"Missing name in {group_name}"
                assert scenario.description, f"Missing description in {scenario.name}"
                assert scenario.expected_type, f"Missing expected_type in {scenario.name}"
                assert scenario.claim_data, f"Missing claim_data in {scenario.name}"
                assert scenario.difficulty in ("easy", "medium", "hard"), \
                    f"Invalid difficulty in {scenario.name}"

    def test_all_scenarios_have_valid_claim_data(self):
        """Claim data should have required fields for ClaimInput."""
        required_fields = [
            "policy_number", "vin", "vehicle_year", "vehicle_make",
            "vehicle_model", "incident_date", "incident_description",
            "damage_description"
        ]
        for group_name, scenarios in ALL_SCENARIOS.items():
            for scenario in scenarios:
                for field in required_fields:
                    assert field in scenario.claim_data, \
                        f"Missing {field} in {scenario.name} claim_data"

    def test_expected_types_are_valid(self):
        """Expected types should be valid claim types."""
        valid_types = {"new", "duplicate", "total_loss", "fraud", "partial_loss"}
        for group_name, scenarios in ALL_SCENARIOS.items():
            for scenario in scenarios:
                assert scenario.expected_type in valid_types, \
                    f"Invalid expected_type '{scenario.expected_type}' in {scenario.name}"

    def test_scenario_names_are_unique(self):
        """All scenario names should be unique across all groups."""
        all_names = []
        for scenarios in ALL_SCENARIOS.values():
            for scenario in scenarios:
                all_names.append(scenario.name)
        
        assert len(all_names) == len(set(all_names)), "Duplicate scenario names found"

    def test_minimum_scenarios_per_type(self):
        """Each scenario group should have at least one scenario."""
        for group_name, scenarios in ALL_SCENARIOS.items():
            assert len(scenarios) >= 1, f"No scenarios in {group_name}"


class TestSampleClaimsIntegration:
    """Test sample claims loading and integration."""

    def test_load_sample_claims_scenarios(self):
        """Sample claims should load correctly."""
        scenarios = load_sample_claims_scenarios()
        assert len(scenarios) > 0, "No sample claim scenarios loaded"

    def test_sample_claims_have_valid_data(self):
        """Loaded sample claims should have valid structure."""
        scenarios = load_sample_claims_scenarios()
        for scenario in scenarios:
            assert scenario.name.startswith("sample_")
            assert scenario.claim_data
            assert "policy_number" in scenario.claim_data
            assert "vin" in scenario.claim_data

    def test_sample_claim_files_exist(self):
        """Sample claim JSON files should exist."""
        sample_dir = Path(__file__).parent / "sample_claims"
        assert sample_dir.exists()
        
        expected_files = [
            "partial_loss_parking.json",
            "duplicate_claim.json",
            "total_loss_claim.json",
            "fraud_claim.json",
            "partial_loss_claim.json",
        ]
        for filename in expected_files:
            assert (sample_dir / filename).exists(), f"Missing {filename}"


class TestReportGeneration:
    """Test report generation functionality."""

    def test_generate_empty_report(self):
        """Report should handle empty results."""
        report = generate_report([])
        assert report.total_scenarios == 0
        assert report.overall_accuracy == 0
        assert report.total_cost_usd == 0

    def test_generate_report_with_results(self):
        """Report should correctly aggregate results."""
        # Create mock scenarios and results
        scenario1 = EvaluationScenario(
            name="test1",
            description="Test scenario 1",
            claim_data={"policy_number": "POL-001", "vin": "VIN001", "vehicle_year": 2020,
                       "vehicle_make": "Test", "vehicle_model": "Model", "incident_date": "2025-01-01",
                       "incident_description": "Test", "damage_description": "Test"},
            expected_type="fraud",
        )
        scenario2 = EvaluationScenario(
            name="test2",
            description="Test scenario 2",
            claim_data={"policy_number": "POL-002", "vin": "VIN002", "vehicle_year": 2020,
                       "vehicle_make": "Test", "vehicle_model": "Model", "incident_date": "2025-01-01",
                       "incident_description": "Test", "damage_description": "Test"},
            expected_type="partial_loss",
        )
        
        results = [
            EvaluationResult(
                scenario=scenario1,
                success=True,
                actual_type="fraud",
                latency_ms=1000,
                total_tokens=100,
                cost_usd=0.01,
            ),
            EvaluationResult(
                scenario=scenario2,
                success=True,
                actual_type="partial_loss",
                latency_ms=1500,
                total_tokens=150,
                cost_usd=0.02,
            ),
        ]
        
        report = generate_report(results)
        
        assert report.total_scenarios == 2
        assert report.successful_runs == 2
        assert report.overall_accuracy == 1.0  # Both correct
        assert report.total_latency_ms == 2500
        assert report.avg_latency_ms == 1250
        assert report.total_tokens == 250
        assert abs(report.total_cost_usd - 0.03) < 1e-9  # Floating-point comparison

    def test_report_calculates_type_accuracy(self):
        """Report should calculate accuracy per expected type."""
        scenario = EvaluationScenario(
            name="test",
            description="Test",
            claim_data={"policy_number": "POL-001", "vin": "VIN001", "vehicle_year": 2020,
                       "vehicle_make": "Test", "vehicle_model": "Model", "incident_date": "2025-01-01",
                       "incident_description": "Test", "damage_description": "Test"},
            expected_type="fraud",
        )
        
        # One correct, one incorrect
        results = [
            EvaluationResult(scenario=scenario, success=True, actual_type="fraud"),
            EvaluationResult(scenario=scenario, success=True, actual_type="new"),
        ]
        
        report = generate_report(results)
        
        assert "fraud" in report.type_accuracy
        assert report.type_accuracy["fraud"]["total"] == 2
        assert report.type_accuracy["fraud"]["correct"] == 1
        assert report.type_accuracy["fraud"]["accuracy"] == 0.5

    def test_report_to_json(self):
        """Report should serialize to valid JSON."""
        report = generate_report([])
        json_str = report.to_json()
        parsed = json.loads(json_str)
        
        assert "timestamp" in parsed
        assert "summary" in parsed
        assert "accuracy_by_type" in parsed
        assert "confusion_matrix" in parsed
        assert "results" in parsed


class TestScenarioToDictSerialization:
    """Test scenario serialization."""

    def test_scenario_to_dict(self):
        """Scenario should serialize to dict correctly."""
        scenario = EvaluationScenario(
            name="test",
            description="Test scenario",
            claim_data={"key": "value"},
            expected_type="fraud",
            tags=["tag1", "tag2"],
            difficulty="hard",
        )
        
        d = scenario.to_dict()
        
        assert d["name"] == "test"
        assert d["description"] == "Test scenario"
        assert d["expected_type"] == "fraud"
        assert d["tags"] == ["tag1", "tag2"]
        assert d["difficulty"] == "hard"

    def test_result_to_dict(self):
        """Result should serialize to dict correctly."""
        scenario = EvaluationScenario(
            name="test",
            description="Test",
            claim_data={"policy_number": "POL-001", "vin": "VIN001", "vehicle_year": 2020,
                       "vehicle_make": "Test", "vehicle_model": "Model", "incident_date": "2025-01-01",
                       "incident_description": "Test", "damage_description": "Test"},
            expected_type="fraud",
        )
        
        result = EvaluationResult(
            scenario=scenario,
            success=True,
            actual_type="fraud",
            claim_id="CLM-123",
            latency_ms=1000,
            total_tokens=100,
            cost_usd=0.01,
        )
        
        d = result.to_dict()
        
        assert d["scenario_name"] == "test"
        assert d["expected_type"] == "fraud"
        assert d["actual_type"] == "fraud"
        assert d["type_match"] is True
        assert d["claim_id"] == "CLM-123"


class TestScenarioCounts:
    """Test that we have adequate scenario coverage."""

    def test_total_scenario_count(self):
        """Should have a reasonable number of total scenarios."""
        total = sum(len(scenarios) for scenarios in ALL_SCENARIOS.values())
        assert total >= 30, f"Expected at least 30 scenarios, got {total}"

    def test_fraud_scenarios_exist(self):
        """Should have fraud detection scenarios."""
        fraud_scenarios = ALL_SCENARIOS.get("fraud", [])
        assert len(fraud_scenarios) >= 3, "Need more fraud scenarios"

    def test_edge_case_scenarios_exist(self):
        """Should have edge case scenarios."""
        edge_scenarios = ALL_SCENARIOS.get("edge_cases", [])
        assert len(edge_scenarios) >= 5, "Need more edge case scenarios"

    def test_stress_test_scenarios_exist(self):
        """Should have stress test scenarios."""
        stress_scenarios = ALL_SCENARIOS.get("stress_test", [])
        assert len(stress_scenarios) >= 3, "Need more stress test scenarios"


class TestLoadPreviousReport:
    """Test load_previous_report."""

    def test_load_previous_report_missing_file(self):
        """Missing file should return None."""
        result = load_previous_report("/nonexistent/path/report.json")
        assert result is None

    def test_load_previous_report_invalid_json(self, tmp_path):
        """Invalid JSON file should return None."""
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {")
        result = load_previous_report(str(bad))
        assert result is None

    def test_load_previous_report_valid(self, tmp_path):
        """Valid report file should return parsed dict."""
        report_data = {"summary": {"overall_accuracy": 0.9}, "timestamp": "2025-01-01T00:00:00"}
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report_data), encoding="utf-8")
        result = load_previous_report(str(path))
        assert result is not None
        assert result["summary"]["overall_accuracy"] == 0.9


class TestCompareReports:
    """Test compare_reports output."""

    def test_compare_reports_does_not_raise(self):
        """compare_reports should run without error."""
        report = generate_report([])
        previous = {
            "summary": {
                "overall_accuracy": 0.8,
                "avg_latency_ms": 1000,
                "total_cost_usd": 0.5,
                "total_tokens": 500,
            },
            "accuracy_by_type": {"fraud": {"accuracy": 0.9}},
        }
        compare_reports(report, previous)


class TestFilterScenariosByTags:
    """Test tag filtering."""

    def test_filter_empty_tags_returns_all(self):
        """No tags means no filtering."""
        scenarios = list(ALL_SCENARIOS["fraud"][:2])
        filtered = filter_scenarios_by_tags(scenarios, [])
        assert len(filtered) == len(scenarios)

    def test_filter_by_tag(self):
        """Filter by tag returns only matching scenarios."""
        scenarios = list(ALL_SCENARIOS["fraud"])
        filtered = filter_scenarios_by_tags(scenarios, ["staged"])
        assert all("staged" in (t.lower() for t in s.tags) for s in filtered)
        assert len(filtered) >= 1

    def test_filter_by_nonexistent_tag_returns_empty(self):
        """Nonexistent tag returns empty list."""
        scenarios = list(ALL_SCENARIOS["fraud"][:1])
        filtered = filter_scenarios_by_tags(scenarios, ["nonexistent_tag_xyz"])
        assert len(filtered) == 0


class TestCLIValidation:
    """Test CLI argument handling."""

    def test_list_action_available(self):
        """--list should be a valid option (module imports and list_scenarios exists)."""
        from evaluate_claim_processing import list_scenarios
        list_scenarios()

    def test_invalid_type_rejected_by_parser(self):
        """Invalid --type value should be rejected by argparse."""
        import argparse
        from evaluate_claim_processing import ALL_SCENARIOS

        parser = argparse.ArgumentParser()
        parser.add_argument("--type", choices=list(ALL_SCENARIOS.keys()))
        # Valid choice should parse
        args = parser.parse_args(["--type", "fraud"])
        assert args.type == "fraud"
        # Invalid choice should raise
        with pytest.raises(SystemExit):
            parser.parse_args(["--type", "invalid_type_xyz"])
