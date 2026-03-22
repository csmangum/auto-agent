"""Cross-border data transfer controls for privacy compliance.

Implements controls for data exports across jurisdictions as required by GDPR
Article 44+, CCPA, and analogous frameworks.  The module provides:

* **Jurisdiction classification** – map a country/state/region string to a
  ``JurisdictionZone`` (EU_EEA, US, ADEQUATE, OTHER).
* **Known data-flow catalog** – the authoritative list of data paths in this
  system that cross or may cross jurisdictional borders (LLM API calls, webhook
  deliveries, cloud storage, and external REST adapters).
* **Transfer-check function** – ``check_transfer_permitted`` evaluates whether a
  proposed transfer is allowed under the active ``CrossBorderPolicy`` and returns
  the applicable ``TransferMechanism`` together with any required supplementary
  measures.
* **Transfer logging** – ``log_transfer`` persists an audit entry for each
  cross-border data-flow event to the ``cross_border_transfer_log`` DB table.

Transfer mechanisms documented here:

==================== =====================================================
Mechanism            Legal basis (reference)
==================== =====================================================
SCC                  GDPR Art. 46(2)(c) – Standard Contractual Clauses
ADEQUACY             GDPR Art. 45 – EC adequacy decision
EXPLICIT_CONSENT     GDPR Art. 49(1)(a) – claimant's explicit consent
BCR                  GDPR Art. 47 – Binding Corporate Rules
LEGITIMATE           GDPR Art. 6 / domestic US or employment/insurance
NONE                 No mechanism documented (non-compliant)
==================== =====================================================

Usage::

    from claim_agent.privacy.cross_border import (
        classify_jurisdiction,
        check_transfer_permitted,
        get_known_data_flows,
        log_transfer,
        JurisdictionZone,
        TransferMechanism,
        TransferPolicy,
    )

    # Classify a claim's loss state
    zone = classify_jurisdiction("California")   # -> JurisdictionZone.US

    # Check before sending EU claimant data to an LLM provider
    result = check_transfer_permitted(
        source_jurisdiction="Germany",
        destination_provider="openai",
        data_categories=["claim_data", "personal_data"],
    )
    if result["policy_decision"] == "block":
        raise RuntimeError("Cross-border transfer blocked by policy")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Jurisdiction zones
# ---------------------------------------------------------------------------

class JurisdictionZone(str, Enum):
    """Top-level privacy jurisdiction zones."""

    EU_EEA = "eu_eea"
    """EU/EEA member states – GDPR applies."""

    US = "us"
    """United States – CCPA, state privacy laws, HIPAA where applicable."""

    ADEQUATE = "adequate"
    """Third countries with an EC adequacy decision: UK, CH, JP, CA, NZ, IL, UY, AR, KR."""

    OTHER = "other"
    """All other third countries – no adequacy; GDPR Art. 44 restrictions apply."""


# EU/EEA member states (ISO 3166-1 alpha-2)
_EU_EEA_CODES: frozenset[str] = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HR", "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT",
    "NL", "NO", "PL", "PT", "RO", "SE", "SI", "SK",
})

# EU member state full names (lower-cased for lookup)
_EU_EEA_NAMES: frozenset[str] = frozenset({
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia",
    "czech republic", "denmark", "estonia", "finland", "france", "germany",
    "greece", "hungary", "iceland", "ireland", "italy", "latvia",
    "liechtenstein", "lithuania", "luxembourg", "malta", "netherlands",
    "norway", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden",
})

# Countries with EC adequacy decisions (Art. 45) – includes post-Brexit UK (2021)
_ADEQUATE_CODES: frozenset[str] = frozenset({
    "GB", "CH", "JP", "CA", "NZ", "IL", "UY", "AR", "KR",
})
_ADEQUATE_NAMES: frozenset[str] = frozenset({
    "united kingdom", "uk", "britain", "switzerland", "japan", "canada",
    "new zealand", "israel", "uruguay", "argentina", "south korea", "korea",
})

# US state codes and common aliases
_US_STATE_CODES: frozenset[str] = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC",
})
_US_STATE_NAMES: frozenset[str] = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
    "united states", "usa", "us",
})


def classify_jurisdiction(location: str) -> JurisdictionZone:
    """Return the ``JurisdictionZone`` for a country, state, or region string.

    Accepts ISO codes, full country names, or US state names (case-insensitive).

    Args:
        location: A country name, ISO 3166-1 alpha-2 code, or US state name.

    Returns:
        The matching ``JurisdictionZone``.  Returns ``OTHER`` for unknown locations.

    Examples::

        classify_jurisdiction("California")   # JurisdictionZone.US
        classify_jurisdiction("DE")           # JurisdictionZone.EU_EEA
        classify_jurisdiction("Germany")      # JurisdictionZone.EU_EEA
        classify_jurisdiction("UK")           # JurisdictionZone.ADEQUATE
        classify_jurisdiction("Brazil")       # JurisdictionZone.OTHER
    """
    if not location:
        return JurisdictionZone.OTHER

    raw = location.strip()
    upper = raw.upper()
    lower = raw.lower()

    # Deployment region shorthand (matches DATA_REGION=eu in settings)
    if lower in ("eu", "eea", "europe"):
        return JurisdictionZone.EU_EEA

    # US state code (2-letter)
    if upper in _US_STATE_CODES:
        return JurisdictionZone.US

    # US state full name
    if lower in _US_STATE_NAMES:
        return JurisdictionZone.US

    # EU/EEA ISO code
    if upper in _EU_EEA_CODES:
        return JurisdictionZone.EU_EEA

    # EU/EEA full name
    if lower in _EU_EEA_NAMES:
        return JurisdictionZone.EU_EEA

    # Adequacy ISO code
    if upper in _ADEQUATE_CODES:
        return JurisdictionZone.ADEQUATE

    # Adequacy full name
    if lower in _ADEQUATE_NAMES:
        return JurisdictionZone.ADEQUATE

    return JurisdictionZone.OTHER


# ---------------------------------------------------------------------------
# Transfer mechanisms
# ---------------------------------------------------------------------------

class TransferMechanism(str, Enum):
    """Legal mechanisms authorizing a cross-border data transfer."""

    SCC = "scc"
    """Standard Contractual Clauses – GDPR Art. 46(2)(c)."""

    ADEQUACY = "adequacy_decision"
    """EC adequacy decision for the destination country – GDPR Art. 45."""

    EXPLICIT_CONSENT = "explicit_consent"
    """Claimant's explicit consent to the specific transfer – GDPR Art. 49(1)(a)."""

    BCR = "bcr"
    """Binding Corporate Rules approved by a supervisory authority – GDPR Art. 47."""

    LEGITIMATE = "legitimate_interests"
    """Necessary for the performance of the insurance contract / legitimate interests."""

    NONE = "none"
    """No mechanism documented – non-compliant transfer."""


# ---------------------------------------------------------------------------
# Transfer policy
# ---------------------------------------------------------------------------

class TransferPolicy(str, Enum):
    """System-level policy controlling cross-border transfers."""

    ALLOW = "allow"
    """Permit all transfers; log for audit trail."""

    AUDIT = "audit"
    """Permit transfers but emit warnings and log for review."""

    RESTRICT = "restrict"
    """Block any transfer that lacks a documented safeguard mechanism."""


# ---------------------------------------------------------------------------
# Data flow catalog
# ---------------------------------------------------------------------------

@dataclass
class DataFlow:
    """Describes a single data flow that may cross jurisdictional borders."""

    name: str
    """Short identifier for the flow, e.g. ``llm_api``."""

    description: str
    """Human-readable description of what data is transferred and why."""

    source_zone: JurisdictionZone
    """Where the data originates."""

    destination: str
    """Provider or system receiving the data."""

    destination_zone: JurisdictionZone
    """Jurisdiction zone of the destination."""

    data_categories: list[str]
    """Categories of personal data included (e.g. ``claim_data``, ``pii``)."""

    purpose: str
    """Processing purpose."""

    mechanism: TransferMechanism
    """Legal mechanism authorising the transfer."""

    legal_basis: str
    """Reference to the specific clause, agreement, or adequacy decision."""

    supplementary_measures: list[str] = field(default_factory=list)
    """Technical/organisational supplementary measures applied."""

    subprocessor: str | None = None
    """Name of the DPA-registered subprocessor, if applicable."""

    notes: str = ""
    """Additional compliance notes."""

    @property
    def is_cross_border(self) -> bool:
        """True when the transfer crosses jurisdiction zones."""
        return self.source_zone != self.destination_zone

    @property
    def requires_safeguard(self) -> bool:
        """True when the source is EU/EEA and the destination lacks adequacy."""
        return (
            self.source_zone == JurisdictionZone.EU_EEA
            and self.destination_zone
            not in (JurisdictionZone.EU_EEA, JurisdictionZone.ADEQUATE)
        )


# ---------------------------------------------------------------------------
# Known data flows in this system
# ---------------------------------------------------------------------------

#: The authoritative catalog of cross-border data flows in the claims system.
#: Each entry documents a category of data transfer that may move personal data
#: across jurisdictional lines.  Update this list whenever a new integration is
#: added or an existing one changes.
KNOWN_DATA_FLOWS: list[DataFlow] = [
    DataFlow(
        name="llm_api",
        description=(
            "Claim details (incident description, damage description, estimated damage) "
            "and minimized party context are sent to the LLM provider API for routing, "
            "risk assessment, and decision generation.  PII is minimized via the "
            "llm_data_minimization allowlist before transmission."
        ),
        source_zone=JurisdictionZone.US,
        destination="OpenAI / OpenRouter (configurable)",
        destination_zone=JurisdictionZone.US,
        data_categories=["claim_data", "incident_description", "damage_description"],
        purpose="Automated claims processing and risk assessment",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis=(
            "Necessary for the performance of the insurance contract "
            "(GDPR Art. 6(1)(b)); CCPA Business Purpose exception"
        ),
        supplementary_measures=[
            "PII minimization before LLM prompt (llm_data_minimization allowlist)",
            "No claimant name, email, or phone sent in LLM prompts",
            "OpenAI Data Processing Addendum (DPA) in place",
        ],
        subprocessor="OpenAI",
        notes=(
            "When claim source_zone is EU_EEA and provider is US-based, this "
            "becomes an EU→US transfer requiring SCCs.  Set "
            "LLM_TRANSFER_MECHANISM=scc in .env to document the SCC basis."
        ),
    ),
    DataFlow(
        name="llm_api_eu_to_us",
        description=(
            "Same LLM API call as 'llm_api' but specifically documenting the EU/EEA→US "
            "transfer path when a claimant is based in the EU (e.g., cross-border claim, "
            "EU policyholder).  Requires SCCs or explicit consent."
        ),
        source_zone=JurisdictionZone.EU_EEA,
        destination="OpenAI / OpenRouter (US servers)",
        destination_zone=JurisdictionZone.US,
        data_categories=["claim_data", "incident_description", "damage_description"],
        purpose="Automated claims processing and risk assessment",
        mechanism=TransferMechanism.SCC,
        legal_basis=(
            "GDPR Art. 46(2)(c) – Standard Contractual Clauses (EC 2021/914); "
            "OpenAI DPA with Module 2 (controller-to-processor) SCCs"
        ),
        supplementary_measures=[
            "PII minimization before LLM prompt (llm_data_minimization allowlist)",
            "Data encrypted in transit (TLS 1.2+)",
            "OpenAI DPA / SCCs executed",
            "Transfer impact assessment documented",
        ],
        subprocessor="OpenAI",
        notes="Activate this flow when DATA_REGION=eu or claim loss_state is EU.",
    ),
    DataFlow(
        name="webhook_delivery",
        description=(
            "Claim status-change events are delivered to operator-configured webhook URLs. "
            "Payloads include claim_id, status, timestamps, and summary fields.  "
            "The destination URL and jurisdiction are operator-controlled."
        ),
        source_zone=JurisdictionZone.US,
        destination="Operator-configured webhook endpoint",
        destination_zone=JurisdictionZone.OTHER,
        data_categories=["claim_id", "claim_status", "event_metadata"],
        purpose="Real-time claim event notifications to integrated systems",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis=(
            "Operator DPA / data sharing agreement with webhook recipient; "
            "necessary for contract performance (GDPR Art. 6(1)(b))"
        ),
        supplementary_measures=[
            "HMAC-SHA256 payload signing (WEBHOOK_SECRET)",
            "TLS-only delivery",
            "Minimal payload – no claimant PII beyond claim_id",
        ],
        notes=(
            "When webhook destination is in a third country, operator must ensure "
            "an appropriate transfer mechanism (SCC, adequacy, or consent) is in place."
        ),
    ),
    DataFlow(
        name="cloud_storage_attachments",
        description=(
            "Claim attachments (photos, documents, PDFs) are uploaded to cloud storage "
            "(S3 or local).  When an S3 bucket in a non-EU region is used, this "
            "constitutes a cross-border transfer."
        ),
        source_zone=JurisdictionZone.US,
        destination="AWS S3 (region-dependent) / local filesystem",
        destination_zone=JurisdictionZone.US,
        data_categories=["claim_documents", "photos", "medical_records"],
        purpose="Claim document storage and retrieval",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis=(
            "AWS DPA and SCCs for EU→US transfers; "
            "AWS Privacy Shield successor arrangement"
        ),
        supplementary_measures=[
            "Server-side encryption at rest (AES-256)",
            "TLS in transit",
            "Access control via IAM / signed URLs",
        ],
        subprocessor="Amazon Web Services",
        notes=(
            "Configure S3_BUCKET_REGION to an EU region (e.g., eu-west-1) when "
            "processing EU claimant data to avoid cross-border transfer."
        ),
    ),
    DataFlow(
        name="policy_adapter_rest",
        description=(
            "Claim policy details are retrieved from the external policy REST API. "
            "Request includes policy_number; response may include policyholder details."
        ),
        source_zone=JurisdictionZone.US,
        destination="External Policy REST API (POLICY_REST_BASE_URL)",
        destination_zone=JurisdictionZone.US,
        data_categories=["policy_number", "policyholder_data", "coverage_details"],
        purpose="Policy coverage verification",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis="Necessary for insurance contract performance (GDPR Art. 6(1)(b))",
        supplementary_measures=["TLS in transit", "API key authentication"],
        notes="Destination zone depends on operator's policy system location.",
    ),
    DataFlow(
        name="valuation_adapter_rest",
        description=(
            "Vehicle identification and damage details (VIN, year, make, model) are sent "
            "to external valuation providers (CCC, Mitchell, Audatex) for ACV calculation."
        ),
        source_zone=JurisdictionZone.US,
        destination="CCC / Mitchell / Audatex valuation API",
        destination_zone=JurisdictionZone.US,
        data_categories=["vin", "vehicle_details", "damage_description"],
        purpose="Actual cash value determination for total-loss and partial-loss claims",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis="Insurance contract performance; industry standard subprocessor DPAs",
        supplementary_measures=["TLS in transit", "VIN-only (no claimant name)"],
        notes="Valuation providers are US-based; no EU PII transferred.",
    ),
    DataFlow(
        name="fraud_reporting_adapter",
        description=(
            "Fraud indicator summaries and SIU referral data are transmitted to the "
            "configured fraud reporting adapter (NICB, ISO ClaimSearch, state bureaus)."
        ),
        source_zone=JurisdictionZone.US,
        destination="NICB / ISO ClaimSearch / State Bureau",
        destination_zone=JurisdictionZone.US,
        data_categories=["claim_id", "vin", "fraud_indicators", "siu_case_data"],
        purpose="Insurance fraud prevention and mandatory regulatory reporting",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis=(
            "Mandatory regulatory reporting (state insurance codes); "
            "legitimate interests in fraud prevention"
        ),
        supplementary_measures=["TLS in transit", "Minimal data – no medical records"],
        notes="Regulatory obligation; may override consent-based restrictions.",
    ),
    DataFlow(
        name="notification_email_sms",
        description=(
            "Claimant notifications (FNOL confirmations, status updates) are sent via "
            "SendGrid (email) and Twilio (SMS) when NOTIFICATION_*_ENABLED=true."
        ),
        source_zone=JurisdictionZone.US,
        destination="SendGrid (email) / Twilio (SMS)",
        destination_zone=JurisdictionZone.US,
        data_categories=["claimant_email", "claimant_phone", "claim_status"],
        purpose="Claimant communication and claim status notification",
        mechanism=TransferMechanism.LEGITIMATE,
        legal_basis=(
            "Consent (notification opt-in); contract performance; "
            "SendGrid/Twilio DPAs and SCCs for EU→US transfers"
        ),
        supplementary_measures=[
            "Claimant consent captured at policy issuance",
            "SendGrid / Twilio DPA with SCCs for EU transfers",
            "TLS in transit",
        ],
        subprocessor="SendGrid / Twilio",
    ),
]


def get_known_data_flows(*, cross_border_only: bool = False) -> list[dict[str, Any]]:
    """Return the catalog of known data flows as serializable dicts.

    Args:
        cross_border_only: When ``True``, only return flows where
            ``source_zone != destination_zone``.

    Returns:
        List of dicts, each describing a ``DataFlow``.
    """
    flows = KNOWN_DATA_FLOWS
    if cross_border_only:
        flows = [f for f in flows if f.is_cross_border]

    return [
        {
            "name": f.name,
            "description": f.description,
            "source_zone": f.source_zone.value,
            "destination": f.destination,
            "destination_zone": f.destination_zone.value,
            "data_categories": f.data_categories,
            "purpose": f.purpose,
            "mechanism": f.mechanism.value,
            "legal_basis": f.legal_basis,
            "supplementary_measures": f.supplementary_measures,
            "subprocessor": f.subprocessor,
            "notes": f.notes,
            "is_cross_border": f.is_cross_border,
            "requires_safeguard": f.requires_safeguard,
        }
        for f in flows
    ]


# ---------------------------------------------------------------------------
# Transfer check
# ---------------------------------------------------------------------------

def check_transfer_permitted(
    source_jurisdiction: str,
    destination_provider: str,
    data_categories: list[str],
    *,
    mechanism: TransferMechanism | str | None = None,
) -> dict[str, Any]:
    """Evaluate whether a data transfer is permitted under the active policy.

    The function looks up the configured ``CrossBorderPolicy`` (from
    ``CROSS_BORDER_POLICY`` env var via ``PrivacyConfig``) and the configured
    ``LLM_TRANSFER_MECHANISM`` to determine the result.

    Args:
        source_jurisdiction: Where the personal data originates (state/country).
        destination_provider: Name of the receiving provider or service.
        data_categories: Categories of personal data in the transfer.
        mechanism: Override the configured mechanism; uses
            ``settings.privacy.llm_transfer_mechanism`` when ``None``.

    Returns:
        A dict with keys:

        * ``permitted`` (bool) – True when the transfer is allowed.
        * ``policy_decision`` (str) – ``"allow"``, ``"audit"``, or ``"block"``.
        * ``source_zone`` (str) – Classified jurisdiction zone of the source.
        * ``destination_zone`` (str) – Jurisdiction zone of the destination.
        * ``is_cross_border`` (bool) – Whether zones differ.
        * ``requires_safeguard`` (bool) – Whether a GDPR Art. 44 safeguard is needed.
        * ``mechanism`` (str) – Transfer mechanism code.
        * ``warnings`` (list[str]) – Any warnings the caller should surface.
    """
    from claim_agent.config import get_settings

    settings = get_settings()
    privacy = settings.privacy

    source_zone = classify_jurisdiction(source_jurisdiction)
    # Map known providers to their zones
    dest_zone = _classify_provider_zone(destination_provider)

    is_cross_border = source_zone != dest_zone
    requires_safeguard = (
        source_zone == JurisdictionZone.EU_EEA
        and dest_zone not in (JurisdictionZone.EU_EEA, JurisdictionZone.ADEQUATE)
    )

    # Resolve mechanism
    if mechanism is None:
        mechanism = getattr(privacy, "llm_transfer_mechanism", TransferMechanism.SCC.value)
    if isinstance(mechanism, str):
        try:
            mechanism = TransferMechanism(mechanism)
        except ValueError:
            mechanism = TransferMechanism.NONE

    policy = getattr(privacy, "cross_border_policy", TransferPolicy.AUDIT.value)
    if isinstance(policy, str):
        try:
            policy = TransferPolicy(policy)
        except ValueError:
            policy = TransferPolicy.AUDIT

    warnings: list[str] = []
    permitted = True
    decision = "allow"

    if is_cross_border:
        if requires_safeguard and mechanism == TransferMechanism.NONE:
            warnings.append(
                f"EU/EEA data destined for {destination_provider} (zone={dest_zone.value}) "
                "has no documented transfer mechanism. Set LLM_TRANSFER_MECHANISM."
            )
            if policy == TransferPolicy.RESTRICT:
                permitted = False
                decision = "block"
            else:
                decision = "audit"
        elif requires_safeguard:
            warnings.append(
                f"EU/EEA→{dest_zone.value} transfer uses mechanism={mechanism.value}. "
                "Ensure DPA/SCCs are executed and a transfer impact assessment is on file."
            )
            if policy == TransferPolicy.AUDIT:
                decision = "audit"
        elif policy == TransferPolicy.AUDIT and is_cross_border:
            decision = "audit"

    for w in warnings:
        logger.warning("cross_border: %s", w)

    return {
        "permitted": permitted,
        "policy_decision": decision,
        "source_zone": source_zone.value,
        "destination_zone": dest_zone.value,
        "is_cross_border": is_cross_border,
        "requires_safeguard": requires_safeguard,
        "mechanism": mechanism.value if isinstance(mechanism, TransferMechanism) else str(mechanism),
        "warnings": warnings,
    }


def _classify_provider_zone(provider_name: str) -> JurisdictionZone:
    """Map a provider name to its primary data-processing jurisdiction zone.

    Returns ``US`` for known US-based providers, ``EU_EEA`` for EU providers,
    ``ADEQUATE`` for providers based in countries with an EC adequacy decision
    (UK, Switzerland, Japan, Canada, etc.), and ``OTHER`` for unknowns.
    """
    lower = (provider_name or "").lower()
    _us_providers = {
        "openai", "openrouter", "azure openai", "azure", "aws", "amazon",
        "sendgrid", "twilio", "nicb", "ccc", "mitchell", "audatex",
    }
    _eu_providers: set[str] = set()  # add EU-based providers as needed
    # Hints indicating an adequate-country provider (UK, CH, JP, CA, NZ, IL, KR…)
    _adequate_hints = {
        "uk", "united kingdom", "britain", "swiss", "switzerland",
        "japan", "canadian", "canada", "new zealand", "israel", "korean", "korea",
    }
    for p in _us_providers:
        if p in lower:
            return JurisdictionZone.US
    for p in _eu_providers:
        if p in lower:
            return JurisdictionZone.EU_EEA
    for hint in _adequate_hints:
        if hint in lower:
            return JurisdictionZone.ADEQUATE
    return JurisdictionZone.OTHER


# ---------------------------------------------------------------------------
# Transfer logging
# ---------------------------------------------------------------------------

def log_transfer(
    flow_name: str,
    source_zone: str,
    destination: str,
    destination_zone: str,
    data_categories: list[str],
    mechanism: str,
    *,
    claim_id: str | None = None,
    permitted: bool = True,
    policy_decision: str = "allow",
    notes: str = "",
    db_path: str | None = None,
) -> int:
    """Persist a cross-border transfer audit entry to the database.

    Writes to the ``cross_border_transfer_log`` table.  Silently skips logging
    when the database is unavailable (to avoid blocking the primary workflow).

    Args:
        flow_name: Identifier for the data flow (e.g. ``"llm_api"``).
        source_zone: Jurisdiction zone of the data source.
        destination: Name of the receiving provider or system.
        destination_zone: Jurisdiction zone of the destination.
        data_categories: List of personal data categories transferred.
        mechanism: Transfer mechanism code (e.g. ``"scc"``).
        claim_id: Associated claim ID, if applicable.
        permitted: Whether the transfer was permitted.
        policy_decision: ``"allow"``, ``"audit"``, or ``"block"``.
        notes: Additional notes.
        db_path: Optional DB path override (uses default when ``None``).

    Returns:
        The row ID of the inserted log entry, or ``-1`` on failure.
    """
    try:
        from sqlalchemy import text

        from claim_agent.db.database import get_connection, get_db_path

        path = db_path or get_db_path()
        with get_connection(path) as conn:
            result = conn.execute(
                text("""
                    INSERT INTO cross_border_transfer_log (
                        claim_id, flow_name, source_zone, destination,
                        destination_zone, data_categories, mechanism,
                        permitted, policy_decision, notes
                    ) VALUES (
                        :claim_id, :flow_name, :source_zone, :destination,
                        :destination_zone, :data_categories, :mechanism,
                        :permitted, :policy_decision, :notes
                    )
                """),
                {
                    "claim_id": claim_id,
                    "flow_name": flow_name,
                    "source_zone": source_zone,
                    "destination": destination,
                    "destination_zone": destination_zone,
                    "data_categories": json.dumps(data_categories),
                    "mechanism": mechanism,
                    "permitted": 1 if permitted else 0,
                    "policy_decision": policy_decision,
                    "notes": notes,
                },
            )
            return result.lastrowid or -1
    except Exception as exc:  # pragma: no cover
        logger.warning("cross_border: failed to log transfer: %s", exc)
        return -1


def list_transfer_log(
    *,
    claim_id: str | None = None,
    flow_name: str | None = None,
    policy_decision: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List cross-border transfer log entries with optional filters.

    Returns:
        Tuple of ``(items, total_count)``.
    """
    from sqlalchemy import text

    from claim_agent.db.database import get_connection, get_db_path, row_to_dict

    path = db_path or get_db_path()
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    if claim_id:
        where += " AND claim_id = :claim_id"
        params["claim_id"] = claim_id
    if flow_name:
        where += " AND flow_name = :flow_name"
        params["flow_name"] = flow_name
    if policy_decision:
        where += " AND policy_decision = :policy_decision"
        params["policy_decision"] = policy_decision

    with get_connection(path) as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) FROM cross_border_transfer_log {where}"), params
        ).fetchone()
        total = count_row[0] if count_row and hasattr(count_row, "__getitem__") else 0

        params["limit"] = limit
        params["offset"] = offset
        rows = conn.execute(
            text(
                f"SELECT * FROM cross_border_transfer_log {where} "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        items = []
        for r in rows:
            d = row_to_dict(r)
            # Deserialise JSON array stored as TEXT
            if isinstance(d.get("data_categories"), str):
                try:
                    d["data_categories"] = json.loads(d["data_categories"])
                except (json.JSONDecodeError, TypeError):
                    pass
            items.append(d)
        return items, total


# ---------------------------------------------------------------------------
# Convenience: check and log LLM transfer from claim data
# ---------------------------------------------------------------------------

def check_and_log_llm_transfer(
    claim_data: dict[str, Any],
    *,
    claim_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Check whether sending ``claim_data`` to the LLM is permitted and log the event.

    Derives the source jurisdiction from ``claim_data["loss_state"]`` (falls
    back to the configured ``DATA_REGION``).  Uses the configured LLM provider
    name (from ``OPENAI_API_BASE``) to determine the destination zone.

    When ``CROSS_BORDER_POLICY=restrict`` and the transfer is not permitted,
    raises ``PermissionError`` so the caller can abort the LLM call.

    Args:
        claim_data: Full or minimized claim dict containing at least ``loss_state``.
        claim_id: Override claim ID for the log entry (uses ``claim_data["claim_id"]``
            when ``None``).
        db_path: Optional DB path override.

    Returns:
        The result dict from :func:`check_transfer_permitted`.

    Raises:
        PermissionError: When the active policy is ``restrict`` and the transfer
            lacks a documented mechanism.
    """
    from claim_agent.config import get_settings

    settings = get_settings()
    privacy = settings.privacy

    # Determine source jurisdiction
    loss_state: str = (claim_data or {}).get("loss_state") or ""
    source_jurisdiction = loss_state or getattr(privacy, "data_region", "us")

    # Determine LLM provider from config
    llm_base: str = (settings.llm.api_base or "").strip()
    if "openrouter" in llm_base.lower():
        provider = "OpenRouter"
    else:
        provider = "OpenAI"

    data_categories = ["claim_data", "incident_description", "damage_description"]

    result = check_transfer_permitted(
        source_jurisdiction=source_jurisdiction,
        destination_provider=provider,
        data_categories=data_categories,
    )

    # Log the transfer (non-blocking – failures are swallowed by log_transfer)
    _cid = claim_id or (claim_data or {}).get("claim_id")
    flow = "llm_api_eu_to_us" if result.get("source_zone") == JurisdictionZone.EU_EEA.value else "llm_api"
    log_transfer(
        flow_name=flow,
        source_zone=result["source_zone"],
        destination=provider,
        destination_zone=result["destination_zone"],
        data_categories=data_categories,
        mechanism=result["mechanism"],
        claim_id=str(_cid) if _cid else None,
        permitted=result["permitted"],
        policy_decision=result["policy_decision"],
        notes="; ".join(result.get("warnings", [])),
        db_path=db_path,
    )

    if not result["permitted"]:
        raise PermissionError(
            f"Cross-border data transfer blocked by policy ({privacy.cross_border_policy}): "
            f"{source_jurisdiction} → {provider}. "
            "Set LLM_TRANSFER_MECHANISM to a valid mechanism or change CROSS_BORDER_POLICY."
        )

    return result
