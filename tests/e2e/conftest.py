"""Shared fixtures for E2E tests.

E2E tests submit claims via the REST API and assert outcomes.
Database, sample claims, and mock LLM fixtures come from tests.conftest_shared.
"""

import json
import shutil
import tempfile
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import claim_agent.storage.factory as factory_mod

_ESCALATION_NO_REVIEW = json.dumps({
    "needs_review": False,
    "escalation_reasons": [],
    "priority": "low",
    "fraud_indicators": [],
    "recommended_action": "",
})

_STAGES = "claim_agent.workflow.stages"


@pytest.fixture(autouse=True)
def temp_db():
    """Override root temp_db - E2E tests use integration_db explicitly."""
    yield None


@pytest.fixture
def e2e_client(integration_db: str, monkeypatch):
    """Create a TestClient for the FastAPI app, bound to integration_db.

    CLAIMS_DB_PATH is set by integration_db fixture before the client is created.
    """
    from claim_agent.api.server import app

    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)

    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", tmpdir)

    try:
        yield TestClient(app)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def workflow_patches(mock_llm_instance, mock_router_response, mock_crew_response):
    """Flatten the common 6-deep workflow patch stack into a single context manager.

    Yields a ``WorkflowMocks`` dict with keys for each patched target.  Tests
    configure mocks *after* entering the context (``mocks["router"].return_value
    .kickoff.return_value = ...``).

    Extra claim-type crew patches can be added by the test using additional
    ``with patch(...)`` blocks around the API call — this fixture only covers the
    targets shared across all claim types: get_llm, router, after-action,
    escalation, and task planner.
    """
    factory_mod._storage_instance = None

    class _Ctx:
        def __init__(self):
            self._stack = ExitStack()
            self.llm = None
            self.router = None
            self.after_action = None
            self.escalation = None
            self.task_planner = None

        def __enter__(self):
            s = self._stack.__enter__()  # noqa: F841
            self.llm = self._stack.enter_context(
                patch("claim_agent.workflow.orchestrator.get_llm")
            )
            self.router = self._stack.enter_context(
                patch(f"{_STAGES}.create_router_crew")
            )
            self.after_action = self._stack.enter_context(
                patch(f"{_STAGES}.create_after_action_crew")
            )
            self.escalation = self._stack.enter_context(
                patch(f"{_STAGES}.evaluate_escalation_impl")
            )
            self.task_planner = self._stack.enter_context(
                patch(f"{_STAGES}.create_task_planner_crew")
            )
            self.llm.return_value = mock_llm_instance
            self.after_action.return_value.kickoff.return_value = mock_crew_response(
                "After-action summary added."
            )
            self.escalation.return_value = _ESCALATION_NO_REVIEW
            self.task_planner.return_value.kickoff.return_value = mock_crew_response(
                "Tasks created."
            )
            return self

        def __exit__(self, *exc):
            return self._stack.__exit__(*exc)

        def set_router(self, claim_type: str, reasoning: str = ""):
            self.router.return_value.kickoff.return_value = mock_router_response(
                claim_type, reasoning
            )

        def add_patch(self, target: str):
            """Enter an additional ``patch(target)`` and return the mock."""
            return self._stack.enter_context(patch(target))

    return _Ctx()
