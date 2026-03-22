"""Dependency injection context for claim processing.

Provides ``ClaimContext`` -- a container holding all shared dependencies
(repository, adjuster_service, adapters, metrics, LLM) that is threaded
through the workflow pipeline, tool functions, and entry points instead of
relying on inline instantiation and global singletons.
"""

from __future__ import annotations

from dataclasses import dataclass

from claim_agent.adapters.base import (
    CMSReportingAdapter,
    ClaimSearchAdapter,
    FraudReportingAdapter,
    GapInsuranceAdapter,
    NMVTISAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    StateBureauAdapter,
    ValuationAdapter,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.db.repository import ClaimRepository
from claim_agent.observability.metrics import ClaimMetrics
from claim_agent.services.adjuster_action_service import AdjusterActionService


@dataclass
class AdapterRegistry:
    """Holds concrete adapter instances for all external integrations."""

    policy: PolicyAdapter
    valuation: ValuationAdapter
    repair_shop: RepairShopAdapter
    parts: PartsAdapter
    siu: SIUAdapter
    state_bureau: StateBureauAdapter
    claim_search: ClaimSearchAdapter
    fraud_reporting: FraudReportingAdapter
    nmvtis: NMVTISAdapter
    gap_insurance: GapInsuranceAdapter
    cms: CMSReportingAdapter

    @classmethod
    def from_defaults(cls) -> AdapterRegistry:
        """Build from the existing thread-safe singleton factories."""
        # Inline import to avoid circular dependency with adapters.registry
        from claim_agent.adapters.registry import (
            get_claim_search_adapter,
            get_cms_reporting_adapter,
            get_fraud_reporting_adapter,
            get_gap_insurance_adapter,
            get_nmvtis_adapter,
            get_parts_adapter,
            get_policy_adapter,
            get_repair_shop_adapter,
            get_siu_adapter,
            get_state_bureau_adapter,
            get_valuation_adapter,
        )

        return cls(
            policy=get_policy_adapter(),
            valuation=get_valuation_adapter(),
            repair_shop=get_repair_shop_adapter(),
            parts=get_parts_adapter(),
            siu=get_siu_adapter(),
            state_bureau=get_state_bureau_adapter(),
            claim_search=get_claim_search_adapter(),
            fraud_reporting=get_fraud_reporting_adapter(),
            nmvtis=get_nmvtis_adapter(),
            gap_insurance=get_gap_insurance_adapter(),
            cms=get_cms_reporting_adapter(),
        )


@dataclass
class ClaimContext:
    """Container for all shared dependencies in claim processing.

    Holds repository, adjuster_service, adapters, metrics, and optional llm.
    Pass this through the workflow pipeline and tool functions instead of
    calling global factories directly.  ``llm`` is optional -- tool functions
    never need it, and creating it requires ``OPENAI_API_KEY``.
    """

    repo: ClaimRepository
    adjuster_service: AdjusterActionService
    adapters: AdapterRegistry
    metrics: ClaimMetrics
    llm: LLMProtocol | None = None

    @classmethod
    def from_defaults(
        cls,
        *,
        db_path: str | None = None,
        llm: LLMProtocol | None = None,
    ) -> ClaimContext:
        """Build with production defaults.

        Parameters
        ----------
        db_path:
            Forwarded to ``ClaimRepository``.  ``None`` uses the env-configured
            default.
        llm:
            Pre-built LLM instance.  When ``None`` the context is created
            without an LLM (sufficient for tool functions).
        """
        from claim_agent.observability import get_metrics

        repo = ClaimRepository(db_path=db_path)
        return cls(
            repo=repo,
            adjuster_service=AdjusterActionService(repo=repo),
            adapters=AdapterRegistry.from_defaults(),
            metrics=get_metrics(),
            llm=llm,
        )
