"""Image metadata extraction and lightweight forensics checks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

try:
    from PIL import ExifTags, Image
except Exception:  # pragma: no cover - optional dependency guard
    ExifTags = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, tuple) and len(value) == 2 and value[1] not in (0, 0.0):
        try:
            return float(value[0]) / float(value[1])
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def _gps_to_decimal(gps: dict[str, Any]) -> tuple[float, float] | None:
    lat_raw = gps.get("GPSLatitude")
    lon_raw = gps.get("GPSLongitude")
    lat_ref = str(gps.get("GPSLatitudeRef", "N")).upper()
    lon_ref = str(gps.get("GPSLongitudeRef", "E")).upper()
    if not isinstance(lat_raw, tuple) or not isinstance(lon_raw, tuple):
        return None
    if len(lat_raw) != 3 or len(lon_raw) != 3:
        return None
    lat_vals = [_to_float(v) for v in lat_raw]
    lon_vals = [_to_float(v) for v in lon_raw]
    if any(v is None for v in (*lat_vals, *lon_vals)):
        return None
    lat = float(lat_vals[0]) + float(lat_vals[1]) / 60 + float(lat_vals[2]) / 3600
    lon = float(lon_vals[0]) + float(lon_vals[1]) / 60 + float(lon_vals[2]) / 3600
    if lat_ref == "S":
        lat *= -1
    if lon_ref == "W":
        lon *= -1
    return (round(lat, 6), round(lon, 6))


def extract_exif_metadata(image_path: str) -> dict[str, Any]:
    """Extract a normalized subset of EXIF metadata from image file path."""
    result: dict[str, Any] = {
        "has_exif": False,
        "captured_at": None,
        "device_make": None,
        "device_model": None,
        "software": None,
        "gps": None,
        "errors": [],
    }
    if not image_path:
        result["errors"].append("empty_path")
        return result
    if Image is None or ExifTags is None:
        result["errors"].append("pillow_unavailable")
        return result
    try:
        with Image.open(image_path) as image:
            exif_raw = image.getexif()
            if not exif_raw:
                return result
            exif_named: dict[str, Any] = {}
            for key, value in exif_raw.items():
                tag_name = ExifTags.TAGS.get(key, str(key))
                exif_named[tag_name] = value
            result["has_exif"] = True
            captured_at = exif_named.get("DateTimeOriginal") or exif_named.get("DateTime")
            if isinstance(captured_at, str) and captured_at.strip():
                result["captured_at"] = captured_at.strip()
            for field, tag in (
                ("device_make", "Make"),
                ("device_model", "Model"),
                ("software", "Software"),
            ):
                raw = exif_named.get(tag)
                if isinstance(raw, str) and raw.strip():
                    result[field] = raw.strip()

            gps_ifd = exif_named.get("GPSInfo")
            if isinstance(gps_ifd, dict):
                gps_named: dict[str, Any] = {}
                for key, value in gps_ifd.items():
                    gps_name = ExifTags.GPSTAGS.get(key, str(key))
                    gps_named[gps_name] = value
                result["gps"] = _gps_to_decimal(gps_named)
    except Exception as e:  # pragma: no cover - filesystem/image edge cases
        result["errors"].append(f"exif_error:{type(e).__name__}")
    return result


def analyze_photo_forensics(
    metadata: dict[str, Any],
    *,
    incident_date: str | date | datetime | None = None,
) -> dict[str, Any]:
    """Analyze EXIF metadata for simple fraud-oriented anomalies."""
    anomalies: list[str] = []
    has_exif = bool(metadata.get("has_exif"))
    if not has_exif:
        anomalies.append("photo_missing_exif")

    captured_raw = metadata.get("captured_at")
    captured_dt: datetime | None = None
    if isinstance(captured_raw, str):
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                captured_dt = datetime.strptime(captured_raw, fmt)
                break
            except ValueError:
                continue
    incident_dt: datetime | None = None
    if isinstance(incident_date, datetime):
        incident_dt = incident_date
    elif isinstance(incident_date, date):
        incident_dt = datetime.combine(incident_date, datetime.min.time())
    elif isinstance(incident_date, str):
        try:
            incident_dt = datetime.strptime(incident_date.strip(), "%Y-%m-%d")
        except ValueError:
            incident_dt = None

    if captured_dt and incident_dt:
        if captured_dt.date() < incident_dt.date():
            anomalies.append("photo_captured_before_incident")
        elif (captured_dt.date() - incident_dt.date()).days > 30:
            anomalies.append("photo_captured_long_after_incident")

    software = metadata.get("software")
    if isinstance(software, str) and software.strip():
        lowered = software.lower()
        if any(token in lowered for token in ("photoshop", "gimp", "snapseed")):
            anomalies.append("photo_editing_software_detected")

    gps = metadata.get("gps")
    if gps is None:
        anomalies.append("photo_missing_gps")

    return {
        "anomalies": sorted(set(anomalies)),
        "metadata": metadata,
    }
