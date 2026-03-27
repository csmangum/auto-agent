"""REST reverse-image / stock-photo lookup adapter.

Connects to an external image search provider (e.g. Google Vision, TinEye, or a
proprietary fraud-intelligence platform) for stock-photo and prior-claim matching.

Privacy note
------------
Images submitted to a production reverse-image provider may contain PII (licence
plates, faces, GPS EXIF data).  Ensure that:

* The provider's DPA covers your jurisdiction's data-transfer requirements.
* By default the REST adapter strips EXIF from JPEG/PNG/WebP before upload
  (``REVERSE_IMAGE_REST_SCRUB_EXIF_BEFORE_UPLOAD=false`` to disable if the API
  requires raw metadata).
* API keys are stored in secrets management, never in source code.
* Usage is disclosed in the applicable privacy notice / DSAR records.

Configure via environment variables:

- REVERSE_IMAGE_REST_BASE_URL: Base URL (e.g. https://image-search.example.com/api/v1)
- REVERSE_IMAGE_REST_AUTH_HEADER: Auth header name (default: Authorization)
- REVERSE_IMAGE_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- REVERSE_IMAGE_REST_MATCH_PATH: Path for image matching (default: /images/match)
- REVERSE_IMAGE_REST_RESPONSE_KEY: Optional JSON key wrapping the matches list (e.g. matches)
- REVERSE_IMAGE_REST_TIMEOUT: Request timeout in seconds (default: 30)
- REVERSE_IMAGE_REST_SCRUB_EXIF_BEFORE_UPLOAD: Strip EXIF from JPEG/PNG/WebP before
  multipart upload (default: true; set false only if the provider needs metadata)
- REVERSE_IMAGE_REST_REQUIRE_EXIF_SCRUB: Block upload when scrub was required but not
  achieved (status is SKIPPED_UNSUPPORTED, SKIPPED_NO_PILLOW, or FAILED); returns an
  empty match list. Default: false (warn + upload for pilot availability).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from claim_agent.adapters.base import ReverseImageAdapter
from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError
from claim_agent.utils.image_bytes_privacy import ScrubStatus, scrub_exif_from_image_bytes

logger = logging.getLogger(__name__)


class RestReverseImageAdapter(ReverseImageAdapter):
    """Reverse-image adapter backed by a real REST search provider.

    Expected API contract:

    * ``POST {match_path}`` with a multipart form upload (field ``image``) →
      200 JSON: a list of matches or a dict wrapping the list under ``response_key``.

    Each match must contain ``url`` (str), ``match_score`` (float 0-1), and
    ``source_label`` (str).  Optional: ``title``, ``page_fetched_at``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        match_path: str = "/images/match",
        response_key: str | None = None,
        timeout: float = 30.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
        scrub_exif_before_upload: bool = True,
        require_exif_scrub: bool = False,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_recovery_timeout=circuit_recovery_timeout,
            adapter_name="reverse_image",
        )
        self._match_path = match_path
        self._response_key = (response_key or "").strip() or None
        self._scrub_exif_before_upload = scrub_exif_before_upload
        self._require_exif_scrub = require_exif_scrub

    def _extract_matches(self, raw: Any) -> list[dict[str, Any]]:
        """Normalise the API response to a list of match dicts."""
        if isinstance(raw, list):
            return [m for m in raw if isinstance(m, dict)]
        if isinstance(raw, dict):
            if self._response_key and self._response_key in raw:
                items = raw[self._response_key]
            else:
                # Try common envelope keys
                for key in ("matches", "results", "data"):
                    if key in raw and isinstance(raw[key], list):
                        items = raw[key]
                        break
                else:
                    items = []
            return [m for m in items if isinstance(m, dict)]
        return []

    def match_web_occurrences(self, image: bytes | Path) -> list[dict[str, Any]]:
        """Submit *image* to the provider and return normalised match list."""
        try:
            if isinstance(image, Path):
                with open(image, "rb") as fh:
                    raw_bytes = fh.read()
                filename = image.name
            else:
                raw_bytes = image
                filename = "image.jpg"

            if self._scrub_exif_before_upload:
                raw_bytes, scrub_status = scrub_exif_from_image_bytes(raw_bytes)
                if scrub_status is not ScrubStatus.SCRUBBED:
                    logger.warning(
                        "Reverse-image EXIF scrub outcome: %s",
                        scrub_status.value,
                        extra={"scrub_status": scrub_status.value},
                    )
                    if self._require_exif_scrub:
                        logger.error(
                            "Reverse-image upload blocked: require_exif_scrub=True but "
                            "scrub status is %s",
                            scrub_status.value,
                        )
                        return []

            files = {"image": (filename, raw_bytes)}
            resp = self._client.post_multipart(self._match_path, files=files)
            return self._extract_matches(resp.json())
        except CircuitOpenError:
            logger.warning("Reverse-image adapter circuit breaker open; returning empty")
            return []
        except (httpx.HTTPStatusError, httpx.RequestError, OSError, ValueError):
            logger.warning("Reverse-image adapter error", exc_info=True)
            return []

    def health_check(self) -> tuple[bool, str]:
        """Probe the image search provider for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_reverse_image_adapter() -> RestReverseImageAdapter:
    """Build a REST ReverseImage adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().reverse_image_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "REVERSE_IMAGE_REST_BASE_URL is required when REVERSE_IMAGE_ADAPTER=rest. "
            "Set REVERSE_IMAGE_REST_BASE_URL to your reverse-image provider API base URL."
        )
    return RestReverseImageAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        match_path=cfg.match_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
        scrub_exif_before_upload=cfg.scrub_exif_before_upload,
        require_exif_scrub=cfg.require_exif_scrub,
    )
