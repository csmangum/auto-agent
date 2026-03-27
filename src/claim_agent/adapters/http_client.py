"""HTTP client for real adapters: auth, retry, circuit breaker.

Use this module when building REST-based adapters (policy, valuation, etc.)
to ensure consistent authentication, transient-error retry, and circuit
breaker behavior.
"""

import logging
import threading
import time
from typing import Any, Callable

import httpx
from claim_agent.observability.adapter_metrics import record_adapter_http_request
from tenacity import (
    Retrying,
    RetryError,
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


def safe_adapter_json_dict(resp: httpx.Response, *, log_label: str = "adapter") -> dict[str, Any] | None:
    """Parse JSON body; return ``None`` if missing, invalid, or not a JSON object."""
    try:
        data = resp.json()
    except ValueError:
        logger.warning("%s: response body is not valid JSON (status=%s)", log_label, resp.status_code)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "%s: JSON root is not an object (status=%s, type=%s)",
            log_label,
            resp.status_code,
            type(data).__name__,
        )
        return None
    return data


def extract_response_envelope(raw: Any, response_key: str | None) -> Any:
    """If *raw* is a dict and a non-empty *response_key* is present in it, return that value.

    Otherwise return *raw* unchanged. Used by REST adapters for optional JSON envelopes
    (e.g. ``{"data": {...}}``).
    """
    if not isinstance(raw, dict):
        return raw
    key = (response_key or "").strip()
    if key and key in raw:
        return raw[key]
    return raw


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open (too many failures)."""


def _status_class_from_http_status(code: int) -> str:
    if 100 <= code < 600:
        return f"{code // 100}xx"
    return "error"


def _status_class_from_exception(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        code = resp.status_code if resp is not None else 0
        return _status_class_from_http_status(code)
    return "error"


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
        adapter_name: str = "unknown",
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
        self._adapter_name = (adapter_name or "unknown").strip() or "unknown"

    def _get_client(self) -> httpx.Client:
        """Return shared HTTP client, creating lazily for connection reuse."""
        if self._http_client is not None:
            return self._http_client
        with self._client_lock:
            if self._http_client is None:
                # Do not set auth/default headers on the client; each request passes
                # ``_build_headers()`` once to avoid duplicate Authorization values.
                self._http_client = httpx.Client(timeout=self._timeout)
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

    def _execute_logical_request(
        self,
        method: str,
        path: str,
        *,
        request_callable: Callable[[httpx.Client], httpx.Response],
    ) -> httpx.Response:
        """Run retry + circuit breaker for one logical HTTP request; record Prometheus metrics."""
        t0 = time.perf_counter()
        try:
            self._check_circuit()
        except CircuitOpenError:
            record_adapter_http_request(
                adapter_name=self._adapter_name,
                method=method,
                duration_seconds=time.perf_counter() - t0,
                status_class="circuit_open",
            )
            raise

        retryer = Retrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=1.0, min=self._retry_min_wait, max=self._retry_max_wait),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS)
            | retry_if_exception(_is_retryable_http_error),
            reraise=False,
        )

        try:
            for attempt in retryer:
                with attempt:
                    client = self._get_client()
                    resp = request_callable(client)
                    if self._is_retryable_response(resp):
                        resp.raise_for_status()
                    resp.raise_for_status()
                    self._record_success()
                    elapsed = time.perf_counter() - t0
                    record_adapter_http_request(
                        adapter_name=self._adapter_name,
                        method=method,
                        duration_seconds=elapsed,
                        status_class=_status_class_from_http_status(resp.status_code),
                    )
                    return resp
        except RetryError as re:
            last_exc = re.last_attempt.exception()
            elapsed = time.perf_counter() - t0
            status_class = (
                _status_class_from_exception(last_exc) if last_exc is not None else "error"
            )
            # Client errors (4xx) are not upstream "outages"; do not trip the circuit.
            if isinstance(last_exc, httpx.HTTPStatusError) and last_exc.response is not None:
                if last_exc.response.status_code < 500:
                    record_adapter_http_request(
                        adapter_name=self._adapter_name,
                        method=method,
                        duration_seconds=elapsed,
                        status_class=status_class,
                    )
                    raise last_exc from re
            self._record_failure()
            record_adapter_http_request(
                adapter_name=self._adapter_name,
                method=method,
                duration_seconds=elapsed,
                status_class=status_class,
            )
            if last_exc is not None:
                raise last_exc from re
            raise RuntimeError("Retry loop exited without return or exception") from re
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            status_class = _status_class_from_exception(exc)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                if exc.response.status_code < 500:
                    record_adapter_http_request(
                        adapter_name=self._adapter_name,
                        method=method,
                        duration_seconds=elapsed,
                        status_class=status_class,
                    )
                    raise
            self._record_failure()
            record_adapter_http_request(
                adapter_name=self._adapter_name,
                method=method,
                duration_seconds=elapsed,
                status_class=status_class,
            )
            raise

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}" if path.startswith("/") else f"{self._base_url}/{path}"

        def _do(client: httpx.Client) -> httpx.Response:
            return client.request(
                method,
                url,
                headers=self._build_headers(),
                params=params,
                json=json,
            )

        return self._execute_logical_request(method, path, request_callable=_do)

    def _request_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST multipart with the same retry and circuit-breaker behavior as JSON POST."""
        url = f"{self._base_url}{path}" if path.startswith("/") else f"{self._base_url}/{path}"

        def _do(client: httpx.Client) -> httpx.Response:
            return client.request(
                "POST",
                url,
                headers=self._build_headers(),
                params=params,
                files=files,
            )

        return self._execute_logical_request("POST", path, request_callable=_do)

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

    def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST multipart/form-data with retry and circuit breaker.

        Pass *files* as httpx expects, e.g. ``{"file": ("name.pdf", file_bytes)}``.
        File contents should be bytes (or a fresh file-like) so retries can resend safely.
        """
        return self._request_multipart(path, files=files, params=params)

    def _probe_health_path(self, path: str) -> tuple[bool, str, int | None]:
        """HTTP liveness probe for *path*.

        Returns:
            (ok, message, http_status_code) where *http_status_code* is set when an HTTP
            response was received (success or error status); ``None`` for circuit open,
            empty base URL, or transport errors.
        """
        try:
            self._check_circuit()
        except CircuitOpenError as e:
            return False, str(e), None
        url = self._base_url.rstrip("/")
        if not url:
            return False, "base_url is empty", None
        probe = f"{url}{path}" if path.startswith("/") else f"{url}/{path}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(probe, headers=self._build_headers())
            code = resp.status_code
            if code in (200, 204):
                return True, "ok", code
            return False, f"status={code}", code
        except Exception as e:
            return False, str(e), None

    def health_check(self, path: str = "/health") -> tuple[bool, str]:
        """Probe the base URL for liveness. Returns (ok, message)."""
        ok, msg, _ = self._probe_health_path(path)
        return ok, msg

    def health_check_with_fallback(self, primary_path: str = "/health") -> tuple[bool, str]:
        """Probe *primary_path* (default ``/health``) then ``/`` if the probe returns 404."""
        ok, msg, status = self._probe_health_path(primary_path)
        if not ok and status == 404:
            ok, msg, _ = self._probe_health_path("/")
        return ok, msg
