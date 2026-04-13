# =============================================================================
#  Restart-Morgana-Delete-Agent.ps1
#  - Fixes NSSM service env vars (removes obsolete MORGANA_SSL/MORGANA_AGENT_PORT)
#  - Ensures only one DB file exists (server/db/morgana.db)
#  - Restarts the Morgana server (HTTPS-only on :8888)
#  - Removes the local agent service
#  Run as Administrator.
# =============================================================================

param()

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Morgana - Fix + Restart Server + Remove Agent"
Write-Host "  X3M.AI Red Team Platform"
Write-Host ""

# Check admin
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($me)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[ERROR] Must run as Administrator." -ForegroundColor Red
    exit 1
}

$MorganaRoot = "C:\Users\ninoc\OfficeAddinApps\Morgana"
$ServerDir   = "$MorganaRoot\server"
$RealDb      = "$ServerDir\db\morgana.db"
$StaleDb     = "$ServerDir\morgana.db"

# ------------------------------------------------------------------
# STEP 1 - Fix NSSM service environment variables
# ------------------------------------------------------------------
Write-Host "[STEP 1] Fixing NSSM service env vars..." -ForegroundColor Cyan

$nssmExe = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssmExe) {
    nssm set Morgana AppEnvironmentExtra "MORGANA_LOG_LEVEL=INFO" "MORGANA_PORT=8888"
    Write-Host "[OK] NSSM env vars updated (removed MORGANA_SSL, MORGANA_AGENT_PORT)"
} else {
    # Fallback: write directly to registry
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\Morgana\Parameters"
    Set-ItemProperty -Path $regPath -Name "AppEnvironmentExtra" -Value @("MORGANA_LOG_LEVEL=INFO", "MORGANA_PORT=8888") -Type MultiString
    Write-Host "[OK] Registry env vars updated directly"
}

# ------------------------------------------------------------------
# STEP 2 - Remove the stale empty DB, keep only server/db/morgana.db
# ------------------------------------------------------------------
Write-Host ""
Write-Host "[STEP 2] Consolidating to single database..." -ForegroundColor Cyan

if (Test-Path $RealDb) {
    $realSize = (Get-Item $RealDb).Length
    Write-Host "[OK] Real DB found: $RealDb ($([math]::Round($realSize/1KB)) KB)"
} else {
    Write-Host "[ERROR] Real DB not found at: $RealDb" -ForegroundColor Red
    exit 1
}

if (Test-Path $StaleDb) {
    $staleSize = (Get-Item $StaleDb).Length
    Write-Host "[INFO] Removing stale empty DB: $StaleDb ($([math]::Round($staleSize/1KB)) KB)"
    Remove-Item $StaleDb -Force
    # Also remove WAL/SHM sidecar files if present
    Remove-Item "$StaleDb-wal" -Force -ErrorAction SilentlyContinue
    Remove-Item "$StaleDb-shm" -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Stale DB removed"
} else {
    Write-Host "[INFO] No stale DB found (already clean)"
}

# ------------------------------------------------------------------
# STEP 3 - Restart Morgana server service
# ------------------------------------------------------------------
Write-Host ""
Write-Host "[STEP 3] Restarting Morgana server service..." -ForegroundColor Cyan

Stop-Service "Morgana" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4
Start-Service "Morgana"
Start-Sleep -Seconds 10

$svc = Get-Service "Morgana" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "[OK] Morgana server is Running" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Morgana server did not start" -ForegroundColor Red
    exit 1
}

# Verify which DB the server loaded
$logLine = Get-Content "$ServerDir\logs\server.log" -ErrorAction SilentlyContinue | Select-String "\[START\] Database:" | Select-Object -Last 1
if ($logLine) { Write-Host "[INFO] $($logLine.Line.Trim())" } else { Write-Host "[INFO] DB log line not found (check server.log manually)" }

# Verify HTTPS only - port 8888 only, no 8889
Write-Host ""
Write-Host "[INFO] Listening ports (should be only 8888):"
netstat -ano | Select-String ":8888|:8889" | Select-String "LISTENING"

# ------------------------------------------------------------------
# STEP 4 - Stop and uninstall the local Morgana agent
# ------------------------------------------------------------------
Write-Host ""
Write-Host "[STEP 4] Removing Morgana Red Team Agent..." -ForegroundColor Cyan

$agentSvc = Get-Service "Morgana Red Team Agent" -ErrorAction SilentlyContinue
if ($agentSvc) {
    Stop-Service "Morgana Red Team Agent" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "[OK] Agent service stopped"
} else {
    Write-Host "[INFO] Agent service not found (already removed)"
}

$agentBin = "C:\ProgramData\Morgana\agent\morgana-agent.exe"
if (Test-Path $agentBin) {
    & $agentBin uninstall
    Write-Host "[OK] Agent uninstalled"
} else {
    Write-Host "[INFO] Agent binary not found at $agentBin"
}

Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host "  - Server: HTTPS :8888 with real DB (server/db/morgana.db)"
Write-Host "  - Agent: removed. Redeploy with the one-liner from Morgana UI."
Write-Host ""
