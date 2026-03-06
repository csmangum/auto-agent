"""FastAPI application for the Claims System Observability & Documentation UI.

Provides REST API endpoints for:
- Claims data (listing, detail, audit log, workflow runs, statistics)
- Observability metrics (global and per-claim)
- Documentation browsing (markdown docs and agent skills)
- System configuration and health
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from claim_agent.api.routes.claims import router as claims_router
from claim_agent.api.routes.metrics import router as metrics_router
from claim_agent.api.routes.docs import router as docs_router
from claim_agent.api.routes.system import router as system_router

app = FastAPI(
    title="Claims System Observability UI",
    description="API for the Agentic Claims Processing System dashboard",
    version="1.0.0",
)

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(claims_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(docs_router, prefix="/api")
app.include_router(system_router, prefix="/api")


# Serve frontend static files in production (when built)
_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


@app.get("/api/health")
async def health():
    """Quick health check."""
    return {"status": "ok"}
