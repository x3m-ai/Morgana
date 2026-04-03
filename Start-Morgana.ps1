<#
.SYNOPSIS
    Start the Morgana server. If already running, restart it.

.PARAMETER Port
    TCP port Morgana listens on. Default: 8888

.PARAMETER NoWindow
    Run the server in a background window (minimized). Default: foreground.

.EXAMPLE
    .\Start-Morgana.ps1
    .\Start-Morgana.ps1 -Port 9999
    .\Start-Morgana.ps1 -NoWindow
#>
[CmdletBinding()]
param(
    [int]$Port     = 8888,
    [switch]$NoWindow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir   = $PSScriptRoot
$ServerDir   = Join-Path $ScriptDir "server"
$VenvPython  = Join-Path $ServerDir ".venv\Scripts\python.exe"
$SystemPython = "python"
$PidFile     = Join-Path $ScriptDir "morgana.pid"
$LogFile     = Join-Path $ScriptDir "morgana-server.log"
$MainScript  = Join-Path $ServerDir "main.py"

# ─── Helpers ─────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) {
    Write-Host "[MORGANA] $msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "[OK]      $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "[WARN]    $msg" -ForegroundColor Yellow
}

function Write-Fail([string]$msg) {
    Write-Host "[ERROR]   $msg" -ForegroundColor Red
}

function Get-PythonExe {
    if (Test-Path $VenvPython) { return $VenvPython }
    Write-Warn "Virtual environment not found at $VenvPython"
    Write-Warn "Falling back to system Python. Run: cd server && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    return $SystemPython
}

function Get-ProcessOnPort([int]$p) {
    # Returns the PID listening on $p, or $null
    $netstat = netstat -ano 2>$null | Select-String ":$p\s"
    foreach ($line in $netstat) {
        if ($line -match "LISTENING\s+(\d+)") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Stop-MorganaIfRunning {
    $stopped = $false

    # 1 - Check PID file
    if (Test-Path $PidFile) {
        $savedPid = Get-Content $PidFile -Raw | ForEach-Object { $_.Trim() }
        if ($savedPid -match '^\d+$') {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Step "Stopping existing Morgana process (PID $savedPid) ..."
                Stop-Process -Id $savedPid -Force
                Start-Sleep -Milliseconds 800
                Write-Ok "Stopped PID $savedPid"
                $stopped = $true
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    # 2 - Check port (catches processes not tracked by PID file)
    $portPid = Get-ProcessOnPort $Port
    if ($portPid) {
        $proc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
        $pName = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Step "Port $Port is occupied by '$pName' (PID $portPid). Stopping ..."
        Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
        Write-Ok "Freed port $Port"
        $stopped = $true
    }

    return $stopped
}

# ─── Main ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Morgana Red Team Platform" -ForegroundColor Cyan
Write-Host "  X3M.AI Ltd" -ForegroundColor DarkCyan
Write-Host ""

if (-not (Test-Path $MainScript)) {
    Write-Fail "server\main.py not found at: $MainScript"
    exit 1
}

$pythonExe = Get-PythonExe
$restarting = Stop-MorganaIfRunning

if ($restarting) {
    Write-Step "Restarting Morgana ..."
} else {
    Write-Step "Starting Morgana ..."
}

# ─── Launch ──────────────────────────────────────────────────────────────────

Write-Step "Python:  $pythonExe"
Write-Step "Server:  $MainScript"
Write-Step "Port:    $Port"
Write-Step "Log:     $LogFile"
Write-Host ""

$startArgs = @{
    FilePath         = $pythonExe
    ArgumentList     = $MainScript
    WorkingDirectory = $ServerDir
}

if ($NoWindow) {
    # Background with hidden window, output redirected to log files
    $ErrLogFile = Join-Path $ScriptDir "morgana-server-err.log"
    $startArgs["WindowStyle"]            = "Hidden"
    # Do NOT redirect stdout to the log file: Python's RotatingFileHandler already
    # writes to $LogFile directly. Two OS handles on the same file cause Windows
    # file-lock conflicts that silently kill the process. Redirect stdout to NUL.
    $startArgs["RedirectStandardOutput"] = "NUL"
    $startArgs["RedirectStandardError"]  = $ErrLogFile
    $startArgs["PassThru"]               = $true

    $proc = Start-Process @startArgs
    $proc.Id | Set-Content $PidFile -Encoding ASCII

    # Poll for up to 120 seconds (fix_tactics takes ~40-45s on first run)
    $maxWait  = 120
    $interval = 3
    $elapsed  = 0
    $ready    = $false
    Write-Step "Waiting for server to start (may take up to ${maxWait}s while atomic loader runs) ..."
    while ($elapsed -lt $maxWait) {
        Start-Sleep -Seconds $interval
        $elapsed += $interval
        $portPid = Get-ProcessOnPort $Port
        if ($portPid) {
            $ready = $true
            break
        }
        # Also stop polling if the process died
        if ($proc.HasExited) {
            break
        }
    }

    $sslEnabled = ($env:MORGANA_SSL -eq "true") -or (Test-Path (Join-Path $ServerDir "certs\server.crt"))
    $scheme = if ($sslEnabled) { "https" } else { "http" }

    if ($ready) {
        Write-Ok "Morgana started in background (PID $($proc.Id)) after ${elapsed}s"
        Write-Ok "URL:  ${scheme}://localhost:$Port/ui/"
        Write-Ok "PID file: $PidFile"
        Write-Ok "Log:  $LogFile"
    } else {
        Write-Warn "Process launched but port $Port not yet listening after ${elapsed}s - server may still be initializing."
        Write-Warn "Check log: $LogFile"
    }
} else {
    # Foreground (Ctrl+C to stop)
    $sslEnabled = ($env:MORGANA_SSL -eq "true") -or (Test-Path (Join-Path $ServerDir "certs\server.crt"))
    $scheme = if ($sslEnabled) { "https" } else { "http" }
    Write-Ok "Morgana running in foreground. Press Ctrl+C to stop."
    Write-Ok "URL: ${scheme}://localhost:$Port/ui/"
    Write-Host ""
    & $pythonExe $MainScript
}
