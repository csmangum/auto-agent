"""Unit tests for ClaimContext and AdapterRegistry."""

from claim_agent.context import AdapterRegistry, ClaimContext
from claim_agent.db.repository import ClaimRepository
from claim_agent.observability.metrics import ClaimMetrics
from claim_agent.services.adjuster_action_service import AdjusterActionService


class TestAdapterRegistry:
    def test_from_defaults_returns_registry(self):
        reg = AdapterRegistry.from_defaults()
        assert reg.policy is not None
        assert reg.valuation is not None
        assert reg.repair_shop is not None
        assert reg.parts is not None
        assert reg.siu is not None
        assert reg.claim_search is not None
        assert reg.fraud_reporting is not None
        assert reg.nmvtis is not None
        assert reg.gap_insurance is not None
        assert reg.cms is not None


class TestClaimContext:
    def test_construction_with_explicit_deps(self, temp_db):
        repo = ClaimRepository(db_path=temp_db)
        adjuster = AdjusterActionService(repo=repo)
        adapters = AdapterRegistry.from_defaults()
        metrics = ClaimMetrics()
        ctx = ClaimContext(
            repo=repo,
            adjuster_service=adjuster,
            adapters=adapters,
            metrics=metrics,
            llm=None,
        )
        assert ctx.repo is repo
        assert ctx.adjuster_service is adjuster
        assert ctx.adapters is adapters
        assert ctx.metrics is metrics
        assert ctx.llm is None

    def test_from_defaults_uses_temp_db(self, temp_db):
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        assert ctx.repo is not None
        assert ctx.adjuster_service is not None
        assert ctx.adapters is not None
        assert ctx.metrics is not None
        assert ctx.llm is None

    def test_from_defaults_with_llm(self, temp_db):
        mock_llm = object()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)
        assert ctx.llm is mock_llm
