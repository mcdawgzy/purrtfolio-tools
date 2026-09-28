"""
Trading Tools by Purrtfolio — FastAPI backend.

Read-only API over purrtfolio.db. Single-page drill-down frontend served
from /static/. CORS open for local dev + GitHub Pages (configurable).

Layout: config (env) -> database (connections) -> queries/* (SQL per domain)
-> routers/* (HTTP per domain) -> this module (app assembly).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import CORS_ALLOWED_ORIGINS, STATIC_DIR, get_snapshot_dir
from .errors import install_error_handlers
from .routers import (
    correlation, crowded, earnings, econ, factors, funds, insider, meta, momentum,
    news, options, quotes, screener, short_interest, snapshot,
)
from .scanners import ensure_momentum_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fetch the slim momentum DB (~0.3MB) on cold start so the first
    # momentum/correlation request doesn't have to.
    ensure_momentum_db()
    yield


app = FastAPI(
    title="Trading Tools by Purrtfolio",
    description="Free institutional-ownership + macro market dashboard (SEC EDGAR + FINRA data)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

install_error_handlers(app)

# ---------------------------------------------------------------------------
# API routes (must be registered before the root static mount below)
# ---------------------------------------------------------------------------
for _module in (
    meta, funds, short_interest, insider, econ, options, screener, quotes,
    earnings, snapshot, news, momentum, correlation, factors, crowded,
):
    app.include_router(_module.router)


# ---------------------------------------------------------------------------
# Frontend (single page, served at /)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>Trading Tools by Purrtfolio</h1><p>Frontend not built yet. See <code>static/index.html</code>.</p>",
            status_code=200,
        )
    return FileResponse(idx)


# Serve static assets (CSS, JS) — mounted at /static/ for API compatibility
# and at / for GitHub Pages-style relative URLs (./app.js, ./styles.css).
# Order matters: routes above, then /static, then the catch-all root mount.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    # Root-level static mount for relative paths (./app.js etc.)
    # Placed after /static to avoid shadowing any API routes
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static_root")

# Serve macro market snapshot PNGs
SNAPSHOT_OUT = get_snapshot_dir()
if SNAPSHOT_OUT.exists():
    app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOT_OUT)), name="snapshots")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
