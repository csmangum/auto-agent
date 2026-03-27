"""Unit tests for the ReverseImageAdapter -- mock and stub implementations."""

import json
import os
import types
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claim_agent.config.settings import get_adapter_backend as real_get_adapter_backend

# Minimal JPEG: SOI marker (FF D8) + JFIF APP0 segment + EOI marker (FF D9).
# Used to write temporary image files in tests without requiring real image data.
_MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_adapters():
    """Clear the adapter singleton cache between tests."""
    from claim_agent.adapters.registry import reset_adapters

    reset_adapters()


# ---------------------------------------------------------------------------
# MockReverseImageAdapter
# ---------------------------------------------------------------------------


class TestMockReverseImageAdapter:
    def setup_method(self):
        _reset_adapters()

    def teardown_method(self):
        _reset_adapters()

    def test_returns_list(self):
        """match_web_occurrences always returns a non-empty list in mock mode."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = MockReverseImageAdapter()
        result = adapter.match_web_occurrences(b"\xff\xd8\xff")  # minimal JPEG magic
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_match_has_required_keys(self):
        """Every returned match must include url, match_score, and source_label."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = MockReverseImageAdapter()
        matches = adapter.match_web_occurrences(b"fake-image-bytes")
        for match in matches:
            assert "url" in match, "match missing 'url'"
            assert "match_score" in match, "match missing 'match_score'"
            assert "source_label" in match, "match missing 'source_label'"

    def test_match_score_in_range(self):
        """match_score values must be in [0, 1]."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = MockReverseImageAdapter()
        for match in adapter.match_web_occurrences(b"bytes"):
            score = match["match_score"]
            assert 0.0 <= score <= 1.0, f"match_score {score} out of [0, 1] range"

    def test_accepts_path_argument(self, tmp_path):
        """match_web_occurrences accepts a Path argument (no error raised)."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")
        adapter = MockReverseImageAdapter()
        result = adapter.match_web_occurrences(img)
        assert isinstance(result, list)

    def test_deterministic_output(self):
        """Mock adapter returns the same matches on repeated calls."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = MockReverseImageAdapter()
        first = adapter.match_web_occurrences(b"img1")
        second = adapter.match_web_occurrences(b"img2")
        assert first == second, "Mock adapter must return deterministic results"

    def test_returns_independent_copies(self):
        """Mutations to one result list must not affect subsequent calls."""
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = MockReverseImageAdapter()
        result_a = adapter.match_web_occurrences(b"img")
        result_a.clear()
        result_b = adapter.match_web_occurrences(b"img")
        assert len(result_b) > 0, "Mock must return fresh list on each call"


# ---------------------------------------------------------------------------
# StubReverseImageAdapter
# ---------------------------------------------------------------------------


class TestStubReverseImageAdapter:
    def test_raises_not_implemented_error(self):
        """StubReverseImageAdapter.match_web_occurrences must raise NotImplementedError."""
        from claim_agent.adapters.stub import StubReverseImageAdapter

        adapter = StubReverseImageAdapter()
        with pytest.raises(NotImplementedError):
            adapter.match_web_occurrences(b"bytes")


# ---------------------------------------------------------------------------
# RestReverseImageAdapter -- EXIF scrub before multipart
# ---------------------------------------------------------------------------


def test_rest_reverse_image_posts_scrubbed_jpeg_bytes():
    pytest.importorskip("PIL")
    from PIL import Image
    from PIL.ExifTags import Base

    from claim_agent.adapters.real.reverse_image_rest import RestReverseImageAdapter

    im = Image.new("RGB", (4, 4), (10, 20, 30))
    exif = im.getexif()
    exif[Base.Software] = "reverse-image-upload-test"
    buf = BytesIO()
    im.save(buf, format="JPEG", exif=exif.tobytes(), quality=90)
    raw = buf.getvalue()
    assert Image.open(BytesIO(raw)).getexif().get(Base.Software) == "reverse-image-upload-test"

    mock_client = MagicMock()
    good = MagicMock()
    good.status_code = 200
    good.json = MagicMock(return_value=[])
    good.raise_for_status = MagicMock()
    mock_client.post_multipart = MagicMock(return_value=good)

    adapter = RestReverseImageAdapter(
        base_url="https://provider.example.com/api",
        scrub_exif_before_upload=True,
    )
    adapter._client = mock_client  # type: ignore[method-assign]

    adapter.match_web_occurrences(raw)

    mock_client.post_multipart.assert_called_once()
    args, kwargs = mock_client.post_multipart.call_args
    assert args[0] == "/images/match"
    posted = kwargs["files"]["image"][1]
    assert posted != raw
    assert Image.open(BytesIO(posted)).getexif().get(Base.Software) is None


def test_rest_reverse_image_skips_scrub_when_disabled():
    from claim_agent.adapters.real.reverse_image_rest import RestReverseImageAdapter

    raw = b"send-as-is-payload"
    mock_client = MagicMock()
    good = MagicMock()
    good.status_code = 200
    good.json = MagicMock(return_value=[])
    good.raise_for_status = MagicMock()
    mock_client.post_multipart = MagicMock(return_value=good)

    adapter = RestReverseImageAdapter(
        base_url="https://provider.example.com/api",
        scrub_exif_before_upload=False,
    )
    adapter._client = mock_client  # type: ignore[method-assign]

    adapter.match_web_occurrences(raw)

    _args, kwargs = mock_client.post_multipart.call_args
    assert kwargs["files"]["image"][1] is raw


# ---------------------------------------------------------------------------
# Registry / get_reverse_image_adapter
# ---------------------------------------------------------------------------


class TestReverseImageRegistry:
    def setup_method(self):
        _reset_adapters()

    def teardown_method(self):
        _reset_adapters()
        os.environ.pop("REVERSE_IMAGE_ADAPTER", None)
        from claim_agent.config import reload_settings
        reload_settings()

    def test_default_backend_is_mock(self, monkeypatch):
        """Without REVERSE_IMAGE_ADAPTER set, the registry returns the mock adapter."""
        monkeypatch.delenv("REVERSE_IMAGE_ADAPTER", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        from claim_agent.adapters.registry import get_reverse_image_adapter
        from claim_agent.adapters.mock.reverse_image import MockReverseImageAdapter

        adapter = get_reverse_image_adapter()
        assert isinstance(adapter, MockReverseImageAdapter)

    def test_stub_backend_via_env(self, monkeypatch):
        """REVERSE_IMAGE_ADAPTER=stub returns StubReverseImageAdapter."""
        monkeypatch.setenv("REVERSE_IMAGE_ADAPTER", "stub")
        from claim_agent.config import reload_settings
        reload_settings()
        from claim_agent.adapters.registry import get_reverse_image_adapter
        from claim_agent.adapters.stub import StubReverseImageAdapter

        adapter = get_reverse_image_adapter()
        assert isinstance(adapter, StubReverseImageAdapter)

    def test_invalid_backend_raises_value_error(self, monkeypatch):
        """An unknown REVERSE_IMAGE_ADAPTER value raises ValueError."""
        monkeypatch.setenv("REVERSE_IMAGE_ADAPTER", "unknown_provider")
        from claim_agent.config import reload_settings
        reload_settings()
        from claim_agent.adapters.registry import get_reverse_image_adapter

        with pytest.raises(ValueError, match="REVERSE_IMAGE_ADAPTER"):
            get_reverse_image_adapter()

    def test_singleton_returns_same_instance(self, monkeypatch):
        """Registry returns the same instance on repeated calls."""
        monkeypatch.delenv("REVERSE_IMAGE_ADAPTER", raising=False)
        from claim_agent.adapters.registry import get_reverse_image_adapter

        a = get_reverse_image_adapter()
        b = get_reverse_image_adapter()
        assert a is b

    def test_reset_clears_cache(self, monkeypatch):
        """reset_adapters() allows a fresh adapter to be created."""
        monkeypatch.delenv("REVERSE_IMAGE_ADAPTER", raising=False)
        from claim_agent.adapters.registry import get_reverse_image_adapter, reset_adapters

        first = get_reverse_image_adapter()
        reset_adapters()
        second = get_reverse_image_adapter()
        # Both are mock instances; they should be different objects after reset
        assert first is not second


# ---------------------------------------------------------------------------
# vision_logic integration: reverse_image_matches in photo_forensics
# ---------------------------------------------------------------------------


class TestVisionLogicReverseImageIntegration:
    """Verify that vision_logic wires reverse-image results into photo_forensics."""

    def setup_method(self):
        _reset_adapters()

    def teardown_method(self):
        _reset_adapters()
        os.environ.pop("REVERSE_IMAGE_ADAPTER", None)
        from claim_agent.config import reload_settings
        reload_settings()

    def _make_minimal_jpeg(self, tmp_path: Path) -> str:
        """Write a tiny valid-enough JPEG and return a file:// URL."""
        img = tmp_path / "test.jpg"
        img.write_bytes(_MINIMAL_JPEG_BYTES)
        return img.as_uri()

    def test_reverse_image_matches_in_photo_forensics(self, monkeypatch, tmp_path):
        """photo_forensics contains reverse_image_matches when the non-mock vision path runs."""
        settings_path = str(tmp_path)
        # Patch get_settings in vision_logic's namespace so the path access check passes.
        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.get_settings",
            lambda: _FakeSettings(settings_path),
        )
        # Force the non-mock (LLM) code path so the reverse-image block actually runs.
        monkeypatch.setattr("claim_agent.tools.vision_logic._use_mock_vision", lambda: False)
        # Reverse-image backend only: delegate other adapter names to real settings.
        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.get_adapter_backend",
            lambda name: (
                "mock" if name == "reverse_image" else real_get_adapter_backend(name)
            ),
        )
        # Stub out the LLM call to avoid needing a real API key.
        _fake_resp = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content='{"severity": "low", "parts_affected": [], "notes": "ok"}'
                    )
                )
            ]
        )

        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.litellm.completion",
            lambda *a, **kw: _fake_resp,
        )

        from claim_agent.tools.vision_logic import analyze_damage_photo_impl

        url = self._make_minimal_jpeg(tmp_path)
        raw = analyze_damage_photo_impl(url)
        data = json.loads(raw)
        assert "reverse_image_matches" in data.get("photo_forensics", {}), (
            "photo_forensics should contain reverse_image_matches when adapter is mock"
        )

    def test_stub_backend_skips_reverse_image(self, monkeypatch, tmp_path):
        """When REVERSE_IMAGE_ADAPTER=stub, vision_logic does not call match_web_occurrences."""
        monkeypatch.setenv("REVERSE_IMAGE_ADAPTER", "stub")
        from claim_agent.config import reload_settings

        reload_settings()

        from claim_agent.config.settings import get_adapter_backend

        assert get_adapter_backend("reverse_image") == "stub"

        settings_path = str(tmp_path)
        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.get_settings",
            lambda: _FakeSettings(settings_path),
        )
        monkeypatch.setattr("claim_agent.tools.vision_logic._use_mock_vision", lambda: False)

        def _reverse_image_adapter_must_not_resolve(*_a, **_kw):
            raise AssertionError(
                "get_reverse_image_adapter must not be called when backend is stub"
            )

        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.get_reverse_image_adapter",
            _reverse_image_adapter_must_not_resolve,
        )

        _fake_resp = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content='{"severity": "low", "parts_affected": [], "notes": "ok"}'
                    )
                )
            ]
        )
        monkeypatch.setattr(
            "claim_agent.tools.vision_logic.litellm.completion",
            lambda *a, **kw: _fake_resp,
        )

        from claim_agent.tools.vision_logic import analyze_damage_photo_impl

        url = self._make_minimal_jpeg(tmp_path)
        raw = analyze_damage_photo_impl(url)
        data = json.loads(raw)
        assert data.get("error") is None
        assert "reverse_image_matches" not in data.get("photo_forensics", {})


class _FakeSettings:
    """Minimal settings stand-in for path validation tests."""

    def __init__(self, attachment_path: str) -> None:
        self.paths = _FakePaths(attachment_path)

    @property
    def llm(self):
        return _FakeLLM()


class _FakePaths:
    def __init__(self, p: str) -> None:
        self.attachment_storage_path = p


class _FakeLLM:
    vision_model = "gpt-4o"
