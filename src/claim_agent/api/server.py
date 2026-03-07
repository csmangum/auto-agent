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
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from claim_agent.api.auth import is_auth_required, verify_token
from claim_agent.observability.health import check_health, is_healthy
from claim_agent.observability.prometheus import generate_metrics
from claim_agent.api.rate_limit import get_client_ip, is_rate_limited
from claim_agent.api.routes.claims import router as claims_router
from claim_agent.api.routes.claims import _background_tasks as claim_background_tasks
from claim_agent.api.routes.metrics import router as metrics_router
from claim_agent.api.routes.docs import router as docs_router
from claim_agent.api.routes.system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Shutdown: wait for in-flight claim workflow tasks to complete
    if claim_background_tasks:
        await asyncio.gather(*claim_background_tasks)


app = FastAPI(
    title="Claims System Observability UI",
    description="API for the Agentic Claims Processing System dashboard",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/openapi/docs",
    redoc_url="/api/openapi/redoc",
    openapi_url="/api/openapi.json",
)

# CORS: use CORS_ORIGINS env var for production, default to localhost for dev
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
_cors_origins_str = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS = (
    [o.strip() for o in _cors_origins_str.split(",") if o.strip()]
    if _cors_origins_str
    else _default_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_token(request: Request) -> str | None:
    """Extract token from X-API-Key or Authorization: Bearer."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


_UNRATE_LIMITED_PATHS = ("/api/health", "/health", "/healthz", "/metrics")


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit API routes: 100 req/min per IP."""
    path = request.url.path
    if path.startswith("/api/") and path not in _UNRATE_LIMITED_PATHS:
        ip = get_client_ip(request)
        if is_rate_limited(ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


_UNAUTH_PATHS = ("/api/health", "/health", "/healthz", "/metrics")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Verify auth when configured. Set request.state.auth on success."""
    path = request.url.path
    if not path.startswith("/api/") or path in _UNAUTH_PATHS:
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
    status_code = 200 if is_healthy() else 503
    return JSONResponse(content=result, status_code=status_code)


@app.get("/api/health")
async def health():
    """Production health check: DB (required), optional LLM. Returns 503 if DB down."""
    return _health_response()


@app.get("/health")
@app.get("/healthz")
async def health_aliases():
    """Health check aliases for k8s/load balancers."""
    return _health_response()


@app.get("/metrics")
async def metrics():
    """Prometheus metrics scrape endpoint."""
    return Response(
        content=generate_metrics(),
        media_type="text/plain; charset=utf-8",
    )


# Register API routes
app.include_router(claims_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(docs_router, prefix="/api")
app.include_router(system_router, prefix="/api")


# Serve frontend static files in production (when built)
# Must be after API routes so /api/* paths are handled first
_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
