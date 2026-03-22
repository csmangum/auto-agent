"""Tests for EXIF metadata extraction and photo forensics helpers."""

from claim_agent.utils.image_metadata import (
    analyze_photo_forensics,
    extract_exif_metadata,
    haversine_distance_km,
)


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

    def test_haversine_same_point_is_near_zero(self):
        assert haversine_distance_km(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_haversine_short_distance_reasonable(self):
        """~1 km apart near NYC latitude."""
        d = haversine_distance_km(40.7128, -74.0060, 40.7218, -74.0060)
        assert 0.8 < d < 1.2

    def test_haversine_antipodal_order_of_magnitude(self):
        d = haversine_distance_km(0.0, 0.0, 0.0, 180.0)
        assert 19000 < d < 21000

    def test_analyze_photo_forensics_gps_far_from_incident(self):
        metadata = {
            "has_exif": True,
            "captured_at": "2026:01:11 10:00:00",
            "gps": (34.0522, -118.2437),
            "errors": [],
        }
        result = analyze_photo_forensics(
            metadata,
            incident_date="2026-01-10",
            incident_latitude=40.7128,
            incident_longitude=-74.0060,
            photo_gps_incident_max_distance=50.0,
            photo_gps_incident_distance_unit="miles",
        )
        assert "photo_gps_far_from_incident" in result["anomalies"]

    def test_analyze_photo_forensics_gps_near_incident_no_flag(self):
        metadata = {
            "has_exif": True,
            "captured_at": "2026:01:11 10:00:00",
            "gps": (40.7218, -74.0060),
            "errors": [],
        }
        result = analyze_photo_forensics(
            metadata,
            incident_date="2026-01-10",
            incident_latitude=40.7128,
            incident_longitude=-74.0060,
            photo_gps_incident_max_distance=50.0,
            photo_gps_incident_distance_unit="miles",
        )
        assert "photo_gps_far_from_incident" not in result["anomalies"]

    def test_analyze_photo_forensics_no_distance_flag_without_incident_coords(self):
        metadata = {
            "has_exif": True,
            "captured_at": "2026:01:11 10:00:00",
            "gps": (34.0522, -118.2437),
            "errors": [],
        }
        result = analyze_photo_forensics(
            metadata,
            incident_date="2026-01-10",
            photo_gps_incident_max_distance=0.01,
            photo_gps_incident_distance_unit="miles",
        )
        assert "photo_gps_far_from_incident" not in result["anomalies"]

    def test_analyze_photo_forensics_no_distance_flag_when_extraction_failed(self):
        metadata = {
            "has_exif": True,
            "captured_at": "2026:01:11 10:00:00",
            "gps": (34.0522, -118.2437),
            "errors": ["exif_error:OSError"],
        }
        result = analyze_photo_forensics(
            metadata,
            incident_date="2026-01-10",
            incident_latitude=40.7128,
            incident_longitude=-74.0060,
            photo_gps_incident_max_distance=0.01,
            photo_gps_incident_distance_unit="miles",
        )
        assert "photo_gps_far_from_incident" not in result["anomalies"]

    def test_analyze_photo_forensics_distance_unit_km(self):
        metadata = {
            "has_exif": True,
            "captured_at": "2026:01:11 10:00:00",
            "gps": (40.7218, -74.0060),
            "errors": [],
        }
        result = analyze_photo_forensics(
            metadata,
            incident_date="2026-01-10",
            incident_latitude=40.7128,
            incident_longitude=-74.0060,
            photo_gps_incident_max_distance=0.5,
            photo_gps_incident_distance_unit="km",
        )
        assert "photo_gps_far_from_incident" in result["anomalies"]
