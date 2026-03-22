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
          Optionally, when available: ``named_insured`` (list of dicts; use ``name``,
          or ``full_name`` / ``display_name`` per ``get_policy_party_display_name``,
          plus optional ``email``, ``phone``) and ``drivers`` (list of dicts with name,
          license_number, relationship).
          These optional keys may be omitted entirely, especially for legacy/backends
          that still use a simpler schema — omitting them disables claimant verification
          rather than escalating all claims.
          When ``named_insured`` is present, FNOL claim creation may auto-add a
          **policyholder** party from the first entry with a resolvable display name
          if the intake payload did not already include a policyholder
          (see ``merge_fnol_parties_with_named_insured_policyholder``).
        - Legacy: ``coverage`` (str), ``deductible`` (number)
        
        Territory coverage (optional):
        - ``territory`` (str or list): Geographic coverage area (e.g., "US", "USA_Canada",
          US states/DC/insular areas (e.g. PR, Puerto Rico), Canadian provinces/territories
          (e.g. ON, Ontario), or a list mixing names and codes)
        - ``excluded_territories`` (list): Territories explicitly excluded from coverage

        Policy term (optional, ISO date ``YYYY-MM-DD`` or date-like values):
        - ``effective_date`` / ``expiration_date``: inclusive coverage window for FNOL checks.
        - Aliases: ``term_start`` maps to effective, ``term_end`` to expiration (normalized
          in policy query output). Omit both to skip incident-vs-term verification.
        - If only one of effective/expiration (or ``term_start`` / ``term_end``) is provided,
          the term is treated as incomplete and FNOL coverage verification escalates to
          ``under_investigation``; adapters should supply both dates or omit both.
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


class StateBureauAdapter(ABC):
    """Interface for filing fraud reports with state insurance bureaus."""

    @abstractmethod
    def submit_fraud_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        """Submit a state bureau fraud report and return filing metadata."""
        ...


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


class NMVTISAdapter(ABC):
    """Interface for National Motor Vehicle Title Information System (NMVTIS) insurer reporting.

    Production implementations integrate with the DOJ/AAMVA-designated NMVTIS data provider
    workflow (49 U.S.C. 30502; 28 CFR Part 25). This codebase only defines the contract.
    """

    @abstractmethod
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
        """Report a total loss / salvage vehicle to NMVTIS (or queue for submission).

        Parameters
        ----------
        loss_type:
            e.g. ``total_loss``, ``salvage``.
        trigger_event:
            ``dmv_salvage_report`` | ``salvage_disposition`` | ``manual_resubmit``.
        dmv_reference:
            State DMV / title reference when known.

        Returns
        -------
        dict
            At minimum ``nmvtis_reference`` (str) and ``status`` (``accepted`` | ``pending`` | ``rejected``).
            Optional: ``message`` (str).
        """
        ...


class CMSReportingAdapter(ABC):
    """Interface for Medicare/CMS reporting eligibility (MMSEA Section 111 style).

    Production implementations integrate with CMS COBC / Section 111 reporting.
    """

    @abstractmethod
    def evaluate_settlement_reporting(
        self,
        *,
        claim_id: str,
        settlement_amount: float,
        claimant_medicare_eligible: bool,
    ) -> dict[str, Any]:
        """Return reporting flags and amounts for a proposed settlement.

        Expected keys: ``settlement_amount``, ``claimant_medicare_eligible``,
        ``reporting_threshold``, ``reporting_required`` (bool),
        ``conditional_payment_amount`` (float | None), ``msa_required`` (bool),
        ``notes`` (str).
        """
        ...


class GapInsuranceAdapter(ABC):
    """Interface for gap (loan/lease) carrier coordination after auto total loss."""

    @abstractmethod
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
        """Notify the gap carrier or open a gap claim for the loan/lease shortfall.

        Returns a dict with at least:
        - ``gap_claim_id`` (str): carrier reference
        - ``status`` (str): e.g. ``submitted``, ``approved_pending_payment``,
          ``partial_approval``, ``denied``
        Optional:
        - ``approved_amount`` (float | None): amount the gap carrier expects to pay
        - ``denial_reason`` (str | None)
        - ``remaining_shortfall_after_gap`` (float | None): balance after gap decision
        - ``message`` (str): human-readable carrier message
        """
        ...

    def get_claim_status(self, gap_claim_id: str) -> dict[str, Any] | None:
        """Return current gap claim status from the carrier, or None if unknown."""
        raise NotImplementedError(
            "GapInsuranceAdapter.get_claim_status: override for carrier status polling."
        )
