"""
Admin router — privileged server management operations.

POST /api/v2/admin/atomics/reload   Full wipe + re-import of all Atomic Red Team scripts
GET  /api/v2/admin/atomics/status   Show atomic loader stats from last run
"""
import logging
from fastapi import APIRouter, Header, HTTPException
from pathlib import Path

from config import settings

log = logging.getLogger("morgana.routers.admin")
router = APIRouter()

# In-memory last-run stats (updated by reload endpoint)
_last_stats: dict = {}


@router.post("/atomics/reload")
def reload_atomics(x_api_key: str = Header(...)):
    """
    Wipe all atomic-red-team scripts from DB and re-import from disk.
    Run this after updating the Atomic Red Team submodule.
    Requires the admin API key.
    """
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not settings.atomic_path or not Path(settings.atomic_path).exists():
        raise HTTPException(status_code=503, detail="Atomic Red Team path not configured or not found")

    log.info("[ADMIN] Full atomic reload requested")

    from core.atomic_loader import AtomicLoader
    loader = AtomicLoader(settings.atomic_path)
    stats = loader.reload_all()

    global _last_stats
    _last_stats = stats

    log.info("[ADMIN] Reload complete: %s", stats)
    return {"status": "ok", "stats": stats}


@router.get("/atomics/status")
def atomic_status(x_api_key: str = Header(...)):
    """Return stats from the last atomic import run."""
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    from database import SessionLocal
    from models.script import Script

    db = SessionLocal()
    try:
        total_atomic = db.query(Script).filter(Script.source == "atomic-red-team").count()
        total_custom = db.query(Script).filter(Script.source == "custom").count()
    finally:
        db.close()

    atomic_path = Path(settings.atomic_path) if settings.atomic_path else None
    yaml_count = len(list(atomic_path.rglob("T*.yaml"))) if atomic_path and atomic_path.exists() else 0

    return {
        "atomic_scripts_in_db": total_atomic,
        "custom_scripts_in_db": total_custom,
        "yaml_files_on_disk": yaml_count,
        "last_run_stats": _last_stats,
    }
