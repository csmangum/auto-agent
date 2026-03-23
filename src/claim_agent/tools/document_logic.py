"""Document and report generation logic, plus document classification."""

import base64
import json
import logging
import re
import uuid
from pathlib import Path

from claim_agent.adapters import get_ocr_adapter
from claim_agent.config import get_settings
from claim_agent.config.settings import get_adapter_backend, get_mock_crew_config
from claim_agent.db.document_repository import DocumentRepository
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.utils.attachments import attachment_type_to_document_type, infer_attachment_type

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_OPTIONS = [
    "police_report",
    "estimate",
    "medical_record",
    "photo",
    "pdf",
    "rental_receipt",
    "rental_agreement",
    "other",
]

MAX_VISION_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


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
    from xml.sax.saxutils import escape

    from claim_agent.config import get_settings

    result: dict[str, str | None] = {"pdf_path": None, "error": None}
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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


def _use_mock_document_classification() -> bool:
    """Return True if mock classification should be used."""
    if get_adapter_backend("vision") == "mock":
        return True
    crew_cfg = get_mock_crew_config()
    return crew_cfg.get("enabled") is True


def _classify_document_mock(storage_key: str) -> tuple[str, str | None]:
    """Mock: infer from filename. Returns (document_type, received_from)."""
    atype = infer_attachment_type(storage_key)
    doc_type = attachment_type_to_document_type(atype).value
    lower = storage_key.lower()
    if "police" in lower or ("report" in lower and "incident" in lower):
        return ("police_report", "police")
    if "estimate" in lower or "repair" in lower:
        return ("estimate", "repair_shop")
    if "medical" in lower or "record" in lower or "bill" in lower:
        return ("medical_record", "provider")
    return (doc_type, "claimant")


def _classify_document_vision(file_path: Path, storage_key: str) -> tuple[str, str | None]:
    """Use vision model to classify document. Returns (document_type, received_from)."""
    try:
        import litellm
    except ImportError:
        return _classify_document_mock(storage_key)

    if not file_path.exists() or not file_path.is_file():
        return _classify_document_mock(storage_key)
    ext = file_path.suffix.lower().lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
        return _classify_document_mock(storage_key)
    file_size = file_path.stat().st_size
    if file_size > MAX_VISION_FILE_BYTES:
        return _classify_document_mock(storage_key)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}" if ext in ("png", "gif", "webp", "heic") else "image/jpeg"
    content = f"data:{mime};base64,{b64}"
    model = get_settings().llm.vision_model.strip() or "gpt-4o"
    prompt = """Classify this insurance claim document image. Return a JSON object with:
- document_type: one of police_report, estimate, medical_record, photo, pdf, rental_receipt, rental_agreement, other
- received_from: optional source (claimant, police, repair_shop, provider, etc.) or null if unclear"""
    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": content}},
                ],
            }
        ]
        resp = litellm.completion(model=model, messages=messages)
        text = resp.choices[0].message.content or "{}"
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            doc_type = parsed.get("document_type", "other")
            if doc_type not in DOCUMENT_TYPE_OPTIONS:
                doc_type = "other"
            rec_from = parsed.get("received_from")
            return (doc_type, rec_from)
    except Exception as e:
        logger.warning("Vision document classification failed: %s", e)
    return _classify_document_mock(storage_key)


def classify_document_impl(
    claim_id: str,
    document_id: int,
    *,
    db_path: str | None = None,
) -> str:
    """Classify a document using vision or heuristics, update DB, return JSON result."""
    doc_repo = DocumentRepository(db_path=db_path)
    doc = doc_repo.get_document(document_id)
    if doc is None:
        return json.dumps({"success": False, "error": "Document not found"})
    if doc.get("claim_id") != claim_id:
        return json.dumps({"success": False, "error": "Document does not belong to claim"})
    storage_key = doc.get("storage_key", "")
    if not storage_key:
        return json.dumps({"success": False, "error": "No storage key"})
    storage = get_storage_adapter()
    if not isinstance(storage, LocalStorageAdapter):
        doc_type, rec_from = _classify_document_mock(storage_key)
    else:
        path = storage.get_path(claim_id, storage_key)
        if _use_mock_document_classification():
            doc_type, rec_from = _classify_document_mock(storage_key)
        else:
            doc_type, rec_from = _classify_document_vision(path, storage_key)
    updated = doc_repo.update_document_review(
        document_id,
        document_type=doc_type,
        received_from=rec_from,
    )
    return json.dumps({
        "success": True,
        "document_id": document_id,
        "document_type": doc_type,
        "received_from": rec_from,
        "document": updated,
    })


def extract_document_data_impl(
    claim_id: str,
    document_id: int,
    *,
    db_path: str | None = None,
) -> str:
    """Extract structured data from a document via OCR adapter, update DB, return JSON."""
    doc_repo = DocumentRepository(db_path=db_path)
    doc = doc_repo.get_document(document_id)
    if doc is None:
        return json.dumps({"success": False, "error": "Document not found"})
    if doc.get("claim_id") != claim_id:
        return json.dumps({"success": False, "error": "Document does not belong to claim"})
    storage_key = doc.get("storage_key", "")
    doc_type = doc.get("document_type") or "other"
    if not storage_key:
        return json.dumps({"success": False, "error": "No storage key"})
    storage = get_storage_adapter()
    if not isinstance(storage, LocalStorageAdapter):
        return json.dumps({"success": False, "error": "OCR extraction only available for local storage"})
    path = storage.get_path(claim_id, storage_key)
    if not path.exists():
        return json.dumps({"success": False, "error": "File not found"})
    ocr = get_ocr_adapter()
    extracted = ocr.extract_structured_data(path, doc_type)
    if extracted is None:
        return json.dumps({"success": False, "error": "OCR extraction not supported for this document type"})
    updated = doc_repo.update_document_review(document_id, extracted_data=extracted)
    return json.dumps({
        "success": True,
        "document_id": document_id,
        "extracted_data": extracted,
        "document": updated,
    })
