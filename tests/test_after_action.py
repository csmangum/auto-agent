"""Unit tests for the after-action crew: close_claim tool and _stage_after_action."""

import json
import os
from unittest.mock import MagicMock, patch

from crewai import LLM

import claim_agent.crews.main_crew  # noqa: F401  (break circular import for stage patches)

# Ensure mock_db path is set
os.environ.setdefault(
    "MOCK_DB_PATH",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "mock_db.json"),
)


def _mock_llm():
    """Minimal LLM for structural validation (no API calls)."""
    return LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")


class TestCloseClaimTool:
    """Tests for the close_claim CrewAI tool."""

    def test_close_claim_success(self, seeded_temp_db):
        from claim_agent.tools.status_tools import close_claim

        result = close_claim.run(claim_id="CLM-TEST001", reason="All actions complete")
        data = json.loads(result)
        assert data["success"] is True
        assert "closed" in data["message"]

    def test_close_claim_updates_status_in_db(self, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.tools.status_tools import close_claim

        close_claim.run(claim_id="CLM-TEST001", reason="Settlement complete")
        repo = ClaimRepository()
        claim = repo.get_claim("CLM-TEST001")
        assert claim["status"] == "closed"

    def test_close_claim_not_found(self, temp_db):
        from claim_agent.tools.status_tools import close_claim

        result = close_claim.run(claim_id="CLM-NONEXISTENT", reason="test")
        data = json.loads(result)
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_close_claim_missing_claim_id(self):
        from claim_agent.tools.status_tools import close_claim

        result = close_claim.run(claim_id="", reason="test")
        data = json.loads(result)
        assert data["success"] is False
        assert "claim_id" in data["message"]

    def test_close_claim_missing_reason(self):
        from claim_agent.tools.status_tools import close_claim

        result = close_claim.run(claim_id="CLM-TEST001", reason="")
        data = json.loads(result)
        assert data["success"] is False
        assert "reason" in data["message"]

    def test_close_claim_from_open_without_payout_fails(self, temp_db):
        """Close from open without payout recorded returns clear error."""
        from claim_agent.db.constants import STATUS_OPEN, STATUS_PROCESSING
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.tools.status_tools import close_claim

        repo = ClaimRepository(db_path=temp_db)
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
        repo.update_claim_status(claim_id, STATUS_PROCESSING)
        repo.update_claim_status(claim_id, STATUS_OPEN)
        result = close_claim.run(claim_id=claim_id, reason="Test close")
        data = json.loads(result)
        assert data["success"] is False
        assert "without payout" in data["message"].lower()
        assert "open" in data["message"].lower()

    def test_close_claim_audit_trail(self, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.tools.status_tools import close_claim

        close_claim.run(claim_id="CLM-TEST001", reason="Final closure")
        repo = ClaimRepository()
        entries, _ = repo.get_claim_history("CLM-TEST001")
        close_entries = [e for e in entries if e.get("new_status") == "closed"]
        assert len(close_entries) >= 1
        assert "Final closure" in close_entries[-1].get("details", "")

    def test_close_claim_idempotent_when_already_closed(self, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.tools.status_tools import close_claim

        close_claim.run(claim_id="CLM-TEST001", reason="First close")
        result = close_claim.run(claim_id="CLM-TEST001", reason="Second close")
        data = json.loads(result)
        assert data["success"] is True
        assert "already closed" in data["message"]
        repo = ClaimRepository()
        entries, _ = repo.get_claim_history("CLM-TEST001")
        close_entries = [e for e in entries if e.get("new_status") == "closed"]
        assert len(close_entries) == 1


class TestCloseClaimLazyLoad:
    """Test that close_claim is properly lazy-loaded from tools/__init__.py."""

    def test_close_claim_lazy_load(self, seeded_temp_db):
        from claim_agent.tools import close_claim

        result = close_claim.run(claim_id="CLM-TEST001", reason="Lazy load test")
        data = json.loads(result)
        assert data["success"] is True


class TestStageAfterAction:
    """Tests for the _stage_after_action workflow stage."""

    @patch("claim_agent.workflow.stages._check_token_budget")
    @patch("claim_agent.workflow.stages.create_after_action_crew")
    def test_stage_after_action_calls_crew(
        self, mock_create_crew, mock_budget, temp_db
    ):
        """Verify _stage_after_action invokes the after-action crew via _run_crew_stage."""
        from claim_agent.context import ClaimContext
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_after_action

        repo = ClaimRepository(db_path=temp_db)
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001", vin="VIN123", vehicle_year=2022,
            vehicle_make="Test", vehicle_model="Car",
            incident_date="2025-06-01", incident_description="Hit",
            damage_description="Dent", estimated_damage=3000,
        ))
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "claim_id": claim_id, "claim_type": "new"}

        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-001",
            workflow_start_time=0.0,
            actor_id="workflow",
            claim_type="new",
            workflow_output="Claim opened successfully.",
            checkpoints={},
        )

        crew_inst = MagicMock()
        crew_inst.kickoff.return_value = MagicMock(raw="After-action complete.")
        mock_create_crew.return_value = crew_inst

        result = _stage_after_action(wf_ctx)

        assert result is None
        crew_inst.kickoff.assert_called_once()
        call_inputs = crew_inst.kickoff.call_args[1]["inputs"]
        assert "claim_data" in call_inputs
        assert "workflow_output" in call_inputs

    @patch("claim_agent.workflow.stages._check_token_budget")
    @patch("claim_agent.workflow.stages.create_after_action_crew")
    def test_stage_after_action_runs_for_all_claim_types(
        self, mock_create_crew, mock_budget, temp_db
    ):
        """After-action stage should run regardless of claim type."""
        from claim_agent.context import ClaimContext
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_after_action

        repo = ClaimRepository(db_path=temp_db)
        claim_id = repo.create_claim(ClaimInput(
            policy_number="POL-001", vin="VIN123", vehicle_year=2022,
            vehicle_make="Test", vehicle_model="Car",
            incident_date="2025-06-01", incident_description="Hit",
            damage_description="Dent", estimated_damage=3000,
        ))
        ctx = ClaimContext.from_defaults(db_path=temp_db)

        for claim_type in ("new", "total_loss", "partial_loss", "fraud", "duplicate", "bodily_injury"):
            crew_inst = MagicMock()
            crew_inst.kickoff.return_value = MagicMock(raw="Done.")
            mock_create_crew.return_value = crew_inst

            claim_data = {"vin": "VIN123"}
            claim_data_with_id = {**claim_data, "claim_id": claim_id, "claim_type": claim_type}

            wf_ctx = _WorkflowCtx(
                claim_id=claim_id,
                claim_data=claim_data,
                claim_data_with_id=claim_data_with_id,
                inputs={},
                similarity_score_for_escalation=None,
                context=ctx,
                workflow_run_id=f"run-{claim_type}",
                workflow_start_time=0.0,
                actor_id="workflow",
                claim_type=claim_type,
                workflow_output="output",
                checkpoints={},
            )

            result = _stage_after_action(wf_ctx)
            assert result is None, f"after_action should not early-return for {claim_type}"
            crew_inst.kickoff.assert_called_once()


class TestAfterActionInWorkflowStages:
    """Verify after_action is registered in WORKFLOW_STAGES."""

    def test_after_action_in_workflow_stages(self):
        from claim_agent.workflow.helpers import WORKFLOW_STAGES

        assert "after_action" in WORKFLOW_STAGES

    def test_after_action_is_last_stage(self):
        from claim_agent.workflow.helpers import WORKFLOW_STAGES

        assert WORKFLOW_STAGES[-1] == "after_action"


class TestAfterActionSkillFiles:
    """Verify after-action skill files load correctly."""

    def test_load_after_action_summary_skill(self):
        from claim_agent.skills import AFTER_ACTION_SUMMARY, load_skill

        skill = load_skill(AFTER_ACTION_SUMMARY)
        assert skill["role"] is not None
        assert skill["goal"] is not None
        assert skill["backstory"] is not None

    def test_load_after_action_status_skill(self):
        from claim_agent.skills import AFTER_ACTION_STATUS, load_skill

        skill = load_skill(AFTER_ACTION_STATUS)
        assert skill["role"] is not None
        assert skill["goal"] is not None
        assert skill["backstory"] is not None


class TestAfterActionAgentFactories:
    """Verify agent factory functions create agents with correct tools."""

    def test_create_summary_agent(self):
        from claim_agent.agents.after_action import create_after_action_summary_agent

        agent = create_after_action_summary_agent(llm=_mock_llm())
        assert agent.role == "After-Action Summary Specialist"
        tool_names = [t.name for t in agent.tools]
        assert "Add After-Action Note" in tool_names
        assert "Get Claim Notes" in tool_names

    def test_create_status_agent(self):
        from claim_agent.agents.after_action import create_after_action_status_agent

        agent = create_after_action_status_agent(llm=_mock_llm())
        assert agent.role == "After-Action Status Specialist"
        tool_names = [t.name for t in agent.tools]
        assert "Close Claim" in tool_names
        assert "Get Claim Notes" in tool_names


class TestAddAfterActionNote:
    """Tests for the add_after_action_note tool with token-budget enforcement."""

    def test_adds_note_within_budget(self, seeded_temp_db):
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        note = "## Interaction Summary\n- Claim type: new\n- Routed successfully"
        result = add_after_action_note.run(claim_id="CLM-TEST001", note=note)
        data = json.loads(result)
        assert data["success"] is True
        assert data["truncated"] is False

    def test_truncates_note_exceeding_budget(self, seeded_temp_db):
        from claim_agent.config import get_settings
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        settings = get_settings()
        original = settings.after_action_note_max_tokens
        try:
            object.__setattr__(settings, "after_action_note_max_tokens", 10)
            long_note = "Line one of note content\nLine two of note content\nLine three of note\n" * 10
            result = add_after_action_note.run(claim_id="CLM-TEST001", note=long_note)
            data = json.loads(result)
            assert data["success"] is True
            assert data["truncated"] is True
            assert "truncated" in data["message"]
        finally:
            object.__setattr__(settings, "after_action_note_max_tokens", original)

    def test_truncated_note_stored_within_limit(self, seeded_temp_db):
        from claim_agent.config import get_settings
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.tools.claim_notes_tools import CHARS_PER_TOKEN, add_after_action_note

        settings = get_settings()
        original = settings.after_action_note_max_tokens
        max_tokens = 10
        try:
            object.__setattr__(settings, "after_action_note_max_tokens", max_tokens)
            long_note = "A" * 500
            add_after_action_note.run(claim_id="CLM-TEST001", note=long_note)
        finally:
            object.__setattr__(settings, "after_action_note_max_tokens", original)

        repo = ClaimRepository()
        notes = repo.get_notes("CLM-TEST001")
        after_action_notes = [n for n in notes if n["actor_id"] == "After-Action Summary"]
        assert len(after_action_notes) == 1
        assert len(after_action_notes[0]["note"]) <= max_tokens * CHARS_PER_TOKEN

    def test_truncation_breaks_at_newline(self, seeded_temp_db):
        from claim_agent.config import get_settings
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        settings = get_settings()
        original = settings.after_action_note_max_tokens
        try:
            object.__setattr__(settings, "after_action_note_max_tokens", 5)
            note = "Short\nThis is a longer second line that will push over the limit"
            result = add_after_action_note.run(claim_id="CLM-TEST001", note=note)
            data = json.loads(result)
            assert data["success"] is True
            assert data["truncated"] is True
        finally:
            object.__setattr__(settings, "after_action_note_max_tokens", original)

    def test_missing_claim_id(self):
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        result = add_after_action_note.run(claim_id="", note="test")
        data = json.loads(result)
        assert data["success"] is False

    def test_empty_note(self):
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        result = add_after_action_note.run(claim_id="CLM-TEST001", note="")
        data = json.loads(result)
        assert data["success"] is False

    def test_claim_not_found(self, temp_db):
        from claim_agent.tools.claim_notes_tools import add_after_action_note

        result = add_after_action_note.run(claim_id="CLM-NOPE", note="test")
        data = json.loads(result)
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_lazy_load(self, seeded_temp_db):
        from claim_agent.tools import add_after_action_note

        result = add_after_action_note.run(claim_id="CLM-TEST001", note="lazy load")
        data = json.loads(result)
        assert data["success"] is True


class TestAfterActionNoteMaxTokensSetting:
    """Verify the AFTER_ACTION_NOTE_MAX_TOKENS setting exists and is configurable."""

    def test_default_value(self):
        from claim_agent.config.settings import AFTER_ACTION_NOTE_MAX_TOKENS

        assert isinstance(AFTER_ACTION_NOTE_MAX_TOKENS, int)
        assert AFTER_ACTION_NOTE_MAX_TOKENS > 0

    def test_env_override(self):
        with patch.dict(os.environ, {"AFTER_ACTION_NOTE_MAX_TOKENS": "512"}):
            import claim_agent.config as _cfg
            _cfg._settings = None
            from claim_agent.config import get_settings
            s = get_settings()
            assert s.after_action_note_max_tokens == 512
            _cfg._settings = None
