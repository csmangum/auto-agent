"""Stub adapters for real external integrations.

Each stub raises ``NotImplementedError`` with guidance on what the real
implementation should connect to.  Use these as starting points when
building production adapters.
"""

from pathlib import Path
from typing import Any

from claim_agent.adapters.base import (
    ClaimSearchAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)


class StubPolicyAdapter(PolicyAdapter):
    """Placeholder for a real policy-database integration (REST API / SQL).

    Replace the body of ``get_policy`` with a call to the production
    policy management system.
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
