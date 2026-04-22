[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,

    [Parameter(Mandatory = $true)]
    [string]$DataDir,

    [int]$Port = 8888,
    [string]$ServiceName = "Morgana"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$message) {
    Write-Host "[INFO] $message"
}

function Ensure-Dir([string]$path) {
    if (-not (Test-Path $path)) {
        New-Item -Path $path -ItemType Directory -Force | Out-Null
    }
}

function New-RandomApiKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $hex = ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
    return "mrg_$hex"
}

$nssm = Join-Path $AppDir "tools\nssm.exe"
$serverExe = Join-Path $AppDir "morgana-server.exe"

if (-not (Test-Path $nssm)) {
    throw "Missing NSSM executable: $nssm"
}
if (-not (Test-Path $serverExe)) {
    throw "Missing server executable: $serverExe"
}

$dbDir = Join-Path $DataDir "db"
$logsDir = Join-Path $DataDir "logs"
$certsDir = Join-Path $DataDir "certs"
$configDir = Join-Path $DataDir "config"

Ensure-Dir $DataDir
Ensure-Dir $dbDir
Ensure-Dir $logsDir
Ensure-Dir $certsDir
Ensure-Dir $configDir

# Add Windows Defender exclusion BEFORE any files are written.
# Atomic Red Team YAML files contain attack commands and trigger Defender heuristics.
# C:\ProgramData\Morgana is the single data root -- DB, logs, certs and atomics all live here.
Write-Info "Adding Windows Defender exclusion for $DataDir"
try {
    Add-MpPreference -ExclusionPath $DataDir -ErrorAction Stop
    Write-Info "Defender exclusion added for $DataDir"
} catch {
    Write-Warning "[WARN] Could not add Defender exclusion: $_"
    Write-Warning "[WARN] Add manually in PowerShell (admin): Add-MpPreference -ExclusionPath '$DataDir'"
}

$apiKeyFile = Join-Path $configDir "master-api-key.txt"
if (Test-Path $apiKeyFile) {
    $apiKey = (Get-Content -Path $apiKeyFile -Raw).Trim()
} else {
    $apiKey = New-RandomApiKey
    Set-Content -Path $apiKeyFile -Encoding ASCII -Value $apiKey
}

$atomicsDir = Join-Path $DataDir "atomics\atomics"
Ensure-Dir (Join-Path $DataDir "atomics")

$dbPath = Join-Path $dbDir "morgana.db"
$logPath = Join-Path $logsDir "server.log"
$certPath = Join-Path $certsDir "server.crt"
$keyPath = Join-Path $certsDir "server.key"
$stdoutPath = Join-Path $logsDir "service.log"
$stderrPath = Join-Path $logsDir "service_error.log"

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Write-Info "Existing service found, removing it before reinstall"
    & $nssm stop $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 2
    & $nssm remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 1
}

Write-Info "Installing Windows service $ServiceName"
& $nssm install $ServiceName $serverExe
if ($LASTEXITCODE -ne 0) {
    throw "NSSM install failed with exit code $LASTEXITCODE"
}

& $nssm set $ServiceName AppDirectory $AppDir | Out-Null
& $nssm set $ServiceName DisplayName "Morgana Red Team Platform" | Out-Null
& $nssm set $ServiceName Description "Morgana Server - X3M.AI" | Out-Null
& $nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null

& $nssm set $ServiceName AppStdout $stdoutPath | Out-Null
& $nssm set $ServiceName AppStderr $stderrPath | Out-Null
& $nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $nssm set $ServiceName AppRotateBytes 20971520 | Out-Null
& $nssm set $ServiceName AppRotateOnline 1 | Out-Null

$envVars = @(
    "MORGANA_PORT=$Port",
    "MORGANA_DB=$dbPath",
    "MORGANA_LOG=$logPath",
    "MORGANA_CERT=$certPath",
    "MORGANA_KEY=$keyPath",
    "MORGANA_API_KEY=$apiKey",
    "MORGANA_ATOMICS=$atomicsDir"
)
& $nssm set $ServiceName AppEnvironmentExtra $envVars | Out-Null

& $nssm set $ServiceName ObjectName LocalSystem | Out-Null
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null

Write-Info "Ensuring firewall rule for TCP $Port"
$fwRuleName = "Morgana Server Port $Port"
$existingRule = Get-NetFirewallRule -DisplayName $fwRuleName -ErrorAction SilentlyContinue
if ($null -eq $existingRule) {
    New-NetFirewallRule -DisplayName $fwRuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
}

Write-Info "Starting service"
Start-Service -Name $ServiceName

# Wait for the server to generate the self-signed TLS cert (up to 20 seconds),
# then install it into the Windows Trusted Root store so browsers don't warn.
Write-Info "Waiting for TLS certificate to be generated..."
$waited = 0
while (-not (Test-Path $certPath) -and $waited -lt 20) {
    Start-Sleep -Seconds 1
    $waited++
}

if (Test-Path $certPath) {
    Write-Info "Installing TLS certificate into Windows Trusted Root store..."
    $certResult = & certutil.exe -addstore -f "Root" $certPath 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Certificate trusted -- browser will no longer show 'Not secure'"
    } else {
        Write-Warning "[WARN] certutil failed (exit $LASTEXITCODE): $certResult"
        Write-Warning "[WARN] You can trust it manually: certutil -addstore -f Root `"$certPath`""
    }
} else {
    Write-Warning "[WARN] Certificate not found at $certPath after $waited s -- skipping trust install"
    Write-Warning "[WARN] Run manually after first start: certutil -addstore -f Root `"$certPath`""
}

Write-Host ""
Write-Host "[SUCCESS] Morgana installation completed"
Write-Host "[SUCCESS] URL: https://localhost:$Port/ui/"
Write-Host "[SUCCESS] Username: admin@admin.com"
Write-Host "[SUCCESS] Password: admin"
Write-Host "[SUCCESS] API key file: $apiKeyFile"
Write-Host ""
