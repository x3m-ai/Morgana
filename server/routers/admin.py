"""
Admin router — privileged server management operations.

POST /api/v2/admin/atomics/reload   Full wipe + re-import of all Atomic Red Team scripts
GET  /api/v2/admin/atomics/status   Show atomic loader stats from last run
GET  /api/v2/admin/settings         Read global server settings
PUT  /api/v2/admin/settings         Update global server settings (default_beacon_interval, dns_name, ...)
GET  /api/v2/admin/server-info      Return hostname, IP, memory, disk info
"""
import json
import logging
import platform
import shutil
import socket
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from config import settings

log = logging.getLogger("morgana.routers.admin")
router = APIRouter()

# In-memory last-run stats (updated by reload endpoint)
_last_stats: dict = {}

# Persistent global settings file (survives restarts)
_SETTINGS_FILE = Path(settings.db_path).parent / "server-settings.json"


def _load_server_settings() -> dict:
    """Return persisted global settings, falling back to config.py defaults."""
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"default_beacon_interval": settings.default_beacon_interval}


def _save_server_settings(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    """Accept the master env-var key or any DB-stored key."""
    if not key:
        raise HTTPException(status_code=401, detail="API key required")
    if key == settings.api_key:
        return
    import hashlib
    from database import SessionLocal
    from models.api_key import ApiKey
    khash = hashlib.sha256(key.encode()).hexdigest()
    _db = SessionLocal()
    try:
        row = _db.query(ApiKey).filter(ApiKey.key_hash == khash).first()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid API key")
    finally:
        _db.close()


# ─── Global settings endpoints ────────────────────────────────────────────────

class ServerSettingsBody(BaseModel):
    default_beacon_interval: Optional[int] = None  # seconds, 5-3600
    dns_name: Optional[str] = None                 # public DNS name (empty string = clear)


@router.get("/settings")
def get_server_settings(key: Optional[str] = Header(None, alias="KEY")):
    """Return current global server settings."""
    _require_api_key(key)
    return _load_server_settings()


@router.put("/settings")
def put_server_settings(body: ServerSettingsBody, key: Optional[str] = Header(None, alias="KEY")):
    """Persist global server settings. Changes take effect for newly enrolled agents."""
    _require_api_key(key)
    data = _load_server_settings()
    if body.default_beacon_interval is not None:
        if not (5 <= body.default_beacon_interval <= 3600):
            raise HTTPException(status_code=400, detail="beacon_interval must be between 5 and 3600 seconds")
        data["default_beacon_interval"] = body.default_beacon_interval
        settings.default_beacon_interval = body.default_beacon_interval  # in-memory update
    if body.dns_name is not None:
        data["dns_name"] = body.dns_name.strip()
    _save_server_settings(data)
    log.info("[ADMIN] Global settings updated: %s", data)
    return data


@router.get("/server-info")
def get_server_info(key: Optional[str] = Header(None, alias="KEY")):
    """Return server hostname, primary IP, memory usage, disk usage, and platform info."""
    _require_api_key(key)

    # Hostname
    hostname = socket.gethostname()

    # Primary IP address (the one used for outbound connections)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            ip_address = socket.gethostbyname(hostname)
        except Exception:
            ip_address = "127.0.0.1"

    # Memory (try psutil, fallback to platform)
    memory_info: dict = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        memory_info = {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
            "used_pct": vm.percent,
        }
    except ImportError:
        memory_info = {"note": "psutil not installed"}

    # Disk (path where morgana DB lives)
    disk_info: dict = {}
    try:
        disk_path = Path(settings.db_path).parent
        disk = shutil.disk_usage(str(disk_path))
        disk_info = {
            "path": str(disk_path),
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "used_pct": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
        }
    except Exception as exc:
        disk_info = {"error": str(exc)}

    # DNS name from persisted settings
    saved = _load_server_settings()

    return {
        "hostname": hostname,
        "ip_address": ip_address,
        "dns_name": saved.get("dns_name", ""),
        "platform": platform.system(),
        "platform_version": platform.version()[:80],
        "python_version": platform.python_version(),
        "server_port": settings.port,
        "memory": memory_info,
        "disk": disk_info,
    }


# ─── Atomic Red Team endpoints ────────────────────────────────────────────────
def reload_atomics(key: Optional[str] = Header(None, alias="KEY")):
    """
    Wipe all atomic-red-team scripts from DB and re-import from disk.
    Run this after updating the Atomic Red Team submodule.
    """
    _require_api_key(key)

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


@router.post("/deploy-token")
def create_deploy_token_endpoint(key: Optional[str] = Header(None, alias="KEY")):
    """Generate a one-time deploy token for agent installation.

    The token is valid for a single agent registration and expires after use.
    Returns the token in the response — pass it as --token to the agent installer.
    """
    _require_api_key(key)
    from routers.agent.register import create_deploy_token
    token = create_deploy_token()
    log.info("[ADMIN] Deploy token generated")
    return {"deploy_token": token}


@router.get("/atomics/status")
def atomic_status(key: Optional[str] = Header(None, alias="KEY")):
    """Return stats from the last atomic import run."""
    _require_api_key(key)

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
