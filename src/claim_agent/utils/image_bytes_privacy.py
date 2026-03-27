"""Strip sensitive image metadata from in-memory bytes before third-party upload."""

from __future__ import annotations

import enum
import io
import logging
from typing import Final

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]

# Formats where we re-save without EXIF (JPEG explicit exif=b""; PNG/WEBP via clean save).
_STRIP_FORMATS: Final[frozenset[str]] = frozenset({"JPEG", "MPO", "PNG", "WEBP"})


class ScrubStatus(enum.Enum):
    """Outcome of an EXIF-scrub attempt.

    Callers can inspect this value to decide whether to proceed with upload,
    emit a compliance metric, or block if strict scrubbing is required.

    Values
    ------
    SCRUBBED
        EXIF was removed and the re-encoded buffer was returned.  Also used
        when the input is empty (nothing to strip).
    SKIPPED_UNSUPPORTED
        Pillow recognised the image format but it is not in the supported strip
        set (e.g. GIF, BMP).  The original buffer is returned unchanged.
    SKIPPED_NO_PILLOW
        Pillow is not installed.  The original buffer is returned unchanged.
    FAILED
        An exception occurred while opening or re-encoding the image.  The
        original buffer is returned unchanged so that availability is
        preserved by default.
    """

    SCRUBBED = "scrubbed"
    SKIPPED_UNSUPPORTED = "skipped_unsupported"
    SKIPPED_NO_PILLOW = "skipped_no_pillow"
    FAILED = "failed"


def scrub_exif_from_image_bytes(data: bytes) -> tuple[bytes, ScrubStatus]:
    """Return ``(image_bytes, ScrubStatus)`` after attempting EXIF removal.

    The returned bytes have EXIF stripped when Pillow recognises a supported
    raster format (JPEG/MPO/PNG/WebP).  In all other cases the original
    *data* is returned unchanged together with the relevant :class:`ScrubStatus`
    so that callers can apply their own policy (block, warn, metric).

    Status matrix
    -------------
    * Empty *data* → ``(data, SCRUBBED)`` – nothing to strip.
    * Pillow unavailable → ``(data, SKIPPED_NO_PILLOW)``
    * Format outside strip set → ``(data, SKIPPED_UNSUPPORTED)``
    * Re-encoding exception → ``(data, FAILED)``
    * Success → ``(scrubbed_bytes, SCRUBBED)``
    """
    if not data:
        # Empty buffer has no metadata; treat as scrubbed so strict callers
        # are not unnecessarily blocked.
        return data, ScrubStatus.SCRUBBED

    if Image is None:
        logger.debug("Pillow unavailable; skipping in-memory EXIF scrub for reverse-image upload")
        return data, ScrubStatus.SKIPPED_NO_PILLOW

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = (im.format or "").upper()
            if fmt not in _STRIP_FORMATS:
                logger.warning(
                    "Reverse-image EXIF scrub skipped for format %s (not in supported set); "
                    "original bytes may still contain metadata",
                    im.format,
                )
                return data, ScrubStatus.SKIPPED_UNSUPPORTED

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
            return out.getvalue(), ScrubStatus.SCRUBBED
    except Exception:
        logger.warning(
            "Failed to scrub EXIF from image bytes before upload; sending original buffer",
            exc_info=True,
        )
        return data, ScrubStatus.FAILED
