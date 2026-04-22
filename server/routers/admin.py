"""
Admin router — privileged server management operations.

POST /api/v2/admin/atomics/reload   Full wipe + re-import of all Atomic Red Team scripts
GET  /api/v2/admin/atomics/status   Show atomic loader stats from last run
GET  /api/v2/admin/settings         Read global server settings
PUT  /api/v2/admin/settings         Update global server settings (default_beacon_interval, dns_name, log_retention_hours, ...)
GET  /api/v2/admin/server-info      Return hostname, IP, memory, disk info
GET  /api/v2/admin/logs             Return recent log entries (JSONL log file) with filtering
"""
import io
import json
import logging
import platform
import shlex
import shutil
import socket
import ssl
import sys
import threading
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config import settings
from core.auth import require_api_key

log = logging.getLogger("morgana.routers.admin")
router = APIRouter()


def _make_ssl_context() -> ssl.SSLContext:
    """
    SSL context that works in PyInstaller frozen apps (OpenSSL, not SChannel).
    Uses certifi CA bundle when available -- certifi is always bundled because
    httpx depends on it, so this is safe in both dev and frozen builds.
    Falls back to ssl.create_default_context() which works on non-frozen builds.
    """
    try:
        import certifi as _certifi
        return ssl.create_default_context(cafile=_certifi.where())
    except Exception:
        pass
    ctx = ssl.create_default_context()
    # On Windows non-frozen builds, additionally load from the system store
    if sys.platform == "win32":
        try:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        except Exception:
            pass
    return ctx

# In-memory last-run stats (updated by reload endpoint)
_last_stats: dict = {}

# ─── Download background state ────────────────────────────────────────────────
_dl_lock = threading.Lock()
_dl_state: dict = {
    "running": False,
    "phase": "idle",      # idle | connecting | downloading | extracting | importing | done | error
    "percent": 0,
    "message": "",
    "error": None,
    "files_extracted": 0,
    "stats": {},
}

def _dl_set(phase: str, percent: int, message: str = "") -> None:
    with _dl_lock:
        _dl_state.update({"phase": phase, "percent": percent, "message": message})

def _run_download() -> None:
    """Background thread: download + extract + import Atomic Red Team."""
    global _last_stats

    GITHUB_ZIP = "https://github.com/redcanaryco/atomic-red-team/archive/refs/heads/master.zip"
    ZIP_PREFIX  = "atomic-red-team-master/atomics/"
    ALLOWED_EXTS = {".yaml", ".yml", ".md"}

    atomic_dir    = Path(settings.atomic_path)
    atomic_parent = atomic_dir.parent

    try:
        # ── Phase 1: connect
        _dl_set("connecting", 2, "Connecting to GitHub...")
        req = urllib.request.Request(GITHUB_ZIP, headers={"User-Agent": "Morgana/1.0"})
        with urllib.request.urlopen(req, context=_make_ssl_context(), timeout=600) as resp:
            content_length = int(resp.headers.get("Content-Length") or 0)
            mb_total = content_length // (1024 * 1024) if content_length else 0
            _dl_set("downloading", 5, f"Downloading (~{mb_total} MB)...")

            # ── Phase 2: chunked download with real % (5% -> 65%)
            CHUNK = 65536
            chunks: list[bytes] = []
            downloaded = 0
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if content_length > 0:
                    pct = 5 + int(downloaded / content_length * 60)
                    mb_done = downloaded // (1024 * 1024)
                    _dl_set("downloading", min(pct, 65), f"Downloading... {mb_done} MB / {mb_total} MB")
            zip_data = b"".join(chunks)

        # ── Phase 3: extract (65% -> 85%)
        _dl_set("extracting", 68, "Extracting YAML files...")
        if atomic_dir.exists():
            shutil.rmtree(str(atomic_dir), ignore_errors=True)
        atomic_parent.mkdir(parents=True, exist_ok=True)

        extracted = 0
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            members = [m for m in zf.namelist()
                       if m.startswith(ZIP_PREFIX) and m != ZIP_PREFIX
                       and not m.endswith("/")
                       and Path(m).suffix.lower() in ALLOWED_EXTS]
            total_members = len(members) or 1
            for i, member in enumerate(members):
                rel  = member[len("atomic-red-team-master/"):]
                dest = atomic_parent / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member))
                extracted += 1
                if i % 50 == 0:
                    pct = 68 + int(i / total_members * 17)
                    _dl_set("extracting", min(pct, 85), f"Extracting... {extracted} files")

        log.info("[ADMIN] Extracted %d files to %s", extracted, atomic_dir)

        # ── Phase 4: import into DB (85% -> 99%)
        _dl_set("importing", 87, "Importing into database...")
        from core.atomic_loader import AtomicLoader
        loader = AtomicLoader(str(atomic_dir))
        stats  = loader.reload_all()
        _last_stats = stats
        log.info("[ADMIN] Import done: loaded=%d updated=%d errors=%d",
                 stats.get("loaded", 0), stats.get("updated", 0), stats.get("errors", 0))

        # ── Done
        with _dl_lock:
            _dl_state.update({
                "running": False, "phase": "done", "percent": 100,
                "message": f"{extracted} files extracted, {stats.get('loaded', 0)} scripts imported",
                "error": None, "files_extracted": extracted, "stats": stats,
            })

    except Exception as exc:
        log.error("[ADMIN] Atomics download failed: %s", exc)
        with _dl_lock:
            _dl_state.update({
                "running": False, "phase": "error", "percent": 0,
                "message": str(exc), "error": str(exc),
            })

# Persistent global settings file (survives restarts)
_SETTINGS_FILE = Path(settings.db_path).parent / "server-settings.json"


def _load_server_settings() -> dict:
    """Return persisted global settings, falling back to config.py defaults."""
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "default_beacon_interval": settings.default_beacon_interval,
            "log_retention_hours": 24,
        }


def _save_server_settings(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─── Global settings endpoints ────────────────────────────────────────────────

class ServerSettingsBody(BaseModel):
    default_beacon_interval: Optional[int] = None  # seconds, 5-3600
    dns_name: Optional[str] = None                 # public DNS name (empty string = clear)
    log_retention_hours: Optional[int] = None      # hours to keep logs, 1-168 (default 24)


@router.get("/settings")
def get_server_settings(_: str = Depends(require_api_key)):
    """Return current global server settings."""
    return _load_server_settings()


@router.put("/settings")
def put_server_settings(body: ServerSettingsBody, _: str = Depends(require_api_key)):
    """Persist global server settings. Changes take effect for newly enrolled agents."""
    data = _load_server_settings()
    if body.default_beacon_interval is not None:
        if not (5 <= body.default_beacon_interval <= 3600):
            raise HTTPException(status_code=400, detail="beacon_interval must be between 5 and 3600 seconds")
        data["default_beacon_interval"] = body.default_beacon_interval
        settings.default_beacon_interval = body.default_beacon_interval  # in-memory update
    if body.dns_name is not None:
        data["dns_name"] = body.dns_name.strip()
    if body.log_retention_hours is not None:
        if not (1 <= body.log_retention_hours <= 168):
            raise HTTPException(status_code=400, detail="log_retention_hours must be between 1 and 168")
        data["log_retention_hours"] = body.log_retention_hours
    _save_server_settings(data)
    log.info("[ADMIN] Global settings updated: %s", data)
    return data


# ─── Log viewer + cleanup ─────────────────────────────────────────────────────

def cleanup_old_logs() -> int:
    """Remove log lines older than log_retention_hours. Returns count removed.

    Reads the JSONL log file, keeps only entries within the retention window,
    and rewrites the file. Safe to call from any thread.
    """
    log_file = Path(settings.log_file)
    if not log_file.exists():
        return 0
    retention_hours = int(_load_server_settings().get("log_retention_hours", 24))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    kept: list[str] = []
    removed = 0
    for raw in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
            ts_str = entry.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                kept.append(raw)
            else:
                removed += 1
        except Exception:
            kept.append(raw)  # keep unparseable lines
    if removed:
        log_file.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


@router.get("/logs")
def get_logs(
    since: Optional[str] = None,   # ISO datetime, or shorthand "30m" / "1h" / "6h" / "24h"
    until: Optional[str] = None,   # ISO datetime upper bound (optional)
    search: Optional[str] = None,  # text to match within the msg field (case-insensitive)
    level: Optional[str] = None,   # INFO | WARNING | ERROR
    limit: int = 500,
    _: str = Depends(require_api_key),
):
    """Return recent log entries from the JSONL server log file.

    By default (no params) returns the last 30 minutes of entries, newest first.
    """
    log_file = Path(settings.log_file)
    if not log_file.exists():
        return []

    now = datetime.now(timezone.utc)

    # Parse 'since'
    if since is None:
        since_dt = now - timedelta(minutes=30)
    elif since.endswith("m"):
        try:
            since_dt = now - timedelta(minutes=int(since[:-1]))
        except ValueError:
            since_dt = now - timedelta(minutes=30)
    elif since.endswith("h"):
        try:
            since_dt = now - timedelta(hours=int(since[:-1]))
        except ValueError:
            since_dt = now - timedelta(minutes=30)
    else:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            since_dt = now - timedelta(minutes=30)

    # Parse 'until'
    until_dt: Optional[datetime] = None
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        except Exception:
            until_dt = None

    level_filter = level.upper() if level else None

    # Parse search string into tokens: quoted phrases stay intact, words are AND-ed.
    # e.g. 'async papa'       -> ['async', 'papa'] (both must appear)
    #      '"async papa"'     -> ['async papa']    (exact phrase must appear)
    #      'error "my func"'  -> ['error', 'my func']
    search_tokens: list[str] = []
    if search:
        try:
            search_tokens = [t.lower() for t in shlex.split(search) if t]
        except ValueError:
            # Unbalanced quotes — treat the whole string as a single token
            search_tokens = [search.strip().lower()]

    entries: list[dict] = []
    for raw in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
            ts_str = entry.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < since_dt:
            continue
        if until_dt is not None and ts > until_dt:
            continue
        if level_filter and entry.get("level", "").upper() != level_filter:
            continue
        if search_tokens:
            # Search across msg + exception traceback (case-insensitive)
            haystack = (entry.get("msg", "") + " " + (entry.get("exc") or "")).lower()
            if not all(token in haystack for token in search_tokens):
                continue
        entries.append(entry)

    # Newest first
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries[:max(1, limit)]


@router.get("/server-info")
def get_server_info(_: str = Depends(require_api_key)):
    """Return server hostname, primary IP, memory usage, disk usage, and platform info."""

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
        "ssl_enabled": True,
        "memory": memory_info,
        "disk": disk_info,
    }


# ─── Atomic Red Team endpoints ────────────────────────────────────────────────
@router.post("/atomics/reload")
def reload_atomics(_: str = Depends(require_api_key)):
    """
    Wipe all atomic-red-team scripts from DB and re-import from disk.
    Run this after updating the Atomic Red Team submodule.
    """

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
def create_deploy_token_endpoint(_: str = Depends(require_api_key)):
    """No-op - agent registration no longer requires a deploy token."""
    log.info("[ADMIN] Deploy token requested - auth-free mode, returning empty")
    return {"deploy_token": ""}


@router.get("/atomics/status")
def atomic_status(_: str = Depends(require_api_key)):
    """Return stats from the last atomic import run."""

    from database import SessionLocal
    from models.script import Script

    db = SessionLocal()
    try:
        total_atomic = db.query(Script).filter(Script.source == "atomic-red-team").count()
        total_morgana = db.query(Script).filter(Script.source == "morgana").count()
    finally:
        db.close()

    atomic_path = Path(settings.atomic_path) if settings.atomic_path else None
    yaml_count = len(list(atomic_path.rglob("T*.yaml"))) if atomic_path and atomic_path.exists() else 0

    return {
        "atomic_scripts_in_db": total_atomic,
        "morgana_scripts_in_db": total_morgana,
        "yaml_files_on_disk": yaml_count,
        "last_run_stats": _last_stats,
    }


@router.post("/atomics/download")
def download_atomics(_: str = Depends(require_api_key)):
    """
    Start a background download of Atomic Red Team YAML scripts from GitHub.
    Returns immediately with {"status": "started"}.
    Poll GET /atomics/download-progress for real-time percentage updates.
    """
    with _dl_lock:
        if _dl_state["running"]:
            return {"status": "already_running", "phase": _dl_state["phase"], "percent": _dl_state["percent"]}
        _dl_state.update({
            "running": True, "phase": "connecting", "percent": 0,
            "message": "Starting...", "error": None,
            "files_extracted": 0, "stats": {},
        })

    log.info("[ADMIN] Atomics download started in background thread")
    t = threading.Thread(target=_run_download, daemon=True)
    t.start()
    return {"status": "started"}


@router.get("/atomics/download-progress")
def download_progress(_: str = Depends(require_api_key)):
    """Return current download+import progress. Poll this after POST /atomics/download."""
    with _dl_lock:
        return dict(_dl_state)
