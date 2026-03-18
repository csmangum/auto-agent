"""State-specific fraud reporting templates for Department of Insurance filings.

Provides structured templates per state for mandatory fraud bureau reporting
(CA CDI, TX DFR, FL DIFS, NY FBU, GA DOI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claim_agent.rag.constants import normalize_state


@dataclass
class FraudReportTemplate:
    """State-specific fraud report form template."""

    state: str
    form_id: str
    form_name: str
    required_fields: tuple[str, ...]
    filing_deadline_days: int
    bureau_name: str
    bureau_url: str | None = None


_TEMPLATES: dict[str, FraudReportTemplate] = {
    "California": FraudReportTemplate(
        state="California",
        form_id="CA-CDI-DFR-1",
        form_name="California Department of Insurance Fraud Referral",
        required_fields=(
            "claim_id",
            "policy_number",
            "vin",
            "indicators_summary",
            "incident_date",
            "claimant_name",
            "estimated_loss",
        ),
        filing_deadline_days=30,
        bureau_name="California Department of Insurance Fraud Division",
        bureau_url="https://www.insurance.ca.gov/",
    ),
    "Florida": FraudReportTemplate(
        state="Florida",
        form_id="FL-DIFS-FR-1",
        form_name="Florida Division of Insurance Fraud Referral",
        required_fields=(
            "claim_id",
            "policy_number",
            "vin",
            "indicators_summary",
            "incident_date",
            "claimant_name",
        ),
        filing_deadline_days=30,
        bureau_name="Florida Division of Insurance Fraud",
        bureau_url="https://www.myfloridacfo.com/division/df/",
    ),
    "New York": FraudReportTemplate(
        state="New York",
        form_id="NY-FBU-FR-1",
        form_name="New York Insurance Fraud Bureau Referral",
        required_fields=(
            "claim_id",
            "policy_number",
            "vin",
            "indicators_summary",
            "incident_date",
        ),
        filing_deadline_days=21,
        bureau_name="New York Insurance Fraud Bureau",
        bureau_url="https://www.dfs.ny.gov/",
    ),
    "Texas": FraudReportTemplate(
        state="Texas",
        form_id="TX-DFR-FR-1",
        form_name="Texas Department of Insurance Fraud Referral",
        required_fields=(
            "claim_id",
            "policy_number",
            "vin",
            "indicators_summary",
            "incident_date",
            "claimant_name",
        ),
        filing_deadline_days=30,
        bureau_name="Texas Department of Insurance Fraud Unit",
        bureau_url="https://www.tdi.texas.gov/",
    ),
    "Georgia": FraudReportTemplate(
        state="Georgia",
        form_id="GA-DOI-FR-1",
        form_name="Georgia Department of Insurance Fraud Referral",
        required_fields=(
            "claim_id",
            "policy_number",
            "vin",
            "indicators_summary",
            "incident_date",
        ),
        filing_deadline_days=30,
        bureau_name="Georgia Department of Insurance Fraud Unit",
        bureau_url="https://oci.georgia.gov/",
    ),
}


def get_fraud_report_template(state: str | None) -> dict[str, Any] | None:
    """Return fraud report template for the given state, or None if unsupported.

    Args:
        state: State jurisdiction (California, Texas, Florida, New York, Georgia).

    Returns:
        Dict with form_id, form_name, required_fields, filing_deadline_days,
        bureau_name, bureau_url, state. None if state unsupported.
    """
    if not state or not str(state).strip():
        return None
    try:
        normalized = normalize_state(str(state).strip())
    except ValueError:
        return None
    template = _TEMPLATES.get(normalized)
    if not template:
        return None
    return {
        "state": template.state,
        "form_id": template.form_id,
        "form_name": template.form_name,
        "required_fields": list(template.required_fields),
        "filing_deadline_days": template.filing_deadline_days,
        "bureau_name": template.bureau_name,
        "bureau_url": template.bureau_url,
    }
