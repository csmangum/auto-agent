"""Stub fraud-reporting adapter for production integration placeholders."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import FraudReportingAdapter


class StubFraudReportingAdapter(FraudReportingAdapter):
    """Placeholder adapter for NICB/NISS/state-bureau production integrations."""

    def file_state_bureau_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubFraudReportingAdapter.file_state_bureau_report: connect to a real state bureau filing API."
        )

    def file_nicb_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubFraudReportingAdapter.file_nicb_report: connect to a real NICB filing API."
        )

    def file_niss_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubFraudReportingAdapter.file_niss_report: connect to a real NISS filing API."
        )
