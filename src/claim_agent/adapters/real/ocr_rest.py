"""REST OCR adapter for calling an external document extraction API.

Configure via environment variables:

- OCR_REST_BASE_URL: Base URL (e.g. https://ocr.example.com/api/v1)
- OCR_REST_AUTH_HEADER: Auth header name (default: Authorization)
- OCR_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- OCR_REST_EXTRACT_PATH: Path for extraction endpoint (default: /ocr/extract)
- OCR_REST_RESPONSE_KEY: Optional JSON key wrapping the structured data (e.g. data)
- OCR_REST_TIMEOUT: Request timeout in seconds (default: 30)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from claim_agent.adapters.base import OCRAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
    safe_adapter_json_dict,
)

logger = logging.getLogger(__name__)


class RestOCRAdapter(OCRAdapter):
    """OCR adapter backed by a real REST extraction API.

    Expected API contract:

    * ``POST {extract_path}`` with a multipart form upload (field ``file``) and a
      ``document_type`` query parameter → 200 JSON with structured extraction data.

    The response must return document-type-specific keys matching the contract
    defined in ``OCRAdapter.extract_structured_data``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        extract_path: str = "/ocr/extract",
        response_key: str | None = None,
        timeout: float = 30.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_recovery_timeout=circuit_recovery_timeout,
            adapter_name="ocr",
        )
        self._extract_path = extract_path
        self._response_key = (response_key or "").strip() or None

    def _unwrap_payload(self, raw: Any) -> dict[str, Any] | None:
        """Unwrap optional response envelope key and validate the data dict."""
        inner = extract_response_envelope(raw, self._response_key)
        return inner if isinstance(inner, dict) else None

    def extract_structured_data(self, file_path: Path, document_type: str) -> dict[str, Any] | None:
        """Call the OCR REST API with the given file and return structured extraction.

        Uploads the file as a multipart form POST. The ``document_type`` is sent as
        a query parameter so the backend can apply the appropriate extraction model.
        """
        try:
            with open(file_path, "rb") as fh:
                file_bytes = fh.read()
            files = {"file": (file_path.name, file_bytes)}
            resp = self._client.post_multipart(
                self._extract_path,
                files=files,
                params={"document_type": document_type},
            )
            parsed = safe_adapter_json_dict(resp, log_label="ocr_rest")
            if parsed is None:
                return None
            return self._unwrap_payload(parsed)
        except CircuitOpenError:
            logger.warning("OCR adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            logger.warning("OCR adapter HTTP error: %s", exc, exc_info=True)
            return None
        except httpx.RequestError as exc:
            logger.warning("OCR adapter request error: %s", exc, exc_info=True)
            return None
        except (OSError, ValueError):
            logger.warning("OCR adapter file or parse error", exc_info=True)
            return None

    def health_check(self) -> tuple[bool, str]:
        """Probe the OCR API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_ocr_adapter() -> RestOCRAdapter:
    """Build a REST OCR adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().ocr_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "OCR_REST_BASE_URL is required when OCR_ADAPTER=rest. "
            "Set OCR_REST_BASE_URL to your OCR API base URL."
        )
    return RestOCRAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        extract_path=cfg.extract_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
