"""Tests for EXIF metadata extraction and photo forensics helpers."""

from claim_agent.utils.image_metadata import analyze_photo_forensics, extract_exif_metadata


class TestPhotoForensicsHelpers:
    def test_extract_exif_metadata_handles_empty_path(self):
        result = extract_exif_metadata("")
        assert result["has_exif"] is False
        assert "empty_path" in result["errors"]

    def test_analyze_photo_forensics_flags_missing_exif_and_gps(self):
        result = analyze_photo_forensics({"has_exif": False, "gps": None}, incident_date="2026-01-10")
        assert "photo_missing_exif" in result["anomalies"]
        assert "photo_missing_gps" in result["anomalies"]

    def test_analyze_photo_forensics_detects_capture_before_incident(self):
        metadata = {"has_exif": True, "captured_at": "2026:01:01 10:00:00", "gps": (1.0, 1.0)}
        result = analyze_photo_forensics(metadata, incident_date="2026-01-10")
        assert "photo_captured_before_incident" in result["anomalies"]

    def test_analyze_photo_forensics_detects_editing_software(self):
        metadata = {"has_exif": True, "captured_at": "2026:01:11 10:00:00", "software": "Adobe Photoshop"}
        result = analyze_photo_forensics(metadata, incident_date="2026-01-10")
        assert "photo_editing_software_detected" in result["anomalies"]
