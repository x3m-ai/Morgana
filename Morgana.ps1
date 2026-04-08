<#
.SYNOPSIS
    Morgana Red Team Platform -- server manager.

.DESCRIPTION
    Unified start / stop / restart / install / uninstall for the Morgana server.

    ACTIONS
    -------
    start       Start the server. If the NT service is installed, delegates to
                Windows Service Manager (sc start). Otherwise spawns a Python process.

    stop        Stop the server. Service-aware (sc stop) or process-kill fallback.

    restart     Restart the server. Service-aware or process-based fallback.

    install     Register Morgana as a Windows NT Service (requires Administrator).
                Optional -LogLevel enables file logging at the given level.
                Optional -AutoStart sets the service to start automatically at boot.
                Configures automatic service recovery (restart on failure).

    uninstall   Stop and remove the Windows NT Service (requires Administrator).

    status      Show whether the service is installed and its current state.

.PARAMETER Action
    Required. One of: start | stop | restart | install | uninstall | status

.PARAMETER Port
    TCP port Morgana listens on. Default: 8888.
    Also sets MORGANA_PORT for process-based start.

.PARAMETER NoWindow
    (start / restart only, process-based mode)
    Start the server as a hidden background process. Default: foreground.

.PARAMETER LogLevel
    (install only)
    Enable file logging at this level: DEBUG | INFO | WARNING | ERROR.
    Stored in the service registry. When omitted, only errors are logged
    to the Windows Application Event Log; no file is written.

.PARAMETER AutoStart
    (install only)
    Set the service startup type to Automatic (starts at boot).
    Default: Manual.

.EXAMPLE
    # Process-based (dev / no service installed)
    .\Morgana.ps1 start
    .\Morgana.ps1 start 9000 -NoWindow
    .\Morgana.ps1 stop
    .\Morgana.ps1 restart

    # NT Service management (requires Administrator)
    .\Morgana.ps1 install
    .\Morgana.ps1 install -LogLevel INFO -AutoStart
    .\Morgana.ps1 start          # --> sc start Morgana (service installed)
    .\Morgana.ps1 stop           # --> sc stop  Morgana
    .\Morgana.ps1 restart        # --> Restart-Service Morgana
    .\Morgana.ps1 status
    .\Morgana.ps1 uninstall
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "install", "uninstall", "status")]
    [string]$Action,

    [Parameter(Position = 1)]
    [int]$Port = 8888,

    [switch]$NoWindow,

    [ValidateSet("DEBUG", "INFO", "WARNING", "ERROR", "")]
    [string]$LogLevel = "",

    [switch]$AutoStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---- Paths ------------------------------------------------------------------

$ScriptDir       = $PSScriptRoot
$ServerDir       = Join-Path $ScriptDir "server"
$VenvPython      = Join-Path $ServerDir ".venv\Scripts\python.exe"
$MainScript      = Join-Path $ServerDir "main.py"
$NssmExe         = Join-Path $ScriptDir "tools\nssm.exe"
$PidFile         = Join-Path $ScriptDir "morgana.pid"
$LogDir          = Join-Path $ServerDir "logs"
$LogFile         = Join-Path $LogDir "server.log"

# NT Service identity (must match SERVICE_NAME in morgana_service.py)
$ServiceName     = "Morgana"
$RegParamsPath   = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"

# ---- Output helpers ---------------------------------------------------------

function Write-Step([string]$msg)  { Write-Host "[MORGANA] $msg" -ForegroundColor Cyan    }
function Write-Ok([string]$msg)    { Write-Host "[OK]      $msg" -ForegroundColor Green   }
function Write-Warn([string]$msg)  { Write-Host "[WARN]    $msg" -ForegroundColor Yellow  }
function Write-Fail([string]$msg)  { Write-Host "[ERROR]   $msg" -ForegroundColor Red     }
function Write-Info([string]$msg)  { Write-Host "          $msg" -ForegroundColor Gray    }

# ---- Service helpers --------------------------------------------------------

function Test-ServiceInstalled {
    return $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
}

function Get-ServiceState {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) { return $null }
    return $svc.Status
}

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Fail "This action requires Administrator privileges."
        Write-Fail "Re-run PowerShell as Administrator and try again."
        exit 1
    }
}

# ---- Process-based helpers --------------------------------------------------

function Get-PythonExe {
    if (Test-Path $VenvPython) { return $VenvPython }
    Write-Warn "Virtual environment not found at $VenvPython"
    Write-Warn "Falling back to system Python."
    Write-Warn "Setup: cd server && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    return "python"
}

function Get-PidOnPort([int]$p) {
    # Returns the PID that is LISTENING on port $p, or $null.
    $lines = & netstat -ano 2>$null | Select-String ":$p\s"
    foreach ($line in $lines) {
        if ($line -match "LISTENING\s+(\d+)") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Wait-PortFree([int]$p, [int]$timeoutSec = 15) {
    # Blocks until $p is NOT listening or timeout expires.
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $timeoutSec) {
        if (-not (Get-PidOnPort $p)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-PortOpen([int]$p, [int]$timeoutSec = 120) {
    # Blocks until $p IS listening or timeout expires / process dies.
    # Returns hashtable: {Success, Elapsed, ProcessExited}
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $timeoutSec) {
        if (Get-PidOnPort $p) {
            return @{ Success = $true; Elapsed = [int]$sw.Elapsed.TotalSeconds; ProcessExited = $false }
        }
        # Check if caller set $script:_launchedProc and it has already died
        if ($script:_launchedProc -and $script:_launchedProc.HasExited) {
            return @{ Success = $false; Elapsed = [int]$sw.Elapsed.TotalSeconds; ProcessExited = $true }
        }
        Start-Sleep -Seconds 2
    }
    return @{ Success = $false; Elapsed = $timeoutSec; ProcessExited = $false }
}

function Stop-Server {
    <#
    Kills every process associated with Morgana on the configured port.
    Strategy:
      1. Read PID file -> kill that PID if alive.
      2. Scan port  -> kill occupying PID if still alive.
      3. Wait for port to be free (up to 15s).
    Returns $true if something was stopped, $false if nothing was running.
    #>
    [OutputType([bool])]
    param()

    $killed = $false

    # -- Step 1: PID file
    if (Test-Path $PidFile) {
        $raw = (Get-Content $PidFile -Raw).Trim()
        if ($raw -match '^\d+$') {
            $savedPid = [int]$raw
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Step "Stopping process from PID file (PID $savedPid, name: $($proc.ProcessName)) ..."
                try {
                    $proc.CloseMainWindow() | Out-Null   # graceful first
                    Start-Sleep -Milliseconds 1500
                    if (-not $proc.HasExited) {
                        Stop-Process -Id $savedPid -Force
                        Write-Info "Force-killed PID $savedPid"
                    } else {
                        Write-Info "Graceful exit PID $savedPid"
                    }
                    $killed = $true
                } catch {
                    Write-Warn "Could not kill PID $savedPid : $_"
                }
            } else {
                Write-Info "PID $savedPid from PID file is no longer alive."
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    # -- Step 2: Port scan (catches orphaned / externally-started processes)
    $portPid = Get-PidOnPort $Port
    if ($portPid) {
        $proc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
        $pName = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Step "Port $Port still occupied by '$pName' (PID $portPid). Force-killing ..."
        Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
        $killed = $true
    }

    # -- Step 3: Wait for port to free up
    if ($killed) {
        Write-Step "Waiting for port $Port to be released ..."
        if (Wait-PortFree $Port 15) {
            Write-Ok "Port $Port is free."
        } else {
            Write-Warn "Port $Port still appears occupied after 15s. Proceeding anyway."
        }
    }

    return $killed
}

function Start-Server {
    <#
    Launches the Morgana Python server.
    - If $NoWindow: hidden background process, polls for port open, writes PID file.
    - If not $NoWindow: foreground (blocks until Ctrl+C).
    #>

    if (-not (Test-Path $MainScript)) {
        Write-Fail "server\main.py not found at: $MainScript"
        exit 1
    }
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    $pythonExe = Get-PythonExe

    # Detect SSL
    $sslEnabled = ($env:MORGANA_SSL -eq "true") -or (Test-Path (Join-Path $ServerDir "certs\server.crt"))
    $scheme     = if ($sslEnabled) { "https" } else { "http" }

    Write-Step "Python  : $pythonExe"
    Write-Step "Script  : $MainScript"
    Write-Step "Port    : $Port"
    Write-Step "Log     : $LogFile"
    Write-Host ""

    $startArgs = @{
        FilePath         = $pythonExe
        ArgumentList     = $MainScript
        WorkingDirectory = $ServerDir
    }

    if ($NoWindow) {
        # Hidden background window; Python's own RotatingFileHandler writes to $LogFile.
        # Do NOT redirect stdout/stderr via Start-Process - causes Windows file-lock
        # conflict with Python's log handler and silently kills the process.
        $startArgs["WindowStyle"] = "Hidden"
        $startArgs["PassThru"]    = $true

        $script:_launchedProc = Start-Process @startArgs
        $script:_launchedProc.Id | Set-Content $PidFile -Encoding ASCII

        Write-Step "Waiting for port $Port to open (atomic loader may take up to 120s on first run) ..."
        $result = Wait-PortOpen $Port 120

        if ($result.Success) {
            Write-Ok "Server started (PID $($script:_launchedProc.Id)) in $($result.Elapsed)s"
            Write-Ok "URL     : ${scheme}://localhost:$Port/ui/"
            Write-Ok "PID file: $PidFile"
            Write-Ok "Log     : $LogFile"
        } elseif ($result.ProcessExited) {
            Write-Fail "Server process exited unexpectedly. Check log: $LogFile"
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            exit 1
        } else {
            Write-Warn "Port $Port not yet listening after $($result.Elapsed)s. Server may still be initializing."
            Write-Warn "Check log: $LogFile"
        }
    } else {
        Write-Ok "Starting in foreground. Press Ctrl+C to stop."
        Write-Ok "URL: ${scheme}://localhost:$Port/ui/"
        Write-Host ""
        & $pythonExe $MainScript
    }
}

# ---- Banner -----------------------------------------------------------------

Write-Host ""
Write-Host "  ===============================================" -ForegroundColor DarkCyan
Write-Host "   Morgana Red Team Platform  --  Server Manager" -ForegroundColor Cyan
Write-Host "   X3M.AI Ltd" -ForegroundColor DarkCyan
Write-Host "  ===============================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "   Action  : $Action" -ForegroundColor White
Write-Host "   Port    : $Port"   -ForegroundColor White
if ($LogLevel)  { Write-Host "   LogLevel: $LogLevel"  -ForegroundColor White }
if ($AutoStart) { Write-Host "   Startup : Automatic"  -ForegroundColor White }
Write-Host ""

# ============================================================================
# Dispatch
# ============================================================================

$script:_launchedProc = $null

switch ($Action) {

    # ------------------------------------------------------------------------
    "status" {
        if (Test-ServiceInstalled) {
            $state = Get-ServiceState
            $svc   = Get-Service -Name $ServiceName
            Write-Ok  "NT Service '$ServiceName' is installed."
            Write-Info "Display name : $($svc.DisplayName)"
            Write-Info "Status       : $state"
            Write-Info "Start type   : $($svc.StartType)"
            # Read LogLevel from registry
            $regLL = ""
            try {
                $regLL = (Get-ItemProperty -Path $RegParamsPath -Name "LogLevel" -ErrorAction Stop).LogLevel
            } catch { }
            Write-Info "LogLevel     : $(if ($regLL) { $regLL } else { '(not set, errors-only)' })"
        } else {
            Write-Info "NT Service '$ServiceName' is NOT installed."
            Write-Info "Run '.\Morgana.ps1 install' (as Administrator) to register it."
            $portPid = Get-PidOnPort $Port
            if ($portPid) {
                $proc  = Get-Process -Id $portPid -ErrorAction SilentlyContinue
                $pName = if ($proc) { $proc.ProcessName } else { "unknown" }
                Write-Info "Process-based: port $Port is occupied by '$pName' (PID $portPid) -- server is running."
            } else {
                Write-Info "Process-based: port $Port is NOT in use -- server is NOT running."
            }
        }
    }

    # ------------------------------------------------------------------------
    "stop" {
        if (Test-ServiceInstalled) {
            $state = Get-ServiceState
            if ($state -eq "Stopped") {
                Write-Info "Service '$ServiceName' is already stopped."
            } else {
                Write-Step "Stopping NT service '$ServiceName' ..."
                Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
                # Wait up to 30s for the service to reach Stopped state
                $deadline = (Get-Date).AddSeconds(30)
                while ((Get-ServiceState) -ne "Stopped" -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 500
                }
                if ((Get-ServiceState) -eq "Stopped") {
                    Write-Ok "Service '$ServiceName' stopped."
                } else {
                    Write-Warn "Service '$ServiceName' did not stop within 30s. Check Event Viewer."
                }
            }
        } else {
            # Fallback: process-based stop
            $wasStopped = Stop-Server
            if ($wasStopped) {
                Write-Ok "Morgana process stopped."
            } else {
                Write-Info "No Morgana process was running on port $Port."
            }
        }
    }

    # ------------------------------------------------------------------------
    "start" {
        if (Test-ServiceInstalled) {
            $state = Get-ServiceState
            if ($state -eq "Running") {
                Write-Warn "Service '$ServiceName' is already running."
                Write-Warn "Use '.\Morgana.ps1 restart' to force a restart."
                exit 0
            }
            Write-Step "Starting NT service '$ServiceName' ..."
            Start-Service -Name $ServiceName -ErrorAction Stop
            Write-Ok "Service '$ServiceName' start command issued."
            Write-Info "(Atomic loader may take up to 90s on first run; check Event Viewer or service.log)"
        } else {
            # Fallback: process-based start
            $existingPid = Get-PidOnPort $Port
            if ($existingPid) {
                $proc  = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
                $pName = if ($proc) { $proc.ProcessName } else { "unknown" }
                Write-Warn "Port $Port is already in use by '$pName' (PID $existingPid)."
                Write-Warn "Use '.\Morgana.ps1 restart $Port' to force a restart."
                exit 0
            }
            Start-Server
        }
    }

    # ------------------------------------------------------------------------
    "restart" {
        if (Test-ServiceInstalled) {
            Write-Step "Restarting NT service '$ServiceName' ..."
            # Stop first (handle Stopped state gracefully)
            $state = Get-ServiceState
            if ($state -ne "Stopped") {
                Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
                $deadline = (Get-Date).AddSeconds(30)
                while ((Get-ServiceState) -ne "Stopped" -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 500
                }
            }
            Start-Sleep -Milliseconds 500
            Start-Service -Name $ServiceName -ErrorAction Stop
            Write-Ok "Service '$ServiceName' restarted."
        } else {
            Write-Step "Restarting Morgana process on port $Port ..."
            Stop-Server | Out-Null
            Start-Sleep -Milliseconds 500
            Start-Server
        }
    }

    # ------------------------------------------------------------------------
    "install" {
        Assert-Admin

        if (-not (Test-Path $NssmExe)) {
            Write-Fail "NSSM not found at: $NssmExe"
            Write-Fail "Run: winget install NSSM.NSSM then copy win64\nssm.exe to tools\nssm.exe"
            exit 1
        }
        if (-not (Test-Path $MainScript)) {
            Write-Fail "server\main.py not found at: $MainScript"
            exit 1
        }

        $pythonExe = Get-PythonExe

        # -- Block MS Store Python: it uses AppExecLink reparse points that only
        # resolve in a user session. LocalSystem cannot launch them, causing
        # the service to exit immediately with code 101.
        $pyvenvCfg = Join-Path $ServerDir ".venv\pyvenv.cfg"
        if (Test-Path $pyvenvCfg) {
            $cfgContent = Get-Content $pyvenvCfg -Raw
            if ($cfgContent -match "WindowsApps|PythonSoftwareFoundation") {
                Write-Fail "MS Store Python detected in the venv."
                Write-Fail "The NT Service account (LocalSystem) cannot run MS Store Python."
                Write-Host ""
                Write-Warn "Fix (2 minutes):"
                Write-Warn "  1. winget install Python.Python.3.11"
                Write-Warn "  2. cd server"
                Write-Warn "  3. Remove-Item .venv -Recurse -Force"
                Write-Warn "  4. C:\Python311\python.exe -m venv .venv"
                Write-Warn "  5. .venv\Scripts\pip install -r requirements.txt"
                Write-Warn "  6. Re-run: .\Morgana.ps1 install -LogLevel INFO -AutoStart"
                exit 1
            }
        }

        # -- Remove any existing installation cleanly
        if (Test-ServiceInstalled) {
            Write-Step "Existing service found. Removing before reinstall ..."
            $state = Get-ServiceState
            if ($state -ne "Stopped") {
                & $NssmExe stop $ServiceName confirm 2>&1 | Out-Null
                Start-Sleep -Seconds 3
            }
            & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
            Start-Sleep -Seconds 1
        }

        # -- Create log directory
        if (-not (Test-Path $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        }
        $ServiceLog      = Join-Path $LogDir "service.log"
        $ServiceErrorLog = Join-Path $LogDir "service_error.log"

        # -- Register service via NSSM
        $startupType = if ($AutoStart) { "SERVICE_AUTO_START" } else { "SERVICE_DEMAND_START" }
        Write-Step "Registering NT service '$ServiceName' via NSSM (startup=$(if ($AutoStart) { 'Auto' } else { 'Manual' })) ..."
        Write-Info "Python : $pythonExe"
        Write-Info "Script : $MainScript"

        & $NssmExe install $ServiceName $pythonExe $MainScript
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "NSSM install failed (exit $LASTEXITCODE)."
            exit 1
        }

        # -- Service properties
        & $NssmExe set $ServiceName AppDirectory      $ServerDir | Out-Null
        & $NssmExe set $ServiceName DisplayName       "Morgana Red Team Platform" | Out-Null
        & $NssmExe set $ServiceName Description       "X3M.AI Morgana Red Team Platform - FastAPI server for Purple Teaming operations." | Out-Null
        & $NssmExe set $ServiceName Start             $startupType | Out-Null

        # -- Stdout/Stderr redirection (NSSM handles file locking correctly)
        & $NssmExe set $ServiceName AppStdout         $ServiceLog | Out-Null
        & $NssmExe set $ServiceName AppStderr         $ServiceErrorLog | Out-Null
        & $NssmExe set $ServiceName AppRotateFiles    1 | Out-Null
        & $NssmExe set $ServiceName AppRotateBytes    20971520 | Out-Null
        & $NssmExe set $ServiceName AppRotateOnline   1 | Out-Null

        # -- Environment variables passed to the server process
        $logLevelVal = if ($LogLevel) { $LogLevel } else { "ERROR" }
        & $NssmExe set $ServiceName AppEnvironmentExtra "MORGANA_LOG_LEVEL=$logLevelVal" "MORGANA_PORT=$Port" | Out-Null

        # -- Set service logon account: LocalSystem
        & $NssmExe set $ServiceName ObjectName LocalSystem | Out-Null
        Write-Info "Service logon : LocalSystem"

        # -- Write LogLevel to registry for 'status' display
        if (-not (Test-Path $RegParamsPath)) {
            New-Item -Path $RegParamsPath -Force | Out-Null
        }
        if ($LogLevel) {
            Set-ItemProperty -Path $RegParamsPath -Name "LogLevel" -Value $LogLevel -Type String | Out-Null
        } else {
            Remove-ItemProperty -Path $RegParamsPath -Name "LogLevel" -ErrorAction SilentlyContinue
        }

        # -- Configure automatic recovery: restart on 1st, 2nd, 3rd failure
        Write-Step "Configuring service recovery (auto-restart on failure) ..."
        & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null

        # -- Verify installation
        if (Test-ServiceInstalled) {
            $svc = Get-Service -Name $ServiceName
            Write-Ok  "NT Service '$ServiceName' installed successfully."
            Write-Info "Display name : $($svc.DisplayName)"
            Write-Info "Start type   : $($svc.StartType)"
            Write-Info "Python       : $pythonExe"
            Write-Info "LogLevel     : $(if ($LogLevel) { $LogLevel } else { 'ERROR (default)' })"
            Write-Info "Service logon: LocalSystem"
            Write-Info "Stdout log   : $ServiceLog"
            Write-Info "Stderr log   : $ServiceErrorLog"
            Write-Info "Event Viewer : Windows Logs -> Application -> Source = nssm"
            Write-Host ""
            Write-Info "To start : .\Morgana.ps1 start"
            Write-Info "To stop  : .\Morgana.ps1 stop"
            Write-Info "To remove: .\Morgana.ps1 uninstall"
        } else {
            Write-Fail "Installation verification failed -- service not found after install."
            exit 1
        }
    }

    # ------------------------------------------------------------------------
    "uninstall" {
        Assert-Admin

        if (-not (Test-ServiceInstalled)) {
            Write-Info "Service '$ServiceName' is not installed. Nothing to do."
            exit 0
        }

        if (-not (Test-Path $NssmExe)) {
            Write-Warn "NSSM not found at: $NssmExe -- falling back to sc.exe delete"
            $state = Get-ServiceState
            if ($state -ne "Stopped") {
                Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
            }
            & sc.exe delete $ServiceName | Out-Null
        } else {
            Write-Step "Removing NT service '$ServiceName' via NSSM ..."
            & $NssmExe stop   $ServiceName confirm 2>&1 | Out-Null
            Start-Sleep -Seconds 2
            & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "NSSM remove failed. Trying sc.exe delete ..."
                & sc.exe delete $ServiceName | Out-Null
            }
        }

        Start-Sleep -Seconds 1
        if (-not (Test-ServiceInstalled)) {
            Write-Ok "Service '$ServiceName' removed successfully."
        } else {
            Write-Warn "Service may still appear in SCM briefly. It will be purged on next reboot."
        }
    }
}

Write-Host ""
