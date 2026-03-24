"""FastAPI application for the Claims System Observability & Documentation UI.

Provides REST API endpoints for:
- Claims data (listing, detail, audit log, workflow runs, statistics)
- Observability metrics (global and per-claim)
- Documentation browsing (markdown docs and agent skills)
- System configuration and health

Security: When API_KEYS, CLAIMS_API_KEY, or JWT_SECRET is set, all /api/* endpoints
require auth except /api/health, /api/portal/*, /api/repair-portal/*, /api/third-party-portal/*, /api/auth/login,
and /api/auth/refresh.
Pass via X-API-Key header or Authorization: Bearer <key>. Leave unset for local/dev.
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
from claim_agent.api.routes.reserve_reports import router as reserve_reports_router
from claim_agent.api.routes.retention import router as retention_router
from claim_agent.api.routes.privacy import router as privacy_router
from claim_agent.api.routes.auth_routes import router as auth_login_router
from claim_agent.api.routes.users import router as users_admin_router
from claim_agent.api.routes.repair_shop_users import router as repair_shop_users_router
from claim_agent.api.routes.note_templates import router as note_templates_router
from claim_agent.config import get_settings
from claim_agent.db.database import ensure_fresh_db_on_startup, is_postgres_backend
from claim_agent.diary.auto_create import ensure_diary_listener_registered
from claim_agent.events import ensure_webhook_listener_registered
from claim_agent.exceptions import InvalidClaimTransitionError
from claim_agent.scheduler import ensure_scheduler_running, stop_scheduler

import logging

_server_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if is_postgres_backend() and get_settings().paths.run_migrations_on_startup:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini")
        command.upgrade(alembic_cfg, "head")
    elif not is_postgres_backend():
        ensure_fresh_db_on_startup()
    ensure_webhook_listener_registered()
    ensure_diary_listener_registered()
    ensure_scheduler_running()

    if not get_settings().paths.redis_url:
        _server_logger.warning(
            "Rate limiting uses in-memory storage (REDIS_URL not set). "
            "Not shared across workers. For production, set REDIS_URL and pip install -e '.[redis]'."
        )

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
        await asyncio.gather(*claim_background_tasks)

    await stop_scheduler()

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
        docs_url="/api/openapi/docs",
        redoc_url="/api/openapi/redoc",
        openapi_url="/api/openapi.json",
    )

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.auth.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def _invalid_claim_transition_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        assert isinstance(exc, InvalidClaimTransitionError)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": str(exc),
                "claim_id": exc.claim_id,
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "reason": exc.reason,
            },
        )

    _app.add_exception_handler(InvalidClaimTransitionError, _invalid_claim_transition_handler)

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


_PUBLIC_PATHS = ("/api/health", "/health", "/healthz", "/metrics")


def _is_portal_path(path: str) -> bool:
    """True if path is under /api/portal (uses claimant verification, not bearer auth)."""
    return path.startswith("/api/portal")


def _is_repair_portal_path(path: str) -> bool:
    """True if path is under /api/repair-portal (repair shop token, not bearer auth)."""
    return path.startswith("/api/repair-portal")


def _is_third_party_portal_path(path: str) -> bool:
    """True if path is under /api/third-party-portal (third-party token, not bearer auth)."""
    return path.startswith("/api/third-party-portal")


def _is_auth_public_path(path: str) -> bool:
    """Login and refresh do not require a bearer token."""
    return path in ("/api/auth/login", "/api/auth/refresh")


def _normalize_path(path: str) -> str:
    """Strip trailing slash for consistent path matching (e.g. /api/health/ -> /api/health)."""
    return path.rstrip("/") or "/"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit API routes: 100 req/min per IP; login/refresh use 20 req/min per IP."""
    path = _normalize_path(request.url.path)
    if path.startswith("/api/") and path not in _PUBLIC_PATHS:
        settings = get_settings()
        ip = get_client_ip(request, trust_forwarded_for=settings.auth.trust_forwarded_for)
        limited = (
            is_auth_rate_limited(ip)
            if _is_auth_public_path(path)
            else is_rate_limited(ip)
        )
        if limited:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Verify auth when configured. Set request.state.auth on success."""
    path = _normalize_path(request.url.path)
    if (
        not path.startswith("/api/")
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
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )

    ctx = verify_token(token)
    if ctx is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
        )

    request.state.auth = ctx
    return await call_next(request)


def _health_response():
    """Return health check response with appropriate status code."""
    result = check_health()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)


@app.get("/api/health")
@app.get("/api/health/")
async def health():
    """Production health check: DB (required), optional LLM. Returns 503 if DB down."""
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


# Register API routes
app.include_router(claims_router, prefix="/api")
app.include_router(compliance_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(docs_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(simulation_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(dsar_router, prefix="/api")
app.include_router(portal_router, prefix="/api")
app.include_router(repair_portal_router, prefix="/api")
app.include_router(third_party_portal_router, prefix="/api")
app.include_router(reserve_reports_router, prefix="/api")
app.include_router(retention_router, prefix="/api")
app.include_router(privacy_router, prefix="/api")
app.include_router(auth_login_router, prefix="/api")
app.include_router(users_admin_router, prefix="/api")
app.include_router(repair_shop_users_router, prefix="/api")
app.include_router(note_templates_router, prefix="/api")


# Serve frontend static files in production (when built)
# Must be after API routes so /api/* paths are handled first
_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
