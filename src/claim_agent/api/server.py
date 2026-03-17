"""FastAPI application for the Claims System Observability & Documentation UI.

Provides REST API endpoints for:
- Claims data (listing, detail, audit log, workflow runs, statistics)
- Observability metrics (global and per-claim)
- Documentation browsing (markdown docs and agent skills)
- System configuration and health

Security: When API_KEYS, CLAIMS_API_KEY, or JWT_SECRET is set, all /api/* endpoints
require auth. Pass via X-API-Key header or Authorization: Bearer <key>. Leave unset for local/dev.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from claim_agent.api.auth import is_auth_required, verify_token
from claim_agent.observability.health import check_health
from claim_agent.observability.prometheus import generate_metrics
from claim_agent.api.rate_limit import get_client_ip, is_rate_limited
from claim_agent.api.routes.claims import router as claims_router
from claim_agent.api.routes.claims import _background_tasks as claim_background_tasks
from claim_agent.api.routes.metrics import router as metrics_router
from claim_agent.api.routes.docs import router as docs_router
from claim_agent.api.routes.system import router as system_router
from claim_agent.api.routes.simulation import router as simulation_router
from claim_agent.api.routes.chat import router as chat_router
from claim_agent.api.routes.tasks import router as tasks_router
from claim_agent.api.routes.payments import router as payments_router
from claim_agent.api.routes.webhooks import router as webhooks_router
from claim_agent.config import get_settings
from claim_agent.db.database import ensure_fresh_db_on_startup
from claim_agent.diary.auto_create import ensure_diary_listener_registered
from claim_agent.events import ensure_webhook_listener_registered

import logging

_server_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_fresh_db_on_startup()
    ensure_webhook_listener_registered()
    ensure_diary_listener_registered()

    _server_logger.warning(
        "Rate limiting and approve locks use in-memory storage. "
        "These are NOT shared across workers or processes. "
        "Run with a single worker or use Redis-backed alternatives for production."
    )

    _otel_enabled = False
    try:
        from claim_agent.observability.opentelemetry_setup import setup_opentelemetry, instrument_fastapi
        if setup_opentelemetry():
            instrument_fastapi(_app)
            _otel_enabled = True
    except ImportError:
        pass

    yield

    if claim_background_tasks:
        await asyncio.gather(*claim_background_tasks)

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


def _normalize_path(path: str) -> str:
    """Strip trailing slash for consistent path matching (e.g. /api/health/ -> /api/health)."""
    return path.rstrip("/") or "/"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit API routes: 100 req/min per IP."""
    path = _normalize_path(request.url.path)
    if path.startswith("/api/") and path not in _PUBLIC_PATHS:
        settings = get_settings()
        ip = get_client_ip(request, trust_forwarded_for=settings.auth.trust_forwarded_for)
        if is_rate_limited(ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Verify auth when configured. Set request.state.auth on success."""
    path = _normalize_path(request.url.path)
    if not path.startswith("/api/") or path in _PUBLIC_PATHS:
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
app.include_router(metrics_router, prefix="/api")
app.include_router(docs_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(simulation_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")


# Serve frontend static files in production (when built)
# Must be after API routes so /api/* paths are handled first
_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
