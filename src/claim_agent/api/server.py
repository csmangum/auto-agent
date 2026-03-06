"""FastAPI application for the Claims System Observability & Documentation UI.

Provides REST API endpoints for:
- Claims data (listing, detail, audit log, workflow runs, statistics)
- Observability metrics (global and per-claim)
- Documentation browsing (markdown docs and agent skills)
- System configuration and health

Security: When CLAIMS_API_KEY is set, all /api/* endpoints require API key auth.
Pass via X-API-Key header or Authorization: Bearer <key>. Leave unset for local/dev.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from claim_agent.api.rate_limit import get_client_ip, is_rate_limited
from claim_agent.api.routes.claims import router as claims_router
from claim_agent.api.routes.metrics import router as metrics_router
from claim_agent.api.routes.docs import router as docs_router
from claim_agent.api.routes.system import router as system_router

app = FastAPI(
    title="Claims System Observability UI",
    description="API for the Agentic Claims Processing System dashboard",
    version="1.0.0",
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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit API routes: 100 req/min per IP."""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        ip = get_client_ip(request)
        if is_rate_limited(ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """Require API key when CLAIMS_API_KEY is set.
    Skips /api/health and non-API paths."""
    api_key = os.environ.get("CLAIMS_API_KEY")
    if not api_key:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path == "/api/health":
        return await call_next(request)

    provided = request.headers.get("X-API-Key") or (
        request.headers.get("Authorization") or ""
    ).replace("Bearer ", "").strip()
    if provided != api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )

    return await call_next(request)


@app.get("/api/health")
async def health():
    """Quick health check."""
    return {"status": "ok"}


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
