"""
Morgana Server - Main entry point
FastAPI application serving:
  - /api/v2/merlino/*  -> Merlino integration API
  - /api/v2/agent/*    -> Agent communication API
  - /ui                -> Web UI (static files)
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db
from routers.merlino import synchronize, realtime, ops_graph
from routers.agent import poll, register, result, heartbeat
from routers.scripts import router as scripts_router
from core.atomic_loader import AtomicLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.log_file, encoding="utf-8"),
    ],
)
log = logging.getLogger("morgana.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[START] Morgana Server v%s", settings.version)
    log.info("[START] Database: %s", settings.db_path)

    init_db()
    log.info("[START] Database initialized")

    if settings.atomic_path and Path(settings.atomic_path).exists():
        loader = AtomicLoader(settings.atomic_path)
        count = loader.load_all()
        log.info("[START] Loaded %d Atomic Red Team scripts", count)
    else:
        log.warning("[START] Atomic Red Team path not configured or not found: %s", settings.atomic_path)

    log.info("[START] Morgana Server ready on port %d", settings.port)
    yield
    log.info("[STOP] Morgana Server shutting down")


app = FastAPI(
    title="Morgana",
    description="Morgana Red Team Platform - X3M.AI",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Merlino integration routes
app.include_router(synchronize.router, prefix="/api/v2/merlino", tags=["merlino"])
app.include_router(realtime.router, prefix="/api/v2/merlino", tags=["merlino"])
app.include_router(ops_graph.router, prefix="/api/v2/merlino", tags=["merlino"])

# Agent communication routes
app.include_router(register.router, prefix="/api/v2/agent", tags=["agent"])
app.include_router(poll.router, prefix="/api/v2/agent", tags=["agent"])
app.include_router(result.router, prefix="/api/v2/agent", tags=["agent"])
app.include_router(heartbeat.router, prefix="/api/v2/agent", tags=["agent"])

# Caldera-compat agent list (Merlino checks this before sync)
from routers.compat import agents as compat_agents
app.include_router(compat_agents.router, prefix="/api/v2", tags=["compat"])

# Scripts CRUD
app.include_router(scripts_router, prefix="/api/v2/scripts", tags=["scripts"])

# Serve web UI
ui_path = Path(__file__).parent.parent / "ui"
if ui_path.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="ui")


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.version}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        ssl_keyfile=settings.ssl_keyfile if settings.ssl_enabled else None,
        ssl_certfile=settings.ssl_certfile if settings.ssl_enabled else None,
        reload=settings.debug,
        log_level="info",
    )
