"""SIU investigation tools for the Special Investigations Unit crew."""

from crewai.tools import tool

from claim_agent.tools.siu_logic import (
    add_siu_investigation_note_impl,
    check_claimant_investigation_history_impl,
    file_fraud_report_state_bureau_impl,
    file_nicb_report_impl,
    file_niss_report_impl,
    get_siu_case_details_impl,
    update_siu_case_status_impl,
    verify_document_authenticity_impl,
)


@tool("Get SIU Case Details")
def get_siu_case_details(case_id: str) -> str:
    """Retrieve SIU case details including indicators, status, and investigation notes.

    Args:
        case_id: The SIU case ID (e.g., SIU-MOCK-ABC12345).

    Returns:
        JSON with case_id, claim_id, indicators, status, notes.
    """
    return get_siu_case_details_impl(case_id)


@tool("Add SIU Investigation Note")
def add_siu_investigation_note(case_id: str, note: str, category: str = "general") -> str:
    """Add an investigation note to an SIU case.

    Categories: general, document_review, claimant_interview, records_check, findings.

    Args:
        case_id: The SIU case ID.
        note: The note content.
        category: Note category (default: general).

    Returns:
        JSON with success (bool), case_id, category.
    """
    return add_siu_investigation_note_impl(case_id, note, category)


@tool("Update SIU Case Status")
def update_siu_case_status(case_id: str, status: str) -> str:
    """Update SIU case status.

    Valid statuses: open, investigating, referred, closed.

    Args:
        case_id: The SIU case ID.
        status: New status.

    Returns:
        JSON with success (bool), case_id, status.
    """
    return update_siu_case_status_impl(case_id, status)


@tool("Verify Document Authenticity")
def verify_document_authenticity(
    document_type: str, claim_id: str, document_summary: str = ""
) -> str:
    """Verify document authenticity for SIU investigation.

    Document types: proof_of_loss, repair_estimate, id, title, registration, photos.

    Args:
        document_type: Type of document being verified.
        claim_id: The claim ID.
        document_summary: Brief description of document content (optional).

    Returns:
        JSON with verified (bool), confidence, findings, recommendation.
    """
    return verify_document_authenticity_impl(document_type, claim_id, document_summary)


@tool("Check Claimant Investigation History")
def check_claimant_investigation_history(
    claim_id: str, vin: str = "", policy_number: str = ""
) -> str:
    """Check claimant and vehicle history for prior fraud flags and SIU cases.

    Searches claims database for same VIN/policy to identify patterns.

    Args:
        claim_id: The claim ID.
        vin: Optional VIN to search (uses claim's VIN if omitted).
        policy_number: Optional policy number.

    Returns:
        JSON with prior_claims, prior_fraud_flags, prior_siu_cases, risk_summary.
    """
    return check_claimant_investigation_history_impl(claim_id, vin=vin, policy_number=policy_number)


@tool("File NICB Report")
def file_nicb_report(
    claim_id: str,
    case_id: str,
    report_type: str = "theft",
    indicators: str = "[]",
) -> str:
    """File a report with NICB (National Insurance Crime Bureau).

    Required for vehicle theft, salvage, and certain fraud referrals per state law.

    Args:
        claim_id: The claim ID.
        case_id: The SIU case ID.
        report_type: Type of report - theft, salvage, or fraud.
        indicators: JSON array of fraud indicators.

    Returns:
        JSON with success, report_id, message.
    """
    return file_nicb_report_impl(claim_id, case_id, report_type, indicators)


@tool("File NISS Report")
def file_niss_report(
    claim_id: str,
    case_id: str,
    report_type: str = "fraud",
    indicators: str = "[]",
) -> str:
    """File a report with NISS (National Insurance Special Investigation System).

    Required for certain fraud referrals and cross-carrier reporting.

    Args:
        claim_id: The claim ID.
        case_id: The SIU case ID.
        report_type: Type of report - fraud or referral.
        indicators: JSON array of fraud indicators.

    Returns:
        JSON with success, report_id, message.
    """
    return file_niss_report_impl(claim_id, case_id, report_type, indicators)


@tool("File Fraud Report State Bureau")
def file_fraud_report_state_bureau(
    claim_id: str,
    case_id: str,
    state: str = "California",
    indicators: str = "[]",
    payload_json: str = "{}",
) -> str:
    """File a fraud report with the state insurance fraud bureau.

    Required per state law (e.g., CA SIU reporting, TX DFR, FL DIFS, NY FBU) when
    fraud is confirmed or suspected.

    Args:
        claim_id: The claim ID.
        case_id: The SIU case ID.
        state: State jurisdiction (default: California).
        indicators: JSON array of fraud indicators.
        payload_json: Optional JSON object with state form fields; validated against
            state template required_fields before filing.

    Returns:
        JSON with success/report_id on success; structured validation error details
        on missing required fields.
    """
    return file_fraud_report_state_bureau_impl(claim_id, case_id, state, indicators, payload_json)
