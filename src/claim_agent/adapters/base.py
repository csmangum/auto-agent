"""Abstract base classes for external-system adapters.

Each adapter defines the contract for a specific external integration.
Concrete implementations live in ``mock/`` (current behavior) and
``stub.py`` (placeholder for real integrations).
"""

from abc import ABC, abstractmethod
from typing import Any


class PolicyAdapter(ABC):
    """Interface for policy database lookups."""

    @abstractmethod
    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        """Return policy data for *policy_number*, or ``None`` if not found.

        Expected keys when found: ``status``, and either:
        - New format: ``coverages`` (list, e.g. ["liability","collision","comprehensive"]),
          ``collision_deductible``, ``comprehensive_deductible``, ``liability_limits``
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
