"""FastAPI application for the Claims System Observability & Documentation UI.

Provides REST API endpoints for:
- Claims data (listing, detail, audit log, workflow runs, statistics)
- Observability metrics (global and per-claim)
- Documentation browsing (markdown docs and agent skills)
- System configuration and health

Security: When API_KEYS, CLAIMS_API_KEY, or JWT_SECRET is set, all /api/v1/* endpoints
require auth except /api/v1/health, /api/v1/portal/*, /api/v1/repair-portal/*,
/api/v1/third-party-portal/*, /api/v1/auth/login, and /api/v1/auth/refresh.
Legacy /api/* paths are permanently redirected (308) to /api/v1/*.
Pass via X-API-Key header or Authorization: Bearer <key>. Leave unset for local/dev.
Non-dev deployments (CLAIM_AGENT_ENVIRONMENT) require at least one auth mechanism at startup.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette import status

from claim_agent.api.auth import is_auth_required, verify_token
from claim_agent.api.idempotency import cleanup_expired
from claim_agent.observability.health import check_health
from claim_agent.observability.prometheus import generate_metrics
from claim_agent.api.rate_limit import get_client_ip, is_auth_rate_limited, is_rate_limited
from claim_agent.api.routes.claims import router as claims_router
from claim_agent.api.routes.compliance import router as compliance_router
from claim_agent.api.routes.claims import _background_tasks as claim_background_tasks
from claim_agent.api.routes.claims import _task_claim_ids as claim_task_claim_ids
from claim_agent.api.routes.metrics import router as metrics_router
from claim_agent.api.routes.docs import router as docs_router
from claim_agent.api.routes.system import router as system_router
from claim_agent.api.routes.simulation import router as simulation_router
from claim_agent.api.routes.chat import router as chat_router
from claim_agent.api.routes.tasks import router as tasks_router
from claim_agent.api.routes.payments import router as payments_router
from claim_agent.api.routes.webhooks import router as webhooks_router
from claim_agent.api.routes.dsar import router as dsar_router
from claim_agent.api.routes.portal import router as portal_router
from claim_agent.api.routes.repair_portal import router as repair_portal_router
from claim_agent.api.routes.third_party_portal import router as third_party_portal_router
from claim_agent.api.routes.unified_portal import router as unified_portal_router
from claim_agent.api.routes.reserve_reports import router as reserve_reports_router
from claim_agent.api.routes.retention import router as retention_router
from claim_agent.api.routes.privacy import router as privacy_router
from claim_agent.api.routes.auth_routes import router as auth_login_router
from claim_agent.api.routes.users import router as users_admin_router
from claim_agent.api.routes.repair_shop_users import router as repair_shop_users_router
from claim_agent.api.routes.note_templates import router as note_templates_router
from claim_agent.config import get_settings
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.db.database import ensure_fresh_db_on_startup, get_db_path, is_postgres_backend
from claim_agent.db.repository import ClaimRepository
from claim_agent.diary.auto_create import ensure_diary_listener_registered
from claim_agent.events import ensure_webhook_listener_registered
from claim_agent.api.error_handlers import register_exception_handlers
from claim_agent.config.settings_model import SchedulerConfig

import logging

_server_logger = logging.getLogger(__name__)

# Bytes per MB for request body size checks (see request_body_size_limit_middleware).
_MB = 1024 * 1024

_BODY_LENGTH_REQUIRED_METHODS = frozenset({"POST", "PUT", "PATCH"})


_DEV_ENVIRONMENTS = frozenset({"dev", "development", "test", "testing"})


def _check_auth_configuration() -> None:
    """Refuse to start in non-development environments when no auth is configured.

    When CLAIM_AGENT_ENVIRONMENT (or legacy ENVIRONMENT) is not one of
    dev/development/test/testing and no API_KEYS, CLAIMS_API_KEY, or JWT_SECRET is set,
    the server would grant every caller admin access. Fail fast rather than silently
    expose an unprotected API.
    """
    if is_auth_required():
        return
    env = get_settings().auth.environment.strip().lower()
    if env not in _DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"Authentication is not configured (API_KEYS, CLAIMS_API_KEY, and JWT_SECRET "
            f"are all unset) but CLAIM_AGENT_ENVIRONMENT is set to "
            f"'{get_settings().auth.environment}'. "
            "Configure at least one auth mechanism before deploying, or set "
            "CLAIM_AGENT_ENVIRONMENT=development to allow unauthenticated access in a local dev setup."
        )


def _check_rate_limit_configuration() -> None:
    """Warn in non-development environments when Redis is not configured for rate limiting.

    In-memory rate limiting is not shared across uvicorn workers, so an attacker
    can multiply their request budget by the number of workers. When
    CLAIM_AGENT_ENVIRONMENT is not one of dev/development/test/testing and
    REDIS_URL is unset, emit a warning so operators know to configure Redis before
    going to production.
    """
    if get_settings().paths.redis_url:
        return
    env = get_settings().auth.environment.strip().lower()
    if env not in _DEV_ENVIRONMENTS:
        _server_logger.warning(
            "Rate limiting uses in-memory storage (REDIS_URL not set). "
            "Not shared across workers — each uvicorn worker enforces its own limit, "
            "allowing attackers to multiply their request budget by the worker count. "
            "For production, set REDIS_URL and install the redis extra: "
            "pip install -e '.[redis]'."
        )


def _recover_stuck_processing_claims() -> None:
    """Mark claims stuck in 'processing' as 'needs_review' on startup.

    When the server is restarted while background workflow tasks are in flight, those
    tasks are lost because they live only in memory.  This scan detects claims that are
    still in the 'processing' status after the configured timeout and marks them
    'needs_review' so an adjuster can retrigger or review them.

    Controlled by:
    - ``CLAIM_AGENT_TASK_RECOVERY_ENABLED`` (default true)
    - ``CLAIM_AGENT_TASK_RECOVERY_STUCK_MINUTES`` (default 30)
    """
    settings = get_settings()
    if not settings.task_recovery_enabled:
        return
    stuck_minutes = settings.task_recovery_stuck_minutes
    try:
        repo = ClaimRepository(db_path=get_db_path())
        stuck_claims = repo.get_stuck_processing_claims(stuck_after_minutes=stuck_minutes)
    except Exception:
        _server_logger.exception("Startup recovery scan failed to query stuck processing claims")
        return

    if not stuck_claims:
        _server_logger.debug("Startup recovery: no claims stuck in processing")
        return

    _server_logger.warning(
        "Startup recovery: found %d claim(s) stuck in 'processing' (> %d min). "
        "Marking as 'needs_review'.",
        len(stuck_claims),
        stuck_minutes,
    )
    for claim in stuck_claims:
        claim_id = claim["id"]
        try:
            repo.update_claim_status(
                claim_id,
                STATUS_NEEDS_REVIEW,
                details=(
                    f"Claim was stuck in 'processing' on server restart "
                    f"(exceeded {stuck_minutes}-minute threshold). "
                    "Please review and resubmit for processing."
                ),
                actor_id=ACTOR_WORKFLOW,
                skip_validation=True,
            )
            _server_logger.warning(
                "Startup recovery: claim %s marked 'needs_review'", claim_id
            )
        except Exception:
            _server_logger.exception(
                "Startup recovery: failed to mark claim %s as needs_review", claim_id
            )


def _warn_if_scheduler_enabled_on_api() -> None:
    """Warn when SCHEDULER_ENABLED=true is set on the API server.

    The in-process APScheduler is not safe for multi-worker deployments:
    each Uvicorn/Gunicorn worker or replica pod would run its own copy of
    every cron job, duplicating diary escalations, UCSPA sweeps, and ERP
    polls.  The scheduler should run as a single dedicated process via
    ``claim-agent run-scheduler``.  The API server no longer auto-starts the
    scheduler.
    """
    scheduler_cfg = SchedulerConfig()
    if scheduler_cfg.enabled:
        _server_logger.warning(
            "SCHEDULER_ENABLED=true is set but the API server no longer starts the "
            "in-process scheduler. Run 'claim-agent run-scheduler' as a separate "
            "single-instance process instead. This prevents cron jobs from running "
            "once per API worker in multi-worker deployments. "
            "See docs/configuration.md for details."
        )

async def _shutdown_background_tasks_with_grace(grace_seconds: int) -> None:
    """Wait up to *grace_seconds* for in-flight claim tasks, then cancel the rest.

    Any task still running after the grace period is cancelled. The associated claim
    remains in ``processing`` status so the startup recovery scan will detect it and
    mark it ``needs_review`` on the next server boot.

    Args:
        grace_seconds: Maximum wall-clock seconds to wait before cancellation.
            When 0 the tasks are cancelled immediately without waiting.
    """
    if not claim_background_tasks:
        return

    pending = set(claim_background_tasks)
    _server_logger.info(
        "Graceful shutdown: waiting up to %d s for %d in-flight claim task(s).",
        grace_seconds,
        len(pending),
    )

    if grace_seconds > 0:
        done, pending = await asyncio.wait(pending, timeout=grace_seconds)
        # Log (but do not re-raise) exceptions from tasks that finished during the
        # grace window.  Re-raising would abort the rest of the shutdown sequence,
        # leaving other tasks uncancel-led and their claims in 'processing'.
        for t in done:
            if not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    _server_logger.warning(
                        "Graceful shutdown: task finished with error: %s", exc
                    )

    if not pending:
        _server_logger.info("Graceful shutdown: all claim tasks finished within grace period.")
        return

    _server_logger.warning(
        "Graceful shutdown: %d claim task(s) did not finish within %d s grace period; "
        "cancelling and marking claims as failed (recoverable).",
        len(pending),
        grace_seconds,
    )

    for task in pending:
        claim_id = claim_task_claim_ids.get(task)
        task.cancel()
        if claim_id:
            _server_logger.warning(
                "Graceful shutdown: claim %s interrupted (will be recovered on next startup).",
                claim_id,
            )

    # Await cancelled tasks so their CancelledError is consumed
    await asyncio.gather(*pending, return_exceptions=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _check_auth_configuration()

    _auth_startup = get_settings().auth
    if _auth_startup.enforce_https and not _auth_startup.trust_forwarded_for:
        _server_logger.warning(
            "ENFORCE_HTTPS=true but TRUST_FORWARDED_FOR=false: "
            "HTTP→HTTPS redirect using X-Forwarded-Proto is disabled. "
            "Set TRUST_FORWARDED_FOR=true only when behind a trusted reverse proxy."
        )

    if is_postgres_backend() and get_settings().paths.run_migrations_on_startup:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini")
        command.upgrade(alembic_cfg, "head")
    elif not is_postgres_backend():
        env = get_settings().auth.environment.strip().lower()
        if env not in _DEV_ENVIRONMENTS:
            _server_logger.warning(
                "SQLite is configured as the database backend "
                "(DATABASE_URL is not set). SQLite does not support concurrent writes "
                "and will cause 'database is locked' errors under a multi-worker API "
                "server. It also has no replication, high-availability, or "
                "point-in-time recovery. Set DATABASE_URL to a PostgreSQL connection "
                "string and run 'alembic upgrade head' before going to production. "
                "See docs/database.md for details."
            )
        ensure_fresh_db_on_startup()
    from claim_agent.notifications.claimant import check_notification_readiness

    check_notification_readiness()
    _recover_stuck_processing_claims()
    ensure_webhook_listener_registered()
    ensure_diary_listener_registered()
    _warn_if_scheduler_enabled_on_api()
    _check_rate_limit_configuration()

    _idempotency_cleanup_task: asyncio.Task | None = None
    _idempotency_cleanup_stop = asyncio.Event()

    async def _idempotency_cleanup_loop() -> None:
        """Periodically purge expired idempotency keys (every hour)."""
        interval = 3600
        while not _idempotency_cleanup_stop.is_set():
            try:
                deleted = await asyncio.to_thread(cleanup_expired)
                if deleted:
                    _server_logger.debug("Idempotency cleanup: deleted %d expired keys", deleted)
            except Exception as e:
                _server_logger.warning("Idempotency cleanup failed: %s", e)
            try:
                await asyncio.wait_for(_idempotency_cleanup_stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    _idempotency_cleanup_task = asyncio.create_task(_idempotency_cleanup_loop())

    _otel_enabled = False
    try:
        from claim_agent.observability.opentelemetry_setup import setup_opentelemetry, instrument_fastapi
        if setup_opentelemetry():
            instrument_fastapi(_app)
            _otel_enabled = True
    except ImportError:
        pass

    yield

    if _idempotency_cleanup_task is not None:
        _idempotency_cleanup_stop.set()
        _idempotency_cleanup_task.cancel()
        try:
            await _idempotency_cleanup_task
        except asyncio.CancelledError:
            pass

    if claim_background_tasks:
        await _shutdown_background_tasks_with_grace(
            get_settings().shutdown_grace_period_seconds
        )

    if _otel_enabled:
        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception:
            # Shutdown errors are non-fatal; best-effort flush on exit
            pass


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Usable as a uvicorn factory: ``uvicorn claim_agent.api.server:create_app --factory``
    """
    settings = get_settings()

    _app = FastAPI(
        title="Claims System Observability UI",
        description="API for the Agentic Claims Processing System dashboard",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/v1/openapi/docs",
        redoc_url="/api/v1/openapi/redoc",
        openapi_url="/api/v1/openapi.json",
    )

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.auth.cors_origins,
        allow_credentials=True,
        allow_methods=settings.auth.cors_methods,
        allow_headers=settings.auth.cors_headers,
    )

    register_exception_handlers(_app)

    return _app


app = create_app()


def _get_token(request: Request) -> str | None:
    """Extract token from X-API-Key or Authorization: Bearer."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


_PUBLIC_PATHS = ("/api/v1/health", "/health", "/healthz", "/metrics")


def _is_portal_path(path: str) -> bool:
    """True if path is under /api/v1/portal (uses portal-specific auth, not bearer auth).

    The ``/api/v1/portal/auth/issue-token`` admin endpoint is excluded so it
    falls through to the normal API-key / Bearer-token auth middleware.
    """
    if path.startswith("/api/v1/portal/auth/issue-token"):
        return False
    return path.startswith("/api/v1/portal")


def _is_repair_portal_path(path: str) -> bool:
    """True if path is under /api/v1/repair-portal (repair shop token, not bearer auth)."""
    return path.startswith("/api/v1/repair-portal")


def _is_third_party_portal_path(path: str) -> bool:
    """True if path is under /api/v1/third-party-portal (third-party token, not bearer auth)."""
    return path.startswith("/api/v1/third-party-portal")


def _is_auth_public_path(path: str) -> bool:
    """Login and refresh do not require a bearer token."""
    return path in (
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/repair-portal/auth/login",
        "/api/v1/portal/auth/login",
    )


def _normalize_path(path: str) -> str:
    """Strip trailing slash for consistent path matching (e.g. /api/health/ -> /api/health)."""
    return path.rstrip("/") or "/"


def _base_security_response_headers() -> dict[str, str]:
    """Headers applied to normal and redirect responses (browser hardening)."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": (
            "geolocation=(), microphone=(), camera=(), payment=()"
        ),
        # 'unsafe-inline' is removed from script-src; the theme-init script is served
        # as a static file (/theme-init.js) to avoid inline scripts.
        # 'unsafe-inline' is retained for style-src because React components may apply
        # inline style attributes and Tailwind v4 injects CSS in dev mode.
        # Keep this policy string in sync with frontend/vite.config.ts (document CSP).
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        ),
    }


def _hsts_header_value() -> str | None:
    """Return Strict-Transport-Security value when HTTPS enforcement is enabled."""
    auth_cfg = get_settings().auth
    if not auth_cfg.enforce_https:
        return None
    hsts_value = f"max-age={auth_cfg.hsts_max_age}"
    if auth_cfg.hsts_include_subdomains:
        hsts_value += "; includeSubDomains"
    if auth_cfg.hsts_preload:
        hsts_value += "; preload"
    return hsts_value


def _secured_api_json_response(request: Request, status_code: int, content: dict) -> JSONResponse:
    """JSON error responses with the same hardening as ``security_headers_middleware``.

    Ensures early returns from auth/rate-limit middleware (before ``call_next``) still
    get CSP, frame denial, cache control, and optional HSTS.
    """
    headers = dict(_base_security_response_headers())
    path = _normalize_path(request.url.path)
    cc = _maybe_cache_control_no_store(path)
    if cc:
        headers["Cache-Control"] = cc
    hsts = _hsts_header_value()
    if hsts:
        headers["Strict-Transport-Security"] = hsts
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _maybe_cache_control_no_store(path: str) -> str | None:
    """Return Cache-Control value for API routes except health (see plan)."""
    norm = _normalize_path(path)
    if norm.startswith("/api/v1/") and norm != "/api/v1/health":
        return "no-store"
    return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Verify auth when configured. Set request.state.auth on success."""
    path = _normalize_path(request.url.path)
    if (
        not path.startswith("/api/v1/")
        or path in _PUBLIC_PATHS
        or _is_portal_path(path)
        or _is_repair_portal_path(path)
        or _is_third_party_portal_path(path)
        or _is_auth_public_path(path)
    ):
        return await call_next(request)

    if not is_auth_required():
        return await call_next(request)

    token = _get_token(request)
    if not token:
        return _secured_api_json_response(
            request,
            401,
            {"error_code": "UNAUTHORIZED", "detail": "Invalid or missing API key"},
        )

    ctx = verify_token(token)
    if ctx is None:
        return _secured_api_json_response(
            request,
            401,
            {"error_code": "UNAUTHORIZED", "detail": "Invalid or expired token"},
        )

    request.state.auth = ctx
    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit API routes: 100 req/min per IP; login/refresh use 20 req/min per IP."""
    path = _normalize_path(request.url.path)
    if path.startswith("/api/v1/") and path not in _PUBLIC_PATHS:
        settings = get_settings()
        ip = get_client_ip(request, trust_forwarded_for=settings.auth.trust_forwarded_for)
        limited = (
            is_auth_rate_limited(ip)
            if _is_auth_public_path(path)
            else is_rate_limited(ip)
        )
        if limited:
            return _secured_api_json_response(
                request,
                429,
                {"error_code": "RATE_LIMIT_EXCEEDED", "detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


@app.middleware("http")
async def request_body_size_limit_middleware(request: Request, call_next):
    """Reject requests whose Content-Length exceeds the configured body size limit.

    Applies a 10 MB cap to all non-file-upload endpoints and a 100 MB cap to
    multipart/form-data requests (file uploads).  These limits are configurable
    via MAX_REQUEST_BODY_SIZE_MB and MAX_UPLOAD_BODY_SIZE_MB environment variables.

    The check uses the Content-Length header so that oversized payloads are
    rejected before the body is read into memory.  Route handlers that accept
    file uploads enforce additional per-file limits independently.

    POST/PUT/PATCH under ``/api/v1/`` must send ``Content-Length`` (not chunked
    without a length) so limits cannot be bypassed via ``Transfer-Encoding:
    chunked``.
    """
    path = _normalize_path(request.url.path)
    if not path.startswith("/api/v1/"):
        return await call_next(request)

    method = request.method.upper()
    content_length_header = request.headers.get("content-length")
    if method in _BODY_LENGTH_REQUIRED_METHODS and content_length_header is None:
        return _secured_api_json_response(
            request,
            status.HTTP_411_LENGTH_REQUIRED,
            {"error_code": "LENGTH_REQUIRED", "detail": "Content-Length required"},
        )

    if content_length_header is not None:
        try:
            content_length = int(content_length_header)
        except ValueError:
            return _secured_api_json_response(
                request,
                400,
                {"error_code": "BAD_REQUEST", "detail": "Invalid Content-Length header"},
            )

        if content_length < 0:
            return _secured_api_json_response(
                request,
                400,
                {"error_code": "BAD_REQUEST", "detail": "Invalid Content-Length header"},
            )

        settings = get_settings()
        content_type = request.headers.get("content-type", "").lower()
        if "multipart/form-data" in content_type:
            limit = settings.max_upload_body_size_mb * _MB
        else:
            limit = settings.max_request_body_size_mb * _MB

        if content_length > limit:
            return _secured_api_json_response(
                request,
                413,
                {"error_code": "REQUEST_TOO_LARGE", "detail": "Request body too large"},
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to every response.

    When ENFORCE_HTTPS=true and TRUST_FORWARDED_FOR=true (trusted proxy):
    - HTTP requests (X-Forwarded-Proto: http) get a 307 redirect to HTTPS.

    When ENFORCE_HTTPS=true, Strict-Transport-Security (HSTS) is set on responses.

    Unconditional hardening headers include CSP (default-src 'self').
    """
    settings = get_settings()
    auth_cfg = settings.auth
    path = _normalize_path(request.url.path)

    if (
        auth_cfg.enforce_https
        and auth_cfg.trust_forwarded_for
        and request.headers.get("X-Forwarded-Proto", "").lower() == "http"
    ):
        # Build the redirect URL by only changing the scheme of the current request URL,
        # avoiding direct use of X-Forwarded-Host/Host header values to prevent open redirect.
        https_url = str(request.url.replace(scheme="https"))
        redirect_headers = dict(_base_security_response_headers())
        redirect_headers["Location"] = https_url
        cc = _maybe_cache_control_no_store(path)
        if cc:
            redirect_headers["Cache-Control"] = cc
        return Response(status_code=307, headers=redirect_headers)

    response = await call_next(request)

    for key, value in _base_security_response_headers().items():
        response.headers[key] = value

    cc = _maybe_cache_control_no_store(path)
    if cc:
        response.headers["Cache-Control"] = cc

    hsts = _hsts_header_value()
    if hsts:
        response.headers["Strict-Transport-Security"] = hsts

    return response


@app.middleware("http")
async def api_version_redirect_middleware(request: Request, call_next):
    """Redirect unversioned /api/* requests to /api/v1/* for backward compatibility.

    Clients that still use the legacy /api/ prefix receive a 308 Permanent Redirect
    so they can update their URLs. HTTP 308 preserves the request method (POST, PUT,
    PATCH, DELETE), unlike 301 which causes clients to downgrade to GET. The
    versioned /api/v1/ paths are the canonical API; the legacy paths are kept only
    to avoid silent breakage.
    """
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        versioned = "/api/v1" + path[len("/api"):]
        new_url = request.url.replace(path=versioned)
        return Response(status_code=308, headers={"Location": str(new_url)})
    if path == "/api":
        new_url = request.url.replace(path="/api/v1")
        return Response(status_code=308, headers={"Location": str(new_url)})
    return await call_next(request)


def _health_response():
    """Return health check response with appropriate status code."""
    result = check_health()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)


@app.get("/api/v1/health")
@app.get("/api/v1/health/")
async def health():
    """Production health check: DB (required), optional LLM and notifications. Returns 503 if down."""
    return _health_response()


@app.get("/health")
@app.get("/health/")
@app.get("/healthz")
@app.get("/healthz/")
async def health_aliases():
    """Health check aliases for k8s/load balancers."""
    return _health_response()


@app.get("/metrics")
@app.get("/metrics/")
def metrics():
    """Prometheus metrics scrape endpoint. Sync handler so SQLite queries run in threadpool."""
    return Response(
        content=generate_metrics(),
        media_type="text/plain; charset=utf-8",
    )


# Register API routes (versioned under /api/v1)
app.include_router(claims_router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(docs_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")
app.include_router(simulation_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(dsar_router, prefix="/api/v1")
app.include_router(portal_router, prefix="/api/v1")
app.include_router(unified_portal_router, prefix="/api/v1")
app.include_router(repair_portal_router, prefix="/api/v1")
app.include_router(third_party_portal_router, prefix="/api/v1")
app.include_router(reserve_reports_router, prefix="/api/v1")
app.include_router(retention_router, prefix="/api/v1")
app.include_router(privacy_router, prefix="/api/v1")
app.include_router(auth_login_router, prefix="/api/v1")
app.include_router(users_admin_router, prefix="/api/v1")
app.include_router(repair_shop_users_router, prefix="/api/v1")
app.include_router(note_templates_router, prefix="/api/v1")


# Serve frontend static files in production (when built)
# Must be after API routes so /api/* paths are handled first
_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
