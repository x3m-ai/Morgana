<#
.SYNOPSIS
    Simulates a full Morgana Agent lifecycle against a live server.
    Useful for testing the server before compiling the real Go agent.

.DESCRIPTION
    1. Registers with the server (POST /api/v2/agent/register)
    2. Loops: heartbeat -> poll -> execute -> result
    3. Optionally executes the real command (-RealExecute), otherwise simulates

.PARAMETER Server
    Morgana server base URL. Default: http://localhost:8888

.PARAMETER Token
    Deploy token (API key). Default: MORGANA_ADMIN_KEY

.PARAMETER Hostname
    Fake hostname to register. Default: current machine hostname.

.PARAMETER Interval
    Beacon interval in seconds. Default: 5 (faster for testing).

.PARAMETER RealExecute
    If set, actually runs job commands instead of simulating them.

.EXAMPLE
    .\Test-MorganaAgent.ps1
    .\Test-MorganaAgent.ps1 -Server http://192.168.1.10:8888 -Token MYKEY -RealExecute
#>
[CmdletBinding()]
param(
    [string]$Server   = "http://localhost:8888",
    [string]$Token    = "MORGANA_ADMIN_KEY",
    [string]$Hostname = $env:COMPUTERNAME,
    [int]$Interval    = 5,
    [switch]$RealExecute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Logging ─────────────────────────────────────────────────────────────────

function Write-Step([string]$msg)    { Write-Host "[AGENT]   $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)      { Write-Host "[OK]      $msg" -ForegroundColor Green }
function Write-Job([string]$msg)     { Write-Host "[JOB]     $msg" -ForegroundColor Yellow }
function Write-Warn([string]$msg)    { Write-Host "[WARN]    $msg" -ForegroundColor DarkYellow }
function Write-Fail([string]$msg)    { Write-Host "[ERROR]   $msg" -ForegroundColor Red }
function Write-Beat([string]$msg)    { Write-Host "[BEAT]    $msg" -ForegroundColor DarkCyan }

# ─── HTTP helpers ─────────────────────────────────────────────────────────────

function Invoke-MorganaPost([string]$Path, [hashtable]$Body) {
    $uri  = "$Server$Path"
    $json = $Body | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Uri $uri -Method POST -Body $json -ContentType "application/json"
}

function Invoke-MorganaGet([string]$Path, [string]$BearerToken) {
    $uri     = "$Server$Path"
    $headers = @{}
    if ($BearerToken) { $headers["Authorization"] = "Bearer $BearerToken" }
    return Invoke-RestMethod -Uri $uri -Method GET -Headers $headers
}

# ─── Step 1 - Register ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Morgana Agent Simulator" -ForegroundColor Cyan
Write-Host "  X3M.AI Red Team Platform" -ForegroundColor DarkCyan
Write-Host ""
Write-Step "Registering agent..."
Write-Step "Server:   $Server"
Write-Step "Hostname: $Hostname"
Write-Step "Token:    $Token"
Write-Host ""

try {
    $reg = Invoke-MorganaPost "/api/v2/agent/register" @{
        deploy_token  = $Token
        hostname      = $Hostname
        platform      = "windows"
        architecture  = "amd64"
        os_version    = (Get-CimInstance Win32_OperatingSystem).Caption
        agent_version = "0.1.0-sim"
    }
} catch {
    Write-Fail "Registration failed: $_"
    Write-Fail "Is Morgana running? Try: .\Start-Morgana.ps1"
    exit 1
}

$PAW          = $reg.paw
$AGENT_TOKEN  = $reg.agent_token
$BeaconInterval = if ($reg.beacon_interval) { $reg.beacon_interval } else { $Interval }

Write-Ok "Registered! PAW=$PAW  BeaconInterval=${BeaconInterval}s"
Write-Ok "Check the UI at $Server/ui/ - your agent should appear now."
Write-Host ""
if (-not $RealExecute) {
    Write-Warn "Running in SIMULATE mode - commands will NOT be executed. Use -RealExecute to run them."
    Write-Host ""
}

# Use the faster testing interval
$BeaconInterval = $Interval

# ─── Step 2 - Beacon loop ────────────────────────────────────────────────────

$jobCount     = 0
$successCount = 0
$failCount    = 0

Write-Step "Starting beacon loop (Ctrl+C to stop)..."
Write-Host ""

try {
    while ($true) {
        $now = Get-Date -Format "HH:mm:ss"

        # ── Heartbeat ───────────────────────────────────────────────────────
        try {
            $hb = Invoke-MorganaPost "/api/v2/agent/heartbeat" @{
                paw        = $PAW
                status     = "idle"
                ip_address = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Ethernet*","Wi-Fi*" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty IPAddress)
            }
            Write-Beat "$now  Heartbeat sent. Next poll in ${BeaconInterval}s"
        } catch {
            Write-Warn "$now  Heartbeat failed: $_"
        }

        # ── Poll ─────────────────────────────────────────────────────────────
        try {
            $poll = Invoke-MorganaGet "/api/v2/agent/poll?paw=$PAW" -BearerToken $AGENT_TOKEN

            if ($null -eq $poll.job) {
                # No job - idle
                Start-Sleep -Seconds $BeaconInterval
                continue
            }

            $job = $poll.job
            $jobCount++

            Write-Host ""
            Write-Job "========================================"
            Write-Job "Job received!  ID=$($job.id)"
            Write-Job "Executor:      $($job.executor)"
            Write-Job "Command:       $($job.command)"
            Write-Job "Timeout:       $($job.timeout_seconds)s"
            Write-Job "========================================"
            Write-Host ""

            # ── Execute (or simulate) ─────────────────────────────────────
            $startTime = Get-Date
            $exitCode  = 0
            $stdout    = ""
            $stderr    = ""

            if ($RealExecute) {
                Write-Job "Executing..."
                try {
                    switch ($job.executor.ToLower()) {
                        "powershell" {
                            $result = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $job.command 2>&1
                            $exitCode = $LASTEXITCODE
                            $stdout   = $result -join "`n"
                        }
                        "cmd" {
                            $result = & cmd.exe /C $job.command 2>&1
                            $exitCode = $LASTEXITCODE
                            $stdout   = $result -join "`n"
                        }
                        default {
                            $stdout   = "[SIMULATOR] Executor '$($job.executor)' not supported in simulation"
                            $exitCode = 0
                        }
                    }
                } catch {
                    $stderr   = $_.ToString()
                    $exitCode = 1
                }
            } else {
                # Simulate: fake output + random success/fail
                Start-Sleep -Milliseconds (Get-Random -Minimum 300 -Maximum 1500)
                $stdout   = "[SIMULATED] Command received: $($job.command.Substring(0, [Math]::Min(80, $job.command.Length)))..."
                $exitCode = if ((Get-Random -Minimum 0 -Maximum 10) -lt 9) { 0 } else { 1 }  # 90% success
            }

            $durationMs = [int]((Get-Date) - $startTime).TotalMilliseconds

            # ── Report result ─────────────────────────────────────────────
            try {
                $ack = Invoke-MorganaPost "/api/v2/agent/result" @{
                    paw         = $PAW
                    job_id      = $job.id
                    exit_code   = $exitCode
                    stdout      = $stdout
                    stderr      = $stderr
                    duration_ms = $durationMs
                }

                if ($exitCode -eq 0) {
                    $successCount++
                    Write-Ok "Job $($job.id) FINISHED  exit=0  duration=${durationMs}ms"
                } else {
                    $failCount++
                    Write-Fail "Job $($job.id) FAILED  exit=$exitCode  duration=${durationMs}ms"
                }
            } catch {
                Write-Fail "Failed to send result: $_"
            }

            Write-Host ""
            Write-Step "Stats: jobs=$jobCount  success=$successCount  failed=$failCount"
            Write-Host ""

        } catch {
            Write-Warn "Poll failed: $_"
        }

        Start-Sleep -Seconds $BeaconInterval
    }
} finally {
    Write-Host ""
    Write-Host "  Agent simulator stopped." -ForegroundColor DarkCyan
    Write-Host "  PAW=$PAW  jobs=$jobCount  success=$successCount  failed=$failCount" -ForegroundColor DarkCyan
    Write-Host ""
}
