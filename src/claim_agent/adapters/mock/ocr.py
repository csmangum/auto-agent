"""Mock OCR adapter: returns sample structured data for estimates, police reports, medical records."""

from pathlib import Path
from typing import Any

from claim_agent.adapters.base import OCRAdapter


class MockOCRAdapter(OCRAdapter):
    """Mock OCR: returns sample structured data based on document_type."""

    def extract_structured_data(self, file_path: Path, document_type: str) -> dict[str, Any] | None:
        doc_type = (document_type or "").lower()
        if doc_type == "estimate":
            return {
                "line_items": [
                    {"description": "Bumper cover replacement", "quantity": 1, "unit_cost": 450.00, "total": 450.00},
                    {"description": "Paint and blend", "quantity": 3.0, "unit_cost": 55.00, "total": 165.00},
                    {"description": "Labor", "quantity": 4.5, "unit_cost": 75.00, "total": 337.50},
                ],
                "parts_cost": 450.00,
                "labor_cost": 502.50,
                "total": 952.50,
                "tax": 0,
            }
        if doc_type == "police_report":
            return {
                "incident_date": "2024-01-15",
                "report_number": "24-001234",
                "parties": [
                    {"name": "Driver 1", "role": "at_fault", "vehicle": "2020 Honda Accord"},
                    {"name": "Driver 2", "role": "not_at_fault", "vehicle": "2019 Toyota Camry"},
                ],
                "location": "Main St & Oak Ave",
                "narrative": "Vehicle 1 struck Vehicle 2 from behind at intersection.",
            }
        if doc_type == "medical_record":
            return {
                "diagnoses": ["Whiplash", "Cervical strain"],
                "charges": 1250.00,
                "provider": "ABC Medical Group",
                "treatment_dates": ["2024-01-16", "2024-01-20"],
                "procedures": ["Initial evaluation", "Follow-up"],
            }
        return None
