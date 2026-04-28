"""
Morgana Auto-Update Router

GET  /api/v2/update/check      Check if a newer version is available (no auth required)
POST /api/v2/update/apply      Download new EXE and restart the service (requires API key)
GET  /api/v2/update/status     Poll the background update progress (no auth required)

Architecture:
  - Latest version info is fetched from Camelot (GitHub raw):
    https://raw.githubusercontent.com/x3m-ai/Camelot/main/morgana/Install/version.json
  - apply: downloads the new EXE to a temp file, then launches a detached
    PowerShell script that: stops the Morgana service, swaps the EXE, restarts.
  - The server responds BEFORE the service stops so the UI receives the 202.
  - The UI then polls /check until the server is back online and shows the new version.
"""

import json
import logging
import os
import ssl
import subprocess
import sys
import tempfile
import textwrap
import threading
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import settings
from core.auth import require_api_key

log = logging.getLogger("morgana.update")
router = APIRouter()

# Canonical source of truth for latest Morgana version (public Camelot repo)
_VERSION_JSON_URL = (
    "https://raw.githubusercontent.com/x3m-ai/Camelot/main/morgana/Install/version.json"
)

# Background update state
_upd_lock = threading.Lock()
_upd_state: dict = {
    "running": False,
    "phase": "idle",          # idle | checking | downloading | applying | restarting | done | error
    "percent": 0,
    "message": "",
    "error": None,
    "latest_version": None,
    "download_url": None,
    "release_notes": "",
}


def _upd_set(**kwargs) -> None:
    with _upd_lock:
        _upd_state.update(kwargs)


def _make_ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    ctx = ssl.create_default_context()
    if sys.platform == "win32":
        try:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        except Exception:
            pass
    return ctx


def _fetch_version_json() -> dict:
    """Fetch latest version metadata from Camelot."""
    req = urllib.request.Request(
        _VERSION_JSON_URL,
        headers={"User-Agent": "Morgana-AutoUpdate/1.0"},
    )
    with urllib.request.urlopen(req, context=_make_ssl_ctx(), timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


# ─── Check endpoint ───────────────────────────────────────────────────────────

@router.get("/check")
def check_update():
    """Return current and latest version info. No auth required so the UI can
    call this on every page load without needing the API key.
    """
    current = settings.version
    latest_version = None
    release_notes = ""
    download_url = ""
    update_available = False
    error = None

    try:
        meta = _fetch_version_json()
        latest_version = meta.get("version", "")
        release_notes  = meta.get("release_notes", "")
        download_url   = meta.get("download_url", "")
        if latest_version and _version_tuple(latest_version) > _version_tuple(current):
            update_available = True
    except Exception as exc:
        error = str(exc)
        log.debug("[UPDATE] Version check failed: %s", exc)

    # Also expose live update progress so UI can show it even on check endpoint
    with _upd_lock:
        state_snapshot = dict(_upd_state)

    return {
        "current_version": current,
        "latest_version": latest_version,
        "update_available": update_available,
        "release_notes": release_notes,
        "download_url": download_url,
        "check_error": error,
        "update_state": state_snapshot,
    }


# ─── Status endpoint ──────────────────────────────────────────────────────────

@router.get("/status")
def update_status():
    """Return the current background update progress. No auth required."""
    with _upd_lock:
        return dict(_upd_state)


# ─── Apply endpoint ───────────────────────────────────────────────────────────

class ApplyBody(BaseModel):
    download_url: Optional[str] = None   # override URL (optional)


@router.post("/apply")
def apply_update(
    body: ApplyBody = ApplyBody(),
    _auth: str = Depends(require_api_key),
):
    """Download the latest Morgana installer/EXE and restart the service.

    This endpoint returns 202 immediately. The actual update runs in a
    background thread (and then via a detached PowerShell script) so the
    HTTP response can be sent before the service stops.
    """
    with _upd_lock:
        if _upd_state["running"]:
            raise HTTPException(status_code=409, detail="Update already in progress")
        _upd_state["running"] = True
        _upd_state["phase"] = "checking"
        _upd_state["percent"] = 0
        _upd_state["message"] = "Starting update..."
        _upd_state["error"] = None

    t = threading.Thread(target=_run_update, args=(body.download_url,), daemon=True)
    t.start()

    return {"ok": True, "message": "Update started. Server will restart shortly."}


def _run_update(override_url: Optional[str]) -> None:
    """Background thread: download the new EXE then spawn the swap script."""
    try:
        # ── Phase 1: resolve download URL
        _upd_set(phase="checking", percent=5, message="Fetching version info...")
        if override_url:
            exe_url = override_url
        else:
            meta = _fetch_version_json()
            exe_url = meta.get("download_url", "")
            if not exe_url:
                raise RuntimeError("No download_url in version.json")

        log.info("[UPDATE] Downloading new EXE from: %s", exe_url)
        _upd_set(phase="downloading", percent=10, message="Downloading update...")

        # ── Phase 2: download with progress
        req = urllib.request.Request(exe_url, headers={"User-Agent": "Morgana-AutoUpdate/1.0"})
        with urllib.request.urlopen(req, context=_make_ssl_ctx(), timeout=300) as resp:
            content_length = int(resp.headers.get("Content-Length") or 0)
            mb_total = content_length // (1024 * 1024) if content_length else "?"
            chunks = []
            downloaded = 0
            CHUNK = 65536
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if content_length > 0:
                    pct = 10 + int(downloaded / content_length * 60)
                    mb_done = downloaded // (1024 * 1024)
                    _upd_set(
                        phase="downloading",
                        percent=min(pct, 70),
                        message=f"Downloading... {mb_done} MB / {mb_total} MB",
                    )
            exe_data = b"".join(chunks)

        log.info("[UPDATE] Downloaded %d bytes", len(exe_data))

        # ── Phase 3: write to Defender-excluded temp dir
        _upd_set(phase="applying", percent=72, message="Preparing swap script...")
        temp_dir = Path(settings.data_dir) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        new_exe_path = temp_dir / "morgana-server-new.exe"
        new_exe_path.write_bytes(exe_data)
        log.info("[UPDATE] New EXE written to: %s", new_exe_path)

        # Current EXE path (frozen build = next to this EXE)
        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable)
        else:
            # Dev mode: no real swap, just log and skip
            log.warning("[UPDATE] Dev mode: would swap EXE but skipping actual swap. Restart not triggered.")
            _upd_set(running=False, phase="done", percent=100, message="Dev mode: swap skipped")
            return

        swap_script = textwrap.dedent(f"""\
            # Morgana auto-update swap script (generated, do not edit)
            $ErrorActionPreference = 'Stop'
            function Write-Log {{
                param([string]$msg)
                $ts = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
                Add-Content -Path '{temp_dir}\\update.log' -Value "$ts $msg" -Encoding UTF8 -ErrorAction SilentlyContinue
                Write-Host "$ts $msg"
            }}
            Write-Log '[START] Morgana auto-update swap'
            # Give the HTTP response time to reach the client
            Start-Sleep 3
            # Stop the service
            Write-Log '[INFO] Stopping Morgana service...'
            try {{ Stop-Service -Name Morgana -Force -ErrorAction Stop }} catch {{ Write-Log "[WARN] Stop-Service: $_" }}
            Start-Sleep 4
            # Swap EXE
            Write-Log '[INFO] Replacing EXE...'
            Copy-Item -Path '{new_exe_path}' -Destination '{current_exe}' -Force
            Write-Log '[INFO] EXE replaced'
            # Start the service
            Write-Log '[INFO] Starting Morgana service...'
            try {{ Start-Service -Name Morgana -ErrorAction Stop }} catch {{ Write-Log "[ERROR] Start-Service: $_"; exit 1 }}
            Write-Log '[SUCCESS] Morgana restarted successfully'
        """)

        ps1_path = temp_dir / "morgana-update-swap.ps1"
        ps1_path.write_text(swap_script, encoding="utf-8")
        log.info("[UPDATE] Swap script written to: %s", ps1_path)

        _upd_set(phase="restarting", percent=85, message="Restarting service...")

        # ── Phase 4: launch swap script detached (will outlive this process)
        if sys.platform == "win32":
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-WindowStyle", "Hidden",
                    "-File", str(ps1_path),
                ],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("[UPDATE] Swap script launched (detached). Server will restart.")
            _upd_set(phase="restarting", percent=90, message="Server restarting...")
            # This thread ends here; the server will be killed by the PS1 script
        else:
            # Linux: swap script not implemented yet
            log.warning("[UPDATE] Linux: EXE downloaded but swap not implemented. Manual restart needed.")
            _upd_set(running=False, phase="done", percent=100,
                     message="EXE downloaded. Manual service restart required on Linux.")

    except Exception as exc:
        log.error("[UPDATE] Update failed: %s", exc, exc_info=True)
        _upd_set(running=False, phase="error", percent=0, message=str(exc), error=str(exc))
