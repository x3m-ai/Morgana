<#
.SYNOPSIS
    One-liner installer for the Morgana Agent (Windows NT Service).

.DESCRIPTION
    Downloads morgana-agent.exe from the specified Morgana server and
    installs it as an NT Service that starts automatically on boot.

.PARAMETER ServerUrl
    Base URL of the Morgana server, e.g. https://192.168.1.10:8888

.PARAMETER Token
    Deploy token from the Morgana Settings page (MORGANA_API_KEY).

.PARAMETER Interval
    Beacon heartbeat interval in seconds. Default: 30.

.PARAMETER WorkDir
    Agent working directory. Default: C:\ProgramData\Morgana\agent\work

.EXAMPLE
    irm https://server:8888/ui/install.ps1 | iex
    # Or with parameters:
    & .\install-agent-windows.ps1 -ServerUrl https://192.168.1.10:8888 -Token MYTOKEN

.NOTES
    Requires: PowerShell 5.1+ and Administrator privileges.
    The agent binary is downloaded from ${ServerUrl}/download/morgana-agent.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ServerUrl,

    [Parameter(Mandatory = $false)]
    [string]$Token,

    [Parameter(Mandatory = $false)]
    [int]$Interval = 30,

    [Parameter(Mandatory = $false)]
    [string]$WorkDir = "C:\ProgramData\Morgana\agent\work"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Banner {
    Write-Host ""
    Write-Host "  Morgana Agent Installer" -ForegroundColor Cyan
    Write-Host "  X3M.AI Red Team Platform" -ForegroundColor DarkCyan
    Write-Host ""
}

function Assert-Admin {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($me)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "[ERROR] This script must be run as Administrator." -ForegroundColor Red
        exit 1
    }
}

function Prompt-IfMissing([string]$Value, [string]$Prompt) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return (Read-Host $Prompt)
    }
    return $Value
}

# ─── Main ─────────────────────────────────────────────────────────────────────

Write-Banner
Assert-Admin

$ServerUrl = Prompt-IfMissing $ServerUrl "Enter Morgana server URL (e.g. https://192.168.1.10:8888)"
$Token     = Prompt-IfMissing $Token     "Enter deploy token"

$InstallDir = "C:\ProgramData\Morgana\agent"
$BinaryPath = Join-Path $InstallDir "morgana-agent.exe"
$DownloadUrl = "$ServerUrl/download/morgana-agent.exe"

# Create directories
Write-Host "[INFO] Creating installation directory: $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

# Download binary
Write-Host "[INFO] Downloading agent from $DownloadUrl ..."
try {
    $wc = New-Object System.Net.WebClient
    # Accept self-signed TLS certs used by Morgana
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    $wc.DownloadFile($DownloadUrl, $BinaryPath)
    Write-Host "[SUCCESS] Binary downloaded to $BinaryPath"
} catch {
    Write-Host "[ERROR] Download failed: $_" -ForegroundColor Red
    Write-Host "[INFO] Place morgana-agent.exe manually at $BinaryPath and re-run with --skip-download."
    exit 1
}

# Run agent install command
Write-Host "[INFO] Registering NT Service ..."
$args = @("install", "--server", $ServerUrl, "--token", $Token, "--interval", $Interval)
& $BinaryPath $args
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Agent install failed (exit $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[SUCCESS] Morgana Agent installed and started." -ForegroundColor Green
Write-Host "[INFO] Service name: MorganaAgent"
Write-Host "[INFO] Config:       $InstallDir\config.json"
Write-Host "[INFO] Logs:         $InstallDir\logs\"
Write-Host "[INFO] Work dir:     $WorkDir"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Get-Service MorganaAgent          -- Check service status"
Write-Host "  Restart-Service MorganaAgent      -- Restart agent"
Write-Host "  $BinaryPath status                -- Full diagnostics"
Write-Host "  $BinaryPath uninstall             -- Remove agent"
Write-Host ""
