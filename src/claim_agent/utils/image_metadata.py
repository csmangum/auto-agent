"""Image metadata extraction and lightweight forensics checks."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, cast

try:
    from PIL import ExifTags, Image
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency guard
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
    lat_f = cast(list[float], lat_vals)
    lon_f = cast(list[float], lon_vals)
    lat = lat_f[0] + lat_f[1] / 60 + lat_f[2] / 3600
    lon = lon_f[0] + lon_f[1] / 60 + lon_f[2] / 3600
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


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in kilometers."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


_KM_PER_MILE = 1.609344


def _coordinate_pair(
    lat: Any, lon: Any
) -> tuple[float, float] | None:
    if lat is None or lon is None:
        return None
    try:
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None
    return (la, lo)


def analyze_photo_forensics(
    metadata: dict[str, Any],
    *,
    incident_date: str | date | datetime | None = None,
    incident_latitude: Any = None,
    incident_longitude: Any = None,
    photo_gps_incident_max_distance: float = 50.0,
    photo_gps_incident_distance_unit: str = "miles",
) -> dict[str, Any]:
    """Analyze EXIF metadata for simple fraud-oriented anomalies."""
    anomalies: list[str] = []
    errors = metadata.get("errors") or []
    extraction_failed = any(
        isinstance(e, str) and (e == "pillow_unavailable" or e.startswith("exif_error:"))
        for e in errors
    )
    has_exif = bool(metadata.get("has_exif"))
    if not has_exif and not extraction_failed:
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
    if gps is None and not extraction_failed:
        anomalies.append("photo_missing_gps")

    incident_ll = _coordinate_pair(incident_latitude, incident_longitude)
    if (
        not extraction_failed
        and isinstance(gps, tuple)
        and len(gps) == 2
        and incident_ll is not None
    ):
        try:
            plat = float(gps[0])
            plon = float(gps[1])
        except (TypeError, ValueError):
            plat = plon = float("nan")
        if not (math.isnan(plat) or math.isnan(plon)):
            dist_km = haversine_distance_km(plat, plon, incident_ll[0], incident_ll[1])
            unit = str(photo_gps_incident_distance_unit).strip().lower()
            if unit in ("km", "kilometer", "kilometers"):
                threshold_km = float(photo_gps_incident_max_distance)
            else:
                threshold_km = float(photo_gps_incident_max_distance) * _KM_PER_MILE
            if threshold_km > 0 and dist_km > threshold_km:
                anomalies.append("photo_gps_far_from_incident")

    return {
        "anomalies": sorted(set(anomalies)),
        "metadata": metadata,
    }
