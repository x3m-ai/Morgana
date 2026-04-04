"""
Morgana Server - Deploy endpoints

Provides pre-baked one-liner agent installation commands and agent binary downloads.

Endpoints:
  GET /install/windows?token=TOKEN  ->  PS1 script with server URL + token pre-filled
  GET /install/linux?token=TOKEN    ->  bash script with server URL + token pre-filled
  GET /download/morgana-agent.exe   ->  Windows agent binary (served from build/)
  GET /download/morgana-agent       ->  Linux   agent binary (served from build/)
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from config import settings

log = logging.getLogger("morgana.deploy")

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _server_url(request: Request) -> str:
    """Infer the server public URL from the incoming request."""
    scheme = "https" if settings.ssl_enabled else "http"
    host   = request.url.hostname
    port   = settings.port
    return f"{scheme}://{host}:{port}"


def _win_script(server_url: str, token: str, interval: int) -> str:
    """Generate a pre-baked PowerShell installer for the Windows agent."""
    return f"""# Morgana Agent - Windows One-liner Installer
# Version: {settings.version}  /  Source: {server_url}
#
# ONE-LINER (run as Administrator in PowerShell 5.1+):
#
#   [Net.ServicePointManager]::ServerCertificateValidationCallback={{$true}}; iex (New-Object Net.WebClient).DownloadString('{server_url}/install/windows?token={token}')
#
# PowerShell 7+:
#   irm -SkipCertificateCheck '{server_url}/install/windows?token={token}' | iex

[Net.ServicePointManager]::ServerCertificateValidationCallback = {{$true}}
$ErrorActionPreference = "Stop"

$ServerUrl  = "{server_url}"
$Token      = "{token}"
$Interval   = {interval}
$InstallDir = "C:\\ProgramData\\Morgana\\agent"
$WorkDir    = "$InstallDir\\work"
$BinaryPath = "$InstallDir\\morgana-agent.exe"

Write-Host ""
Write-Host "  Morgana Agent Installer - X3M.AI Red Team Platform"
Write-Host "  Server: $ServerUrl"
Write-Host ""

$me = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($me)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    Write-Host "[ERROR] Must run as Administrator." -ForegroundColor Red
    exit 1
}}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkDir    -Force | Out-Null
New-Item -ItemType Directory -Path "$InstallDir\\logs" -Force | Out-Null

Write-Host "[INFO] Downloading morgana-agent.exe from $ServerUrl ..."
(New-Object Net.WebClient).DownloadFile("$ServerUrl/download/morgana-agent.exe", $BinaryPath)
if (-not (Test-Path $BinaryPath)) {{
    Write-Host "[ERROR] Download failed - binary not found at $BinaryPath." -ForegroundColor Red
    exit 1
}}
Write-Host "[SUCCESS] Binary ready: $BinaryPath"

Write-Host "[INFO] Installing MorganaAgent NT service ..."
& $BinaryPath install --server $ServerUrl --token $Token --interval $Interval
if ($LASTEXITCODE -ne 0) {{
    Write-Host "[ERROR] Agent install failed (exit $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}}

Write-Host ""
Write-Host "[SUCCESS] MorganaAgent installed and started." -ForegroundColor Green
Write-Host "  Check:     Get-Service MorganaAgent"
Write-Host "  Restart:   Restart-Service MorganaAgent"
Write-Host "  Logs:      $InstallDir\\logs\\"
Write-Host "  Config:    $InstallDir\\config.json"
Write-Host "  Remove:    $BinaryPath uninstall"
Write-Host ""
"""


def _linux_script(server_url: str, token: str, interval: int) -> str:
    """Generate a pre-baked bash installer for the Linux agent."""
    return f"""#!/usr/bin/env bash
# Morgana Agent - Linux One-liner Installer
# Version: {settings.version}  /  Source: {server_url}
#
# ONE-LINER (run as root):
#   curl -ksSL '{server_url}/install/linux?token={token}' | sudo bash

set -e

SERVER_URL="{server_url}"
TOKEN="{token}"
INTERVAL={interval}
INSTALL_DIR="/opt/morgana/agent"
BINARY="$INSTALL_DIR/morgana-agent"

echo ""
echo "  Morgana Agent Installer - X3M.AI Red Team Platform"
echo "  Server: $SERVER_URL"
echo ""

[ "$(id -u)" -ne 0 ] && echo "[ERROR] Must run as root." && exit 1

mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/work" "$INSTALL_DIR/logs"

echo "[INFO] Downloading morgana-agent from $SERVER_URL ..."
curl -ksSL "$SERVER_URL/download/morgana-agent" -o "$BINARY"
chmod +x "$BINARY"
echo "[SUCCESS] Binary ready: $BINARY"

echo "[INFO] Installing morgana-agent systemd service ..."
"$BINARY" install --server "$SERVER_URL" --token "$TOKEN" --interval "$INTERVAL"

echo ""
echo "[SUCCESS] morgana-agent installed and started."
echo "  Check:    systemctl status morgana-agent"
echo "  Restart:  systemctl restart morgana-agent"
echo "  Logs:     journalctl -u morgana-agent -f"
echo "  Config:   /etc/morgana/config.json"
echo "  Token:    /etc/morgana/.agent_token"
echo "  Work:     /var/lib/morgana/work/"
echo "  Remove:   /usr/local/bin/morgana-agent uninstall"
echo ""
"""


# ─── Install script endpoints ─────────────────────────────────────────────────

@router.get("/install/windows", response_class=PlainTextResponse, tags=["deploy"])
async def install_windows(
    request: Request,
    token: str = Query(default=None),
    interval: int = Query(default=30),
):
    """Return a pre-baked PowerShell install script for the Windows agent.

    One-liner:
        [Net.ServicePointManager]::ServerCertificateValidationCallback={$true};
        iex (New-Object Net.WebClient).DownloadString('https://SERVER:8888/install/windows?token=TOKEN')
    """
    server_url = _server_url(request)
    t = token or settings.api_key
    script = _win_script(server_url, t, interval)
    log.info("[DEPLOY] Windows install script requested from %s", request.client.host if request.client else "?")
    return PlainTextResponse(content=script, media_type="text/plain")


@router.get("/install/linux", response_class=PlainTextResponse, tags=["deploy"])
async def install_linux(
    request: Request,
    token: str = Query(default=None),
    interval: int = Query(default=30),
):
    """Return a pre-baked bash install script for the Linux agent.

    One-liner:
        curl -ksSL 'https://SERVER:8888/install/linux?token=TOKEN' | sudo bash
    """
    server_url = _server_url(request)
    t = token or settings.api_key
    script = _linux_script(server_url, t, interval)
    log.info("[DEPLOY] Linux install script requested from %s", request.client.host if request.client else "?")
    return PlainTextResponse(content=script, media_type="text/plain")


# ─── Binary download endpoints ────────────────────────────────────────────────

@router.get("/download/morgana-agent.exe", tags=["deploy"])
async def download_agent_windows():
    """Serve the compiled Windows agent binary from build/morgana-agent.exe."""
    binary_path = Path(settings.agent_binary_win)
    if not binary_path.exists():
        log.warning("[DEPLOY] Windows binary not found at %s", binary_path)
        raise HTTPException(
            status_code=404,
            detail=(
                f"Windows agent binary not found at {binary_path}. "
                "Build it first: cd agent && go build -o ../build/morgana-agent.exe ./cmd/agent"
            ),
        )
    log.info("[DEPLOY] Serving Windows binary (%d bytes) from %s", binary_path.stat().st_size, binary_path)
    return FileResponse(
        path=str(binary_path),
        filename="morgana-agent.exe",
        media_type="application/octet-stream",
    )


@router.get("/download/morgana-agent", tags=["deploy"])
async def download_agent_linux():
    """Serve the compiled Linux agent binary from build/morgana-agent."""
    binary_path = Path(settings.agent_binary_linux)
    if not binary_path.exists():
        log.warning("[DEPLOY] Linux binary not found at %s", binary_path)
        raise HTTPException(
            status_code=404,
            detail=(
                f"Linux agent binary not found at {binary_path}. "
                "Build it first: cd agent && GOOS=linux go build -o ../build/morgana-agent ./cmd/agent"
            ),
        )
    log.info("[DEPLOY] Serving Linux binary (%d bytes) from %s", binary_path.stat().st_size, binary_path)
    return FileResponse(
        path=str(binary_path),
        filename="morgana-agent",
        media_type="application/octet-stream",
    )
