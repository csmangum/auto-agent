"""Strip sensitive image metadata from in-memory bytes before third-party upload."""

from __future__ import annotations

import io
import logging
from typing import Final

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]

# Formats where we re-save without EXIF (JPEG explicit exif=b""; PNG/WEBP via clean save).
_STRIP_FORMATS: Final[frozenset[str]] = frozenset({"JPEG", "PNG", "WEBP"})


def scrub_exif_from_image_bytes(data: bytes) -> bytes:
    """Return image bytes with EXIF stripped when Pillow recognizes a supported raster format.

    If Pillow is unavailable, the buffer is not an image, or re-encoding fails, returns
    *data* unchanged and logs at DEBUG (no secrets in log messages).
    """
    if not data or Image is None:
        if not data:
            return data
        logger.debug("Pillow unavailable; skipping in-memory EXIF scrub for reverse-image upload")
        return data

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = (im.format or "").upper()
            if fmt not in _STRIP_FORMATS:
                logger.debug(
                    "Reverse-image EXIF scrub skipped for format %s (not in supported set)",
                    im.format,
                )
                return data

            out = io.BytesIO()
            save_kw: dict = {}
            if fmt in ("JPEG", "MPO"):
                # Empty EXIF removes the segment on re-save.
                save_kw["exif"] = b""
                save_kw["quality"] = 95
            elif fmt == "WEBP":
                save_kw["exif"] = b""
                save_kw["quality"] = 85
            # PNG: no EXIF kw; re-saving drops most auxiliary chunks in practice.

            im.save(out, format=im.format, **save_kw)
            return out.getvalue()
    except Exception:
        logger.warning(
            "Failed to scrub EXIF from image bytes before upload; sending original buffer",
            exc_info=True,
        )
        return data
