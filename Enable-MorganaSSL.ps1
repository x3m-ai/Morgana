<#
.SYNOPSIS
    Enable HTTPS (TLS) on the Morgana server.

.DESCRIPTION
    Run this script AS ADMINISTRATOR on the Morgana machine.

    What it does:
      1. Generates a self-signed TLS certificate with the server IP in the SAN.
      2. Installs the certificate into the Windows Trusted Root store on THIS machine.
      3. Updates the NSSM service environment to add MORGANA_SSL=true.
      4. Restarts the Morgana NT service.
      5. Verifies the HTTPS endpoint responds.

    After running, copy server\certs\morgana-ca.cer to EVERY machine where Excel
    runs the Merlino add-in, then on each Excel machine run (as Administrator):
        certutil -addstore Root morgana-ca.cer

    In Merlino Settings, change the Morgana URL from http:// to https://.

.PARAMETER IP
    The LAN IP address of this machine. Used as IP SAN in the certificate.
    Default: auto-detected from the first non-loopback IPv4 address.

.PARAMETER Port
    The port Morgana listens on. Default: 8888.

.PARAMETER Days
    Certificate validity in days. Default: 1825 (5 years).

.EXAMPLE
    .\Enable-MorganaSSL.ps1
    .\Enable-MorganaSSL.ps1 -IP 192.168.0.160
    .\Enable-MorganaSSL.ps1 -IP 192.168.0.160 -Port 8888
#>
[CmdletBinding()]
param(
    [string]$IP   = "",
    [int]$Port    = 8888,
    [int]$Days    = 1825
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---- helpers ----------------------------------------------------------------
function Write-Ok   ([string]$msg) { Write-Host "[OK]  $msg" -ForegroundColor Green  }
function Write-Info ([string]$msg) { Write-Host "[..] $msg"  -ForegroundColor Cyan   }
function Write-Step ([string]$msg) { Write-Host "[>>] $msg"  -ForegroundColor Yellow }
function Write-Fail ([string]$msg) { Write-Host "[!!] $msg"  -ForegroundColor Red    }

# ---- paths ------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerDir  = Join-Path $ScriptDir "server"
$CertsDir   = Join-Path $ServerDir "certs"
$GenScript  = Join-Path $ScriptDir "scripts\generate-ssl-cert.py"
$VenvPython = Join-Path $ServerDir ".venv\Scripts\python.exe"
$NssmExe    = Join-Path $ScriptDir "tools\nssm.exe"
$ServiceName = "Morgana"

# ---- administrator check ----------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Fail "This script must be run as Administrator."
    Write-Info "Right-click PowerShell and choose 'Run as administrator', then re-run."
    exit 1
}

# ---- auto-detect IP if not provided -----------------------------------------
if (-not $IP) {
    $detected = (
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch "^127\." -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -First 1
    ).IPAddress
    if ($detected) {
        $IP = $detected
        Write-Info "Auto-detected IP: $IP"
    } else {
        Write-Fail "Could not auto-detect IP. Please pass -IP <your-server-ip>"
        exit 1
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Morgana SSL Setup"                      -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Server IP  : $IP"
Write-Host "  Port       : $Port"
Write-Host "  Certs dir  : $CertsDir"
Write-Host "  Validity   : $Days days"
Write-Host ""

# ---- check prerequisites ----------------------------------------------------
Write-Step "Checking prerequisites..."

if (-not (Test-Path $VenvPython)) {
    Write-Fail "Python venv not found at: $VenvPython"
    Write-Info "Run: cd server && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}
Write-Ok "Python venv found."

if (-not (Test-Path $GenScript)) {
    Write-Fail "Cert generator not found at: $GenScript"
    exit 1
}
Write-Ok "Cert generator found."

# ---- generate certificate ---------------------------------------------------
Write-Step "Generating self-signed TLS certificate..."

New-Item -ItemType Directory -Path $CertsDir -Force | Out-Null

& $VenvPython $GenScript --ip $IP --out $CertsDir --days $Days
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Certificate generation failed. Check Python output above."
    exit 1
}

$CertFile = Join-Path $CertsDir "server.crt"
$KeyFile  = Join-Path $CertsDir "server.key"
$CaFile   = Join-Path $CertsDir "morgana-ca.cer"

if (-not (Test-Path $CertFile) -or -not (Test-Path $KeyFile)) {
    Write-Fail "Expected cert files not created. Check output above."
    exit 1
}
Write-Ok "Certificate files created."

# ---- install cert to Windows Trusted Root (this machine) --------------------
Write-Step "Installing certificate to Windows Trusted Root Certification Authorities..."

try {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
        "Root",
        [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine
    )
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $certObj = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CaFile)
    $store.Add($certObj)
    $store.Close()
    Write-Ok "Certificate installed to LocalMachine\Root."
} catch {
    Write-Fail "Failed to install certificate to trust store: $_"
    Write-Info "You can install it manually: certutil -addstore Root '$CaFile'"
}

# ---- update NSSM service environment ----------------------------------------
$serviceInstalled = (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) -ne $null

if ($serviceInstalled -and (Test-Path $NssmExe)) {
    Write-Step "Updating NSSM service environment (MORGANA_SSL=true)..."

    # Read current AppEnvironmentExtra
    $currentEnv = & $NssmExe get $ServiceName AppEnvironmentExtra 2>$null
    if ($currentEnv -notmatch "MORGANA_SSL") {
        $newEnv = ($currentEnv.Trim() + " MORGANA_SSL=true").Trim()
    } else {
        $newEnv = $currentEnv -replace "MORGANA_SSL=\w+", "MORGANA_SSL=true"
    }

    # Split into individual entries for NSSM (each env var as separate arg)
    $envVars = ($newEnv -split "\s+") | Where-Object { $_ -ne "" }
    & $NssmExe set $ServiceName AppEnvironmentExtra @envVars | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "NSSM environment updated with MORGANA_SSL=true."
    } else {
        Write-Fail "NSSM set failed. Set MORGANA_SSL=true manually."
    }
} elseif ($serviceInstalled) {
    Write-Info "NSSM not found. Setting MORGANA_SSL as system environment variable..."
    [System.Environment]::SetEnvironmentVariable("MORGANA_SSL", "true", "Machine")
    Write-Ok "MORGANA_SSL=true set as Machine-level environment variable."
} else {
    Write-Info "NT service not installed. Setting MORGANA_SSL=true for current session."
    $env:MORGANA_SSL = "true"
    Write-Info "For process-based start, also set permanently:"
    Write-Info "  [System.Environment]::SetEnvironmentVariable('MORGANA_SSL','true','Machine')"
}

# ---- restart service --------------------------------------------------------
if ($serviceInstalled) {
    Write-Step "Restarting Morgana NT service..."
    try {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Service $ServiceName).Status -ne "Stopped" -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
        Start-Sleep -Milliseconds 500
        Start-Service -Name $ServiceName -ErrorAction Stop
        Write-Ok "Service restarted."
    } catch {
        Write-Fail "Could not restart service: $_"
        Write-Info "Restart manually: .\Morgana.ps1 restart"
    }
} else {
    Write-Info "NT service not installed. Restart Morgana manually:"
    Write-Info "  .\Morgana.ps1 restart"
}

# ---- verify HTTPS endpoint --------------------------------------------------
Write-Step "Waiting 10s for Morgana to start, then verifying HTTPS..."
Start-Sleep -Seconds 10

$checkUrl = "https://${IP}:${Port}/api/v2/merlino/check_status"
try {
    $response = Invoke-RestMethod -Uri $checkUrl -Headers @{ KEY = "MORGANA_ADMIN_KEY" } -TimeoutSec 10
    Write-Ok "HTTPS endpoint verified: $($response | ConvertTo-Json -Compress)"
} catch {
    Write-Fail "Could not reach $checkUrl - $_"
    Write-Info "The service may still be starting. Try manually:"
    Write-Info "  Invoke-RestMethod '$checkUrl' -Headers @{KEY='MORGANA_ADMIN_KEY'}"
}

# ---- summary ----------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Setup Complete"                          -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""
Write-Ok "Morgana is now running on HTTPS."
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Copy the CA certificate to every Excel machine:" -ForegroundColor White
Write-Host "       $CaFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. On EACH Excel machine, run AS ADMINISTRATOR:" -ForegroundColor White
Write-Host "       certutil -addstore Root morgana-ca.cer" -ForegroundColor Cyan
Write-Host "     (or double-click morgana-ca.cer -> Install -> Local Machine -> Trusted Root)" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. In Merlino Settings, update the Morgana Server URL to:" -ForegroundColor White
Write-Host "       https://$IP" -ForegroundColor Cyan
Write-Host ""
