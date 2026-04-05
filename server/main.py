"""
Morgana Server - Main entry point
FastAPI application serving:
  - /api/v2/merlino/*  -> Merlino integration API
  - /api/v2/agent/*    -> Agent communication API
  - /ui                -> Web UI (static files)
"""

import json
import logging
import logging.handlers
import asyncio
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
from routers.admin import router as admin_router
from routers.tags import router as tags_router
from routers.jobs import router as jobs_router
from routers.console import router as console_router
from core.atomic_loader import AtomicLoader

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record — consistent with the Go agent format."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _setup_logging() -> None:
    """Configure root logging: JSON format, rotating file, level from env."""
    level_name = os.getenv("MORGANA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = _JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    # Only add the stream handler when running in an interactive terminal.
    # When launched via Start-Process -RedirectStandardOutput, stdout is already
    # a file handle pointing at the log file. Adding a second RotatingFileHandler
    # on the same path causes Windows file-lock conflicts that silently kill the process.
    if sys.stdout.isatty():
        root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Quieten noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


_setup_logging()
log = logging.getLogger("morgana.server")



async def _stale_agent_monitor() -> None:
    """Background task: mark agents offline when they stop beaconing.

    Runs every 15 seconds. An agent is considered stale when its last_seen
    timestamp is older than max(beacon_interval * 3, 30) seconds.
    """
    from database import SessionLocal
    from models.agent import Agent as AgentModel
    from datetime import datetime as _dt

    while True:
        await asyncio.sleep(15)
        try:
            db = SessionLocal()
            try:
                now = _dt.utcnow()
                live = db.query(AgentModel).filter(AgentModel.status != "offline").all()
                changed = 0
                for ag in live:
                    if ag.last_seen is None:
                        ag.status = "offline"
                        changed += 1
                        continue
                    threshold = max((ag.beacon_interval or 30) * 3, 30)
                    if (now - ag.last_seen).total_seconds() > threshold:
                        ag.status = "offline"
                        changed += 1
                if changed:
                    db.commit()
                    log.info("[MONITOR] Marked %d stale agent(s) offline", changed)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("[MONITOR] Stale agent check failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[START] Morgana Server v%s", settings.version)
    log.info("[START] Database: %s", settings.db_path)

    init_db()
    log.info("[START] Database initialized")

    if settings.atomic_path and Path(settings.atomic_path).exists():
        loader = AtomicLoader(settings.atomic_path)
        stats = loader.load_all()
        log.info(
            "[START] Atomic Red Team — loaded=%d updated=%d skipped=%d errors=%d",
            stats["loaded"], stats["updated"], stats["skipped"], stats["errors"],
        )
        fixed = loader.fix_tactics()
        if fixed:
            log.info("[START] Tactic backfill: updated %d scripts", fixed)
        # Share boot stats with admin router
        import routers.admin as _admin_router
        _admin_router._last_stats = stats
    else:
        log.warning("[START] Atomic Red Team path not configured or not found: %s", settings.atomic_path)

    log.info("[START] Morgana Server ready on port %d", settings.port)
    _monitor_task = asyncio.create_task(_stale_agent_monitor())
    log.info("[MONITOR] Stale agent monitor started")
    yield
    _monitor_task.cancel()
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

# Admin (reload atomics, status)
app.include_router(admin_router, prefix="/api/v2/admin", tags=["admin"])

# Tags (entity labeling + workspaces + selectors)
app.include_router(tags_router, prefix="/api/v2/tags", tags=["tags"])

# Users management
from routers.users import router as users_router
app.include_router(users_router, prefix="/api/v2/users", tags=["users"])

# Auth (register / login / activate / reset)
from routers.auth import router as auth_router
app.include_router(auth_router, prefix="/api/v2/auth", tags=["auth"])

# Jobs (output polling)
app.include_router(jobs_router, prefix="/api/v2/jobs", tags=["jobs"])

# Tests CRUD + delete
from routers.tests import router as tests_router
app.include_router(tests_router, prefix="/api/v2/tests", tags=["tests"])

# Console (WebSocket reverse shell broker)
app.include_router(console_router, prefix="/api/v2/console", tags=["console"])

# Chains (visual flow builder + execution engine)
from routers.chains import router as chains_router
app.include_router(chains_router, prefix="/api/v2/chains", tags=["chains"])

# API Key management (create / list / revoke)
from routers.api_keys import router as api_keys_router
app.include_router(api_keys_router, prefix="/api/v2/api-keys", tags=["api-keys"])

# Deploy (one-liner install scripts + binary download)
from routers.deploy import router as deploy_router
app.include_router(deploy_router, tags=["deploy"])

# Campaigns (sequence of Chains with parallel support)
from routers.campaigns import router as campaigns_router
app.include_router(campaigns_router, prefix="/api/v2/campaigns", tags=["campaigns"])

# Serve web UI
ui_path = Path(__file__).parent.parent / "ui"
if ui_path.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="ui")


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.version}


@app.get("/login")
async def login_page():
    """Convenience redirect: /login -> /ui/login.html"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/login.html", status_code=302)


@app.get("/")
async def root_redirect():
    """Root redirect to UI dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/", status_code=302)


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
