"""Document and report generation logic."""

import json
import logging
import uuid

logger = logging.getLogger(__name__)


def generate_report_impl(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    report = {
        "report_id": str(uuid.uuid4()),
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": status,
        "summary": summary,
        "payout_amount": payout_amount,
    }
    return json.dumps(report)


def generate_report_pdf_impl(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    """Generate a PDF report from claim data. Requires reportlab (pip install claim-agent[pdf])."""
    from pathlib import Path

    from claim_agent.config import get_settings

    result = {"pdf_path": None, "error": None}
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from xml.sax.saxutils import escape

        def _escape_field(value: object) -> str:
            return escape(str(value)) if value is not None else ""

        out_dir = Path(get_settings().paths.attachment_storage_path).parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_claim_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(claim_id))
        pdf_path = out_dir / f"report_{safe_claim_id}_{uuid.uuid4().hex[:6]}.pdf"

        escaped_claim_id = _escape_field(claim_id)
        escaped_claim_type = _escape_field(claim_type)
        escaped_status = _escape_field(status)
        safe_summary = escape(summary or "").replace("\n", "<br/>")

        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, rightMargin=inch, leftMargin=inch)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("Claim Report", styles["Title"]))
        story.append(Spacer(1, 0.25 * inch))
        story.append(Paragraph(f"<b>Claim ID:</b> {escaped_claim_id}", styles["Normal"]))
        story.append(Paragraph(f"<b>Type:</b> {escaped_claim_type}", styles["Normal"]))
        story.append(Paragraph(f"<b>Status:</b> {escaped_status}", styles["Normal"]))
        if payout_amount is not None:
            story.append(Paragraph(f"<b>Payout:</b> ${payout_amount:,.2f}", styles["Normal"]))
        story.append(Spacer(1, 0.25 * inch))
        story.append(Paragraph("<b>Summary</b>", styles["Heading2"]))
        story.append(Paragraph(safe_summary, styles["Normal"]))
        doc.build(story)
        result["pdf_path"] = str(pdf_path.resolve())
    except ImportError:
        result["error"] = "reportlab required. Install with: pip install claim-agent[pdf]"
    except Exception as e:
        logger.warning("PDF generation failed: %s", e, exc_info=True)
        result["error"] = str(e)
    return json.dumps(result)


def generate_claim_id_impl(prefix: str = "CLM") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
