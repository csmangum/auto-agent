"""State-specific DSAR (Data Subject Access Request) rules and form schemas.

Defines consumer rights, response timelines, required form fields, and data
categories for each supported state privacy law:
- California CCPA/CPRA (Cal. Civ. Code §§ 1798.100-1798.199.100)
- Virginia VCDPA (Va. Code Ann. §§ 59.1-571 to 59.1-585)
- Colorado CPA (Colo. Rev. Stat. §§ 6-1-1301 to 6-1-1313)
- Texas TDPSA (Tex. Bus. & Com. Code §§ 541.001-541.203)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DSARStateRules:
    """State-specific DSAR compliance rules."""

    state: str
    """Full state name (e.g., 'California')."""
    law_name: str
    """Name of the applicable privacy law (e.g., 'CCPA/CPRA')."""
    response_days: int
    """Calendar days from receipt to respond to a verified consumer request."""
    extension_days: int
    """Additional days allowed when a notice-of-extension is sent to the consumer."""
    consumer_rights: list[str]
    """Rights available to consumers under this state's law."""
    required_form_fields: list[str]
    """Minimum fields required on a DSAR submission form."""
    data_categories: list[str]
    """Categories of personal data that must be disclosed on access requests."""
    verification_methods: list[str]
    """Permitted identity-verification approaches for this state."""
    opt_out_mechanisms: list[str]
    """Opt-out channels the business must honour (e.g., 'web_form', 'global_opt_out_signal')."""
    annual_request_limit: int | None
    """Maximum free requests the consumer may submit per 12 months (None = unlimited)."""
    response_format_notes: str
    """Human-readable notes on required response format and timing."""
    notes: list[str] = field(default_factory=list)
    """Additional compliance notes specific to this state."""


# ---------------------------------------------------------------------------
# Pre-defined state DSAR rules
# ---------------------------------------------------------------------------

_DSAR_STATE_RULES: dict[str, DSARStateRules] = {
    "California": DSARStateRules(
        state="California",
        law_name="CCPA/CPRA",
        response_days=45,
        extension_days=45,
        consumer_rights=[
            "right_to_know",
            "right_to_delete",
            "right_to_correct",
            "right_to_opt_out_of_sale_or_sharing",
            "right_to_limit_sensitive_pi_use",
            "right_to_non_discrimination",
            "right_to_portability",
        ],
        required_form_fields=[
            "full_name",
            "email_address",
            "request_type",
            "description_of_request",
            "relationship_to_business",
        ],
        data_categories=[
            "identifiers",
            "customer_records",
            "protected_characteristics",
            "commercial_information",
            "biometric_information",
            "internet_or_network_activity",
            "geolocation_data",
            "sensory_data",
            "professional_or_employment_information",
            "education_information",
            "inferences",
            "sensitive_personal_information",
        ],
        verification_methods=[
            "email_verification",
            "account_login",
            "two_step_verification_for_sensitive_data",
            "signed_declaration_under_penalty_of_perjury",
        ],
        opt_out_mechanisms=[
            "do_not_sell_or_share_link",
            "limit_sensitive_pi_link",
            "global_privacy_control",
        ],
        annual_request_limit=2,
        response_format_notes=(
            "Respond within 45 days of receiving a verifiable consumer request. "
            "May extend by an additional 45 days (90 days total) by notifying the consumer "
            "within the initial 45-day window. Disclosure must cover the 12-month period "
            "preceding the request. Provide response free of charge (up to 2 per year)."
        ),
        notes=[
            "Sensitive personal information (SPI) requires separate disclosure and a "
            "'Limit the Use of My Sensitive Personal Information' link.",
            "Authorized agents may submit requests on behalf of consumers with written permission.",
            "Businesses must verify identity before fulfilling deletion or right-to-know requests.",
        ],
    ),
    "Virginia": DSARStateRules(
        state="Virginia",
        law_name="VCDPA",
        response_days=45,
        extension_days=45,
        consumer_rights=[
            "right_to_access",
            "right_to_correct",
            "right_to_delete",
            "right_to_portability",
            "right_to_opt_out_of_targeted_advertising",
            "right_to_opt_out_of_sale",
            "right_to_opt_out_of_profiling",
        ],
        required_form_fields=[
            "full_name",
            "email_address",
            "request_type",
            "description_of_request",
        ],
        data_categories=[
            "identifiers",
            "sensitive_data",
            "biometric_data",
            "health_data",
            "financial_data",
            "geolocation_data",
            "racial_or_ethnic_origin",
            "religious_beliefs",
        ],
        verification_methods=[
            "email_verification",
            "account_login",
            "reasonable_verification_proportional_to_risk",
        ],
        opt_out_mechanisms=[
            "opt_out_link",
            "global_opt_out_signal",
        ],
        annual_request_limit=None,
        response_format_notes=(
            "Respond within 45 days of receiving a consumer request. "
            "May extend by an additional 45 days (90 days total) with written notice "
            "provided within the initial 45-day period. "
            "Provide one free response per consumer per year; may charge a reasonable fee "
            "for subsequent requests."
        ),
        notes=[
            "Controller must establish an appeals process within 60 days for denied requests.",
            "Sensitive data processing requires opt-in consent.",
            "Profiling that produces legal or similarly significant effects requires opt-out capability.",
        ],
    ),
    "Colorado": DSARStateRules(
        state="Colorado",
        law_name="CPA",
        response_days=45,
        extension_days=45,
        consumer_rights=[
            "right_to_opt_out",
            "right_to_access",
            "right_to_correct",
            "right_to_delete",
            "right_to_portability",
        ],
        required_form_fields=[
            "full_name",
            "email_address",
            "request_type",
            "description_of_request",
        ],
        data_categories=[
            "identifiers",
            "sensitive_data",
            "biometric_data",
            "health_data",
            "financial_data",
            "geolocation_data",
            "racial_or_ethnic_origin",
            "religious_beliefs",
            "sexual_orientation",
            "citizenship_status",
        ],
        verification_methods=[
            "email_verification",
            "account_login",
            "reasonable_verification_proportional_to_sensitivity",
        ],
        opt_out_mechanisms=[
            "opt_out_link",
            "universal_opt_out_mechanism",
        ],
        annual_request_limit=None,
        response_format_notes=(
            "Respond within 45 days of receiving a consumer request. "
            "May extend by an additional 45 days (90 days total) with written notice "
            "within the initial 45-day period. "
            "One free response per consumer per year; subsequent requests may incur a fee."
        ),
        notes=[
            "Must honour Universal Opt-Out Mechanisms (e.g., Global Privacy Control) starting July 2024.",
            "Controller must establish an appeals process within 45 days for denied requests.",
            "Sensitive data requires opt-in consent; sensitive data includes data revealing a "
            "consumer's racial or ethnic origin, mental/physical health, sexual orientation, "
            "citizenship/immigration status, genetic/biometric data, financial data, and "
            "precise geolocation.",
        ],
    ),
    "Texas": DSARStateRules(
        state="Texas",
        law_name="TDPSA",
        response_days=45,
        extension_days=45,
        consumer_rights=[
            "right_to_access",
            "right_to_correct",
            "right_to_delete",
            "right_to_portability",
            "right_to_opt_out_of_targeted_advertising",
            "right_to_opt_out_of_sale",
            "right_to_opt_out_of_profiling",
        ],
        required_form_fields=[
            "full_name",
            "email_address",
            "request_type",
            "description_of_request",
        ],
        data_categories=[
            "identifiers",
            "sensitive_data",
            "biometric_data",
            "health_data",
            "financial_data",
            "geolocation_data",
            "racial_or_ethnic_origin",
            "religious_beliefs",
            "sexual_orientation",
            "citizenship_status",
        ],
        verification_methods=[
            "email_verification",
            "account_login",
            "reasonable_verification_proportional_to_risk",
        ],
        opt_out_mechanisms=[
            "opt_out_link",
            "global_opt_out_signal",
        ],
        annual_request_limit=None,
        response_format_notes=(
            "Respond within 45 days of receiving a consumer request. "
            "May extend by an additional 45 days (90 days total) with written notice "
            "within the initial 45-day period."
        ),
        notes=[
            "Effective July 1, 2024. Applies to controllers processing personal data of 100,000+ "
            "Texas consumers or 25,000+ consumers when deriving 25%+ revenue from selling personal data.",
            "Controller must establish an appeals process for denied requests.",
            "Sensitive data processing requires opt-in consent.",
        ],
    ),
}

# Abbreviation → canonical name mapping for DSAR-supported states.
# This is intentionally separate from the RAG module's normalize_state so that
# DSAR state support is independent of which states have RAG corpus data.
_DSAR_STATE_ABBREV: dict[str, str] = {
    "CA": "California",
    "VA": "Virginia",
    "CO": "Colorado",
    "TX": "Texas",
}


def _normalize_dsar_state(state: str) -> str | None:
    """Return the canonical state name for DSAR lookups, or None if unrecognised."""
    stripped = state.strip()
    upper = stripped.upper()
    if upper in _DSAR_STATE_ABBREV:
        return _DSAR_STATE_ABBREV[upper]
    title = stripped.title()
    return title if title in _DSAR_STATE_RULES else None


def get_dsar_state_rules(state: str | None) -> DSARStateRules | None:
    """Return DSAR-specific state rules, or None if the state is unsupported/unknown."""
    if not state or not str(state).strip():
        return None
    canonical = _normalize_dsar_state(str(state))
    return _DSAR_STATE_RULES.get(canonical) if canonical else None


def get_supported_dsar_states() -> list[str]:
    """Return a list of states with defined DSAR rules."""
    return list(_DSAR_STATE_RULES.keys())


def get_response_deadline_days(state: str | None) -> int:
    """Return the primary response deadline in days for a DSAR request.

    Returns 30 days for unknown/unsupported states as a conservative default.
    """
    rules = get_dsar_state_rules(state)
    return rules.response_days if rules else 30


def get_dsar_form_schema(state: str | None, request_type: str = "access") -> dict[str, Any]:
    """Return a form schema dict for the given state and request type.

    The schema describes the fields a consumer must complete when submitting a
    DSAR form. It is suitable for rendering a guided intake form or validating
    API input.

    Args:
        state: Loss/consumer state (e.g., ``"California"`` or ``"CA"``).  When
            ``None`` or unsupported, a generic schema is returned.
        request_type: ``"access"`` (right-to-know) or ``"deletion"`` (right-to-delete).

    Returns:
        Dict with keys ``state``, ``law_name``, ``request_type``,
        ``response_deadline_days``, ``extension_days``, ``consumer_rights``,
        ``required_fields``, ``data_categories``, ``opt_out_mechanisms``, and
        ``notes``.
    """
    rules = get_dsar_state_rules(state)

    if rules:
        return {
            "state": rules.state,
            "law_name": rules.law_name,
            "request_type": request_type,
            "response_deadline_days": rules.response_days,
            "extension_days": rules.extension_days,
            "consumer_rights": rules.consumer_rights,
            "required_fields": rules.required_form_fields,
            "data_categories": rules.data_categories,
            "verification_methods": rules.verification_methods,
            "opt_out_mechanisms": rules.opt_out_mechanisms,
            "annual_request_limit": rules.annual_request_limit,
            "response_format_notes": rules.response_format_notes,
            "notes": rules.notes,
        }

    # Generic/fallback schema for unsupported states
    return {
        "state": state,
        "law_name": "Generic Privacy Law",
        "request_type": request_type,
        "response_deadline_days": 30,
        "extension_days": 0,
        "consumer_rights": [
            "right_to_access",
            "right_to_delete",
        ],
        "required_fields": [
            "full_name",
            "email_address",
            "request_type",
            "description_of_request",
        ],
        "data_categories": [
            "identifiers",
            "personal_information",
        ],
        "verification_methods": [
            "email_verification",
        ],
        "opt_out_mechanisms": [],
        "annual_request_limit": None,
        "response_format_notes": (
            "Respond within 30 days of receiving the request. "
            "No state-specific extension is currently configured."
        ),
        "notes": [],
    }


def get_state_response_metadata(state: str | None) -> dict[str, Any]:
    """Return response-metadata dict to embed in a DSAR access export.

    Provides consumers with state-specific information about their rights and
    the response timeline.

    Args:
        state: Consumer's state of residence.

    Returns:
        Dict with ``state``, ``applicable_law``, ``response_deadline_days``,
        ``extension_days``, ``consumer_rights``, and ``response_format_notes``.
    """
    rules = get_dsar_state_rules(state)
    if rules:
        return {
            "state": rules.state,
            "applicable_law": rules.law_name,
            "response_deadline_days": rules.response_days,
            "extension_days": rules.extension_days,
            "consumer_rights": rules.consumer_rights,
            "response_format_notes": rules.response_format_notes,
        }
    return {
        "state": state,
        "applicable_law": None,
        "response_deadline_days": 30,
        "extension_days": 0,
        "consumer_rights": ["right_to_access", "right_to_delete"],
        "response_format_notes": "Respond within 30 days of receiving the request.",
    }
