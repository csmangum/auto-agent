"""Document and report generation tools."""

from crewai.tools import tool

from claim_agent.tools.document_logic import (
    classify_document_impl,
    extract_document_data_impl,
    generate_claim_id_impl,
    generate_report_impl,
    generate_report_pdf_impl,
)


@tool("Generate Claim Report")
def generate_report(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    """Generate a claim report/summary document.
    Args:
        claim_id: Assigned claim ID.
        claim_type: new, duplicate, or total_loss.
        status: Claim status (e.g., open, closed, duplicate).
        summary: Human-readable summary of actions and outcome.
        payout_amount: Optional settlement amount for total loss.
    Returns:
        JSON string with report_id, claim_id, status, summary, payout_amount.
    """
    return generate_report_impl(claim_id, claim_type, status, summary, payout_amount)


@tool("Generate Claim Report PDF")
def generate_report_pdf(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    """Generate a downloadable PDF report for a claim. Requires reportlab (pip install claim-agent[pdf]).

    Args:
        claim_id: Assigned claim ID.
        claim_type: new, duplicate, total_loss, etc.
        status: Claim status.
        summary: Human-readable summary.
        payout_amount: Optional settlement amount.
    Returns:
        JSON with pdf_path or error.
    """
    return generate_report_pdf_impl(claim_id, claim_type, status, summary, payout_amount)


@tool("Extract Document Data")
def extract_document_data(claim_id: str, document_id: int) -> str:
    """Extract structured data from a document (estimate, police report, medical record) via OCR.

    Updates the document's extracted_data field. Returns JSON with extracted_data.
    Args:
        claim_id: Claim ID the document belongs to.
        document_id: ID of the document in claim_documents.
    Returns:
        JSON with success, extracted_data, document.
    """
    return extract_document_data_impl(claim_id, document_id)


@tool("Classify Document")
def classify_document(claim_id: str, document_id: int) -> str:
    """Classify a claim document by type (police_report, estimate, medical_record, photo, pdf, other).

    Uses vision model for images; filename heuristics for other files. Updates the document record.
    Args:
        claim_id: Claim ID the document belongs to.
        document_id: ID of the document in claim_documents.
    Returns:
        JSON with success, document_type, received_from, document.
    """
    return classify_document_impl(claim_id, document_id)


@tool("Generate Claim ID")
def generate_claim_id(prefix: str = "CLM") -> str:
    """Generate a unique claim ID. Use prefix CLM for new claims.
    Args:
        prefix: Optional prefix (default CLM).
    Returns:
        Unique claim ID string.
    """
    return generate_claim_id_impl(prefix)
