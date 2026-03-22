"""Stub adapters for real external integrations.

Each stub raises ``NotImplementedError`` with guidance on what the real
implementation should connect to.  Use these as starting points when
building production adapters.
"""

from pathlib import Path
from typing import Any

from claim_agent.adapters.base import (
    CMSReportingAdapter,
    ClaimSearchAdapter,
    GapInsuranceAdapter,
    NMVTISAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    ReverseImageAdapter,
    SIUAdapter,
    StateBureauAdapter,
    ValuationAdapter,
)


class StubPolicyAdapter(PolicyAdapter):
    """Placeholder for a real policy-database integration (REST API / SQL).

    Replace the body of ``get_policy`` with a call to the production
    policy management system. This stub does not return policy data or
    ``named_insured``, so FNOL will not auto-add a policyholder from the adapter.
    """

    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        raise NotImplementedError(
            "StubPolicyAdapter: connect to a real policy database "
            "(e.g. REST endpoint or SQL query). "
            "Expected return: {coverage, deductible, status} or None."
        )


class StubValuationAdapter(ValuationAdapter):
    """Placeholder for a real vehicle-valuation service (KBB / Black Book).

    Replace the body of ``get_vehicle_value`` with a call to the
    production valuation API.
    """

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "StubValuationAdapter: connect to a real valuation API "
            "(e.g. KBB, Black Book). "
            "Expected return: {value, condition} or None."
        )


class StubRepairShopAdapter(RepairShopAdapter):
    """Placeholder for a real repair-shop network API.

    Replace each method with calls to the production shop-network
    service.
    """

    def get_shops(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError(
            "StubRepairShopAdapter.get_shops: connect to a real shop-network API. "
            "Expected return: {shop_id: {name, address, ...}, ...}."
        )

    def get_shop(self, shop_id: str) -> dict[str, Any] | None:
        raise NotImplementedError(
            "StubRepairShopAdapter.get_shop: connect to a real shop-network API. "
            "Expected return: shop data dict or None."
        )

    def get_labor_operations(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError(
            "StubRepairShopAdapter.get_labor_operations: connect to a real "
            "labor-operations catalog. "
            "Expected return: {op_id: {base_hours, ...}, ...}."
        )


class StubPartsAdapter(PartsAdapter):
    """Placeholder for a real parts-vendor API.

    Replace the body of ``get_catalog`` with a call to the production
    parts catalog service.
    """

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError(
            "StubPartsAdapter: connect to a real parts-vendor API. "
            "Expected return: {part_id: {name, oem_price, ...}, ...}."
        )


class StubSIUAdapter(SIUAdapter):
    """Placeholder for a real SIU case-management system.

    Replace the body of ``create_case`` with a call to the production
    SIU system.
    """

    def create_case(self, claim_id: str, indicators: list[str]) -> str:
        raise NotImplementedError(
            "StubSIUAdapter: connect to a real SIU case-management system. "
            "Expected return: case_id string."
        )


class StubStateBureauAdapter(StateBureauAdapter):
    """Placeholder for production state DOI fraud bureau integration."""

    def submit_fraud_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubStateBureauAdapter: connect to a production state fraud bureau API "
            "(e.g. CA CDI, TX DFR, FL DIFS, NY FBU, GA DOI). "
            "Expected return: {report_id, state, message, metadata?}."
        )


class StubClaimSearchAdapter(ClaimSearchAdapter):
    """Placeholder for a real NICB/ISO ClaimSearch integration."""

    def search_claims(
        self,
        *,
        vin: str | None = None,
        claimant_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "StubClaimSearchAdapter: connect to a real NICB/ISO ClaimSearch API. "
            "Expected return: list of external claim match dicts."
        )


class StubOCRAdapter(OCRAdapter):
    """Placeholder for a real OCR service (Tesseract, Azure Document Intelligence, etc.)."""

    def extract_structured_data(self, file_path: Path, document_type: str) -> dict[str, Any] | None:
        return None


class StubNMVTISAdapter(NMVTISAdapter):
    """Placeholder for the production NMVTIS data provider / batch submission integration."""

    def submit_total_loss_report(
        self,
        *,
        claim_id: str,
        vin: str,
        vehicle_year: int,
        make: str,
        model: str,
        loss_type: str,
        trigger_event: str,
        dmv_reference: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubNMVTISAdapter: connect to the DOJ/AAMVA-designated NMVTIS reporting channel "
            "(batch upload, web service, or vendor API). "
            "Return nmvtis_reference and status from the provider acknowledgment."
        )


class StubCMSReportingAdapter(CMSReportingAdapter):
    """Placeholder for CMS COBC / Section 111 production integration."""

    def evaluate_settlement_reporting(
        self,
        *,
        claim_id: str,
        settlement_amount: float,
        claimant_medicare_eligible: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubCMSReportingAdapter: connect to CMS Section 111 reporting (COBC). "
            "Return reporting_required, conditional_payment_amount, msa_required, and notes."
        )


class StubGapInsuranceAdapter(GapInsuranceAdapter):
    """Placeholder for a dealer or standalone gap carrier API (REST, EDI, portal)."""

    def submit_shortfall_claim(
        self,
        *,
        claim_id: str,
        policy_number: str,
        auto_payout_amount: float,
        loan_balance: float,
        shortfall_amount: float,
        vin: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "StubGapInsuranceAdapter: connect to a production gap carrier "
            "(dealer F&I platform, lender, or standalone GAP administrator). "
            "Submit total-loss settlement vs loan balance and return carrier claim id and status."
        )


class StubReverseImageAdapter(ReverseImageAdapter):
    """Placeholder for a real reverse-image / stock-photo search integration.

    Raises ``NotImplementedError`` by design (stub contract), unlike production
    adapters that should return an empty list on soft failures.

    Replace ``match_web_occurrences`` with a call to a production provider
    (e.g. Google Vision ``SIMILAR_WEB_PAGES``, TinEye, or a proprietary
    prior-claim image index).

    Privacy reminder: scrub EXIF metadata from images before submission and
    verify DPA coverage for cross-border transfer (see docs/adapters.md).
    """

    def match_web_occurrences(self, image: bytes | Path) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "StubReverseImageAdapter: connect to a real reverse-image provider "
            "(e.g. Google Cloud Vision similarWebPages, TinEye, or an internal "
            "prior-claim image index). "
            "Return a list of dicts each containing url, match_score, and source_label."
        )
