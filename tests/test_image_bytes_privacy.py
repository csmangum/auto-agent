"""Tests for in-memory image EXIF scrubbing before third-party upload."""

from io import BytesIO

import pytest

from claim_agent.utils import image_bytes_privacy
from claim_agent.utils.image_bytes_privacy import ScrubStatus


pytest.importorskip("PIL", reason="Pillow required for EXIF scrub tests")


def _jpeg_with_exif() -> bytes:
    from PIL import Image
    from PIL.ExifTags import Base

    im = Image.new("RGB", (8, 8), (200, 100, 50))
    exif = im.getexif()
    exif[Base.Software] = "claim-agent-exif-test-marker"
    buf = BytesIO()
    im.save(buf, format="JPEG", exif=exif.tobytes(), quality=90)
    return buf.getvalue()


def test_scrub_exif_from_jpeg_removes_exif():
    raw = _jpeg_with_exif()
    from PIL import Image
    from PIL.ExifTags import Base

    assert Image.open(BytesIO(raw)).getexif().get(Base.Software) == "claim-agent-exif-test-marker"

    scrubbed, status = image_bytes_privacy.scrub_exif_from_image_bytes(raw)
    assert status is ScrubStatus.SCRUBBED
    assert scrubbed != raw

    exif_after = Image.open(BytesIO(scrubbed)).getexif()
    assert exif_after.get(Base.Software) is None


def test_scrub_returns_original_when_not_image():
    data = b"not an image at all"
    result, status = image_bytes_privacy.scrub_exif_from_image_bytes(data)
    assert result is data
    assert status is ScrubStatus.FAILED


def test_scrub_unsupported_format_logs_warning(caplog):
    """GIF is not in the strip set; operator should see WARNING when scrub is requested."""
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="GIF")
    gif_bytes = buf.getvalue()

    import logging

    caplog.set_level(logging.WARNING)
    out, status = image_bytes_privacy.scrub_exif_from_image_bytes(gif_bytes)
    assert out == gif_bytes
    assert status is ScrubStatus.SKIPPED_UNSUPPORTED
    assert any("EXIF scrub skipped" in r.message for r in caplog.records)


def test_scrub_empty_bytes_returns_scrubbed_status():
    """Empty input is treated as safe (nothing to strip)."""
    result, status = image_bytes_privacy.scrub_exif_from_image_bytes(b"")
    assert result == b""
    assert status is ScrubStatus.SCRUBBED


def test_scrub_failure_returns_failed_status(monkeypatch):
    """When Image.open raises, FAILED status is returned with the original bytes."""
    from PIL import Image as PILImage

    class _BrokenImage:
        @staticmethod
        def open(*_a, **_kw):
            raise RuntimeError("synthetic failure")

    monkeypatch.setattr(image_bytes_privacy, "Image", _BrokenImage)

    data = b"\xff\xd8\xff some jpeg-ish bytes"
    result, status = image_bytes_privacy.scrub_exif_from_image_bytes(data)
    assert result is data
    assert status is ScrubStatus.FAILED

    # Restore so other tests are unaffected
    monkeypatch.setattr(image_bytes_privacy, "Image", PILImage)


def test_scrub_png_returns_scrubbed_status():
    """PNG is in the supported strip set; scrub should succeed."""
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    result, status = image_bytes_privacy.scrub_exif_from_image_bytes(png_bytes)
    assert status is ScrubStatus.SCRUBBED
    assert isinstance(result, bytes)
    assert len(result) > 0
