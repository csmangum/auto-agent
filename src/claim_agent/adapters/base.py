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


class FraudReportingAdapter(ABC):
    """Interface for fraud-reporting filings (state bureau, NICB, NISS)."""

    @abstractmethod
    def file_state_bureau_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a state insurance fraud bureau report and return filing metadata.

        *payload* is the validated template payload (merged with claim defaults); it is
        forwarded to the integration backend so required fields can be submitted.
        """
        ...

    @abstractmethod
    def file_nicb_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        """Submit a NICB referral and return filing metadata."""
        ...

    @abstractmethod
    def file_niss_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        """Submit a NISS referral and return filing metadata."""
        ...


class StateBureauAdapter(ABC):
    """Interface for filing fraud reports with state insurance bureaus (per-state endpoints)."""

    @abstractmethod
    def submit_fraud_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        """Submit a state insurance fraud bureau report and return filing metadata."""
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


class ReverseImageAdapter(ABC):
    """Interface for reverse-image / stock-photo lookup.

    Used as an **optional** fraud-signal during photo forensics.  Callers
    should gate the call behind a feature flag (e.g. ``REVERSE_IMAGE_ADAPTER``
    env var) so FNOL processing is never blocked on an external API.

    Privacy note
    ------------
    Images submitted to a production reverse-image provider may contain PII
    (licence plates, faces, GPS EXIF data).  Ensure that:

    * The provider's DPA covers your jurisdiction's data-transfer requirements.
    * Images are scrubbed of EXIF metadata before transmission when required.
    * API keys are stored in secrets management, never in source code.
    * Usage is disclosed in the applicable privacy notice / DSAR records.

    Set ``REVERSE_IMAGE_ADAPTER=stub`` (or omit the var entirely for ``mock``)
    in environments where no real key is available.
    """

    @abstractmethod
    def match_web_occurrences(
        self,
        image: bytes | Path,
    ) -> list[dict[str, Any]]:
        """Search for web occurrences of *image* (stock-photo / prior-claim check).

        Parameters
        ----------
        image:
            Raw JPEG/PNG bytes **or** a :class:`pathlib.Path` to a local file.

        Returns
        -------
        list[dict]
            Each entry represents one match and **must** contain:

            * ``url`` (str): where the image was found.
            * ``match_score`` (float, 0-1): similarity confidence.
            * ``source_label`` (str): human-readable source, e.g. ``"stock_photo_site"``,
              ``"social_media"``, ``"prior_claim"``.

            Optional keys: ``title``, ``page_fetched_at`` (ISO-8601 timestamp).

        **Production** implementations should not raise on non-critical failures;
        return an empty list if the lookup produces no results or the provider is
        unavailable. **Stub** adapters (e.g. ``StubReverseImageAdapter``) may raise
        ``NotImplementedError`` to signal a missing integration.
        """
        ...


class ERPAdapter(ABC):
    """Interface for repair / shop management system (ERP) integrations.

    Supports bi-directional sync between the carrier and external ERP systems
    (e.g. Mitchell RepairCenter, CCC ONE, Solera, or custom shop platforms).

    Outbound methods push carrier-side events to the ERP (assignment, estimate
    updates, status changes).  The inbound method polls the ERP for pending
    events that should be reflected in claim workflows (estimate approvals,
    parts delays, supplement requests).

    Identity mapping
    ----------------
    ``resolve_shop_id`` translates the internal ``shop_id`` to the ERP
    tenant / location identifier.  The default implementation is an identity
    mapping; override in adapters whose ERP uses a different ID scheme.

    Adapter selection
    -----------------
    Set ``ERP_ADAPTER=mock | stub | rest`` (default: ``mock``).
    For ``rest``, also configure the ``ERP_REST_*`` env vars.
    """

    @abstractmethod
    def push_repair_assignment(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        repair_amount: float | None,
        vehicle_info: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Notify ERP of a new repair assignment (outbound: carrier → ERP).

        Parameters
        ----------
        claim_id:
            Internal claim identifier.
        shop_id:
            Internal shop identifier (resolved via ``resolve_shop_id`` before
            submitting to the ERP).
        authorization_id:
            Repair authorization reference, if issued.
        repair_amount:
            Approved repair amount in dollars, if known.
        vehicle_info:
            Optional dict with VIN, year, make, model.

        Returns
        -------
        dict
            Must include ``erp_reference`` (str) and ``status``
            (``submitted`` | ``queued`` | ``rejected``).
            Optional: ``message`` (str).
        """
        ...

    @abstractmethod
    def push_estimate_update(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        estimate_amount: float,
        line_items: list[dict[str, Any]] | None,
        is_supplement: bool,
    ) -> dict[str, Any]:
        """Push an estimate or supplement update to ERP (outbound: carrier → ERP).

        Parameters
        ----------
        claim_id:
            Internal claim identifier.
        shop_id:
            Internal shop identifier.
        authorization_id:
            Repair authorization reference.
        estimate_amount:
            Total estimate amount in dollars.
        line_items:
            Optional list of ``{description, quantity, unit_price}`` dicts.
        is_supplement:
            ``True`` when this is a supplemental estimate rather than an initial one.

        Returns
        -------
        dict
            Must include ``erp_reference`` (str) and ``status``.
            Optional: ``approved_amount`` (float), ``message`` (str).
        """
        ...

    @abstractmethod
    def push_repair_status(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        status: str,
        notes: str | None,
    ) -> dict[str, Any]:
        """Sync a repair status change to ERP (outbound: carrier → ERP).

        Parameters
        ----------
        status:
            One of the ``VALID_REPAIR_STATUSES`` values (e.g. ``received``,
            ``parts_ordered``, ``ready``).

        Returns
        -------
        dict
            Must include ``erp_reference`` (str) and ``status``.
        """
        ...

    @abstractmethod
    def pull_pending_events(
        self,
        *,
        shop_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Poll ERP for pending inbound events (inbound: ERP → carrier).

        Parameters
        ----------
        shop_id:
            If provided, limit results to this shop (internal ID).
        since:
            ISO-8601 timestamp; if provided, return only events newer than
            this value.

        Returns
        -------
        list[dict]
            Each dict must include:

            * ``event_type`` (str): ``estimate_approved`` | ``parts_delayed``
              | ``supplement_requested``.
            * ``claim_id`` (str): internal claim identifier.
            * ``shop_id`` (str): internal shop identifier.
            * ``erp_event_id`` (str): ERP-side reference (for idempotency).
            * ``occurred_at`` (str): ISO-8601 timestamp.

            Optional per event type:

            * ``estimate_approved``: ``approved_amount`` (float).
            * ``parts_delayed``: ``delay_reason`` (str),
              ``expected_availability_date`` (str).
            * ``supplement_requested``: ``supplement_amount`` (float),
              ``description`` (str).
        """
        ...

    def resolve_shop_id(self, internal_shop_id: str) -> str:
        """Map internal shop_id to the ERP tenant / location ID.

        The default implementation is an identity mapping—the internal ID is
        used as-is.  Override in adapters whose ERP has a separate identity
        scheme (e.g. numeric location codes, tenant UUIDs).

        Args:
            internal_shop_id: The shop_id stored in the carrier system.

        Returns:
            The corresponding ERP identifier for the shop.
        """
        return internal_shop_id


# ---------------------------------------------------------------------------
# ERP event types (shared by adapters and inbound webhook routes)
# ---------------------------------------------------------------------------

VALID_ERP_EVENT_TYPES: frozenset[str] = frozenset(
    {"estimate_approved", "parts_delayed", "supplement_requested"}
)

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
