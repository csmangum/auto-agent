"""Abstract base classes for external-system adapters.

Each adapter defines the contract for a specific external integration.
Concrete implementations live in ``mock/`` (current behavior) and
``stub.py`` (placeholder for real integrations).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class OCRAdapter(ABC):
    """Interface for OCR / structured data extraction from documents."""

    @abstractmethod
    def extract_structured_data(self, file_path: Path, document_type: str) -> dict[str, Any] | None:
        """Extract structured data from document.

        Returns None if unsupported or extraction fails.
        Expected keys for estimates: line_items, total, parts_cost, labor_cost.
        For police_report: incident_date, parties, report_number.
        For medical_record: diagnoses, charges, provider.
        """
        ...


class PolicyAdapter(ABC):
    """Interface for policy database lookups."""

    @abstractmethod
    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        """Return policy data for *policy_number*, or ``None`` if not found.

        Expected keys when found: ``status``, and either:
        - New format: ``coverages`` (list, e.g. ["liability","collision","comprehensive"]),
          ``collision_deductible``, ``comprehensive_deductible``, ``liability_limits``.
          Optionally, when available: ``named_insured`` (list of dicts with name, email,
          phone) and ``drivers`` (list of dicts with name, license_number, relationship).
          These optional keys may be omitted entirely, especially for legacy/backends
          that still use a simpler schema — omitting them disables claimant verification
          rather than escalating all claims.
        - Legacy: ``coverage`` (str), ``deductible`` (number)
        """
        ...


class ValuationAdapter(ABC):
    """Interface for vehicle valuation lookups."""

    @abstractmethod
    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        """Return valuation data, or ``None`` if no match.

        Expected keys when found: ``value`` (float), ``condition`` (str).
        Optional: ``comparables`` (list of dicts with vin, year, make, model,
        price, mileage, source) for comparable vehicle analysis.
        """
        ...


class RepairShopAdapter(ABC):
    """Interface for repair-shop network queries."""

    @abstractmethod
    def get_shops(self) -> dict[str, dict[str, Any]]:
        """Return all shops as ``{shop_id: shop_data, ...}``."""
        ...

    @abstractmethod
    def get_shop(self, shop_id: str) -> dict[str, Any] | None:
        """Return data for a single shop, or ``None`` if not found."""
        ...

    @abstractmethod
    def get_labor_operations(self) -> dict[str, dict[str, Any]]:
        """Return labor-operation catalog as ``{op_id: op_data, ...}``."""
        ...


class PartsAdapter(ABC):
    """Interface for parts-catalog queries."""

    @abstractmethod
    def get_catalog(self) -> dict[str, dict[str, Any]]:
        """Return parts catalog as ``{part_id: part_data, ...}``."""
        ...


class SIUAdapter(ABC):
    """Interface for Special Investigations Unit case management."""

    @abstractmethod
    def create_case(self, claim_id: str, indicators: list[str]) -> str:
        """Create an SIU case and return the case identifier."""
        ...

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        """Return case details for an SIU case, or None if not found."""
        raise NotImplementedError(
            "SIUAdapter.get_case: override in adapter for SIU case lookup."
        )

    def add_investigation_note(self, case_id: str, note: str, category: str = "general") -> bool:
        """Add an investigation note to an SIU case. Returns True on success."""
        raise NotImplementedError(
            "SIUAdapter.add_investigation_note: override in adapter for SIU case notes."
        )

    def update_case_status(self, case_id: str, status: str) -> bool:
        """Update SIU case status (e.g. open, investigating, referred, closed). Returns True on success."""
        raise NotImplementedError(
            "SIUAdapter.update_case_status: override in adapter for SIU case status updates."
        )


class ClaimSearchAdapter(ABC):
    """Interface for cross-carrier claim search (NICB/ISO-style)."""

    @abstractmethod
    def search_claims(
        self,
        *,
        vin: str | None = None,
        claimant_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return external claim-search matches for provided identifiers."""
        ...
