"""HTTP client for real adapters: auth, retry, circuit breaker.

Use this module when building REST-based adapters (policy, valuation, etc.)
to ensure consistent authentication, transient-error retry, and circuit
breaker behavior.
"""

import logging
import threading
import time
from typing import Any

import httpx
from tenacity import (
    Retrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Retry on 408, 429, 5xx."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    code = getattr(resp, "status_code", 0)
    return code in RETRYABLE_STATUS_CODES

logger = logging.getLogger(__name__)

# Transient errors worth retrying
RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
# HTTP status codes that indicate transient failures
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open (too many failures)."""


class AdapterHttpClient:
    """HTTP client with auth, retry, and circuit breaker for adapter calls.

    Usage:
        client = AdapterHttpClient(
            base_url="https://pas.example.com/api/v1",
            auth_header="Authorization",
            auth_value="Bearer sk-...",
            timeout=10.0,
            max_retries=3,
            circuit_failure_threshold=5,
            circuit_recovery_timeout=60.0,
        )
        resp = client.get("/policies/POL-001")
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        timeout: float = 15.0,
        max_retries: int = 3,
        retry_min_wait: float = 1.0,
        retry_max_wait: float = 10.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_header = auth_header
        self._auth_value = auth_value
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_min_wait = retry_min_wait
        self._retry_max_wait = retry_max_wait
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_timeout = circuit_recovery_timeout
        self._lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._circuit_open = False
        self._http_client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Return shared HTTP client, creating lazily for connection reuse."""
        if self._http_client is not None:
            return self._http_client
        with self._client_lock:
            if self._http_client is None:
                self._http_client = httpx.Client(
                    timeout=self._timeout,
                    headers=self._build_headers(),
                )
            return self._http_client

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._auth_value:
            headers[self._auth_header] = self._auth_value
        return headers

    def _record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._circuit_failure_threshold:
                self._circuit_open = True
                logger.warning(
                    "Adapter circuit breaker opened after %d failures",
                    self._failure_count,
                )

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._circuit_open = False

    def _check_circuit(self) -> None:
        with self._lock:
            if not self._circuit_open:
                return
            if self._last_failure_time is None:
                return
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._circuit_recovery_timeout:
                logger.info("Adapter circuit breaker half-open (recovery timeout elapsed)")
                self._circuit_open = False
                self._failure_count = 0
            else:
                raise CircuitOpenError(
                    f"Circuit breaker open; retry after {self._circuit_recovery_timeout - elapsed:.0f}s"
                )

    def _is_retryable_response(self, response: httpx.Response) -> bool:
        return response.status_code in RETRYABLE_STATUS_CODES

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self._check_circuit()
        url = f"{self._base_url}{path}" if path.startswith("/") else f"{self._base_url}/{path}"
        
        retryer = Retrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1.0, min=self._retry_min_wait, max=self._retry_max_wait),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS)
            | retry_if_exception(_is_retryable_http_error),
            reraise=True,
        )
        
        for attempt in retryer:
            with attempt:
                try:
                    client = self._get_client()
                    resp = client.request(
                        method,
                        url,
                        headers=self._build_headers(),
                        params=params,
                        json=json,
                    )
                    if self._is_retryable_response(resp):
                        self._record_failure()
                        resp.raise_for_status()
                    resp.raise_for_status()
                    self._record_success()
                    return resp
                except RETRYABLE_EXCEPTIONS:
                    self._record_failure()
                    raise
        raise RuntimeError("Retry loop exited without return or exception")

    def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET request with retry and circuit breaker."""
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST request with retry and circuit breaker."""
        return self._request("POST", path, params=params, json=json)

    def health_check(self, path: str = "/health") -> tuple[bool, str]:
        """Probe the base URL for liveness. Returns (ok, message)."""
        try:
            self._check_circuit()
        except CircuitOpenError as e:
            return False, str(e)
        url = self._base_url.rstrip("/")
        if not url:
            return False, "base_url is empty"
        probe = f"{url}{path}" if path.startswith("/") else f"{url}/{path}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(probe, headers=self._build_headers())
            if resp.status_code in (200, 204):
                return True, "ok"
            return False, f"status={resp.status_code}"
        except Exception as e:
            return False, str(e)
