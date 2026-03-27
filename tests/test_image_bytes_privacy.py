"""Tests for in-memory image EXIF scrubbing before third-party upload."""

from io import BytesIO

import pytest

from claim_agent.utils import image_bytes_privacy


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

    scrubbed = image_bytes_privacy.scrub_exif_from_image_bytes(raw)
    assert scrubbed != raw

    exif_after = Image.open(BytesIO(scrubbed)).getexif()
    assert exif_after.get(Base.Software) is None


def test_scrub_returns_original_when_not_image():
    data = b"not an image at all"
    assert image_bytes_privacy.scrub_exif_from_image_bytes(data) is data


def test_scrub_unsupported_format_logs_warning(caplog):
    """GIF is not in the strip set; operator should see WARNING when scrub is requested."""
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="GIF")
    gif_bytes = buf.getvalue()

    import logging

    caplog.set_level(logging.WARNING)
    out = image_bytes_privacy.scrub_exif_from_image_bytes(gif_bytes)
    assert out == gif_bytes
    assert any("EXIF scrub skipped" in r.message for r in caplog.records)
