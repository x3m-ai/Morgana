<#
.SYNOPSIS
    Injects test jobs into a running Morgana server to test the full pipeline.
    Run this in a second terminal while Test-MorganaAgent.ps1 is running.

.DESCRIPTION
    1. Creates a custom PowerShell script on the server (POST /api/v2/scripts)
    2. Fires a synchronize request with state=running to queue a job for the agent
    3. Repeat N times to test multiple jobs

.PARAMETER Server
    Morgana server base URL. Default: http://localhost:8888

.PARAMETER Token
    API key. Default: MORGANA_ADMIN_KEY

.PARAMETER AgentHostname
    Hostname the agent registered with. Default: current machine hostname.

.PARAMETER Count
    Number of test jobs to inject. Default: 3

.EXAMPLE
    .\Test-MorganaInject.ps1
    .\Test-MorganaInject.ps1 -Count 5 -AgentHostname TARGET-PC
#>
[CmdletBinding()]
param(
    [string]$Server        = "http://localhost:8888",
    [string]$Token         = "MORGANA_ADMIN_KEY",
    [string]$AgentHostname = $env:COMPUTERNAME,
    [int]$Count            = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host "[INJECT]  $msg" -ForegroundColor Magenta }
function Write-Ok([string]$msg)   { Write-Host "[OK]      $msg" -ForegroundColor Green }
function Write-Fail([string]$msg) { Write-Host "[ERROR]   $msg" -ForegroundColor Red }

$headers = @{ "KEY" = $Token; "Content-Type" = "application/json" }

Write-Host ""
Write-Host "  Morgana Job Injector" -ForegroundColor Magenta
Write-Host "  Injecting $Count test jobs for agent: $AgentHostname" -ForegroundColor DarkMagenta
Write-Host ""

# ─── Test scripts to inject ───────────────────────────────────────────────────

$testScripts = @(
    @{
        name     = "Whoami Discovery"
        tcode    = "T1033"
        executor = "powershell"
        platform = "windows"
        command  = 'whoami /all'
        source   = "custom-sim"
    },
    @{
        name     = "List Running Processes"
        tcode    = "T1057"
        executor = "powershell"
        platform = "windows"
        command  = 'Get-Process | Select-Object Name, Id, CPU | Sort-Object CPU -Descending | Select-Object -First 20 | Format-Table'
        source   = "custom-sim"
    },
    @{
        name     = "Network Connections Discovery"
        tcode    = "T1049"
        executor = "cmd"
        platform = "windows"
        command  = 'netstat -ano'
        source   = "custom-sim"
    },
    @{
        name     = "System Info Discovery"
        tcode    = "T1082"
        executor = "powershell"
        platform = "windows"
        command  = 'Get-ComputerInfo | Select-Object CsName, OsName, OsVersion, CsProcessors | Format-List'
        source   = "custom-sim"
    },
    @{
        name     = "Local Users Discovery"
        tcode    = "T1087.001"
        executor = "powershell"
        platform = "windows"
        command  = 'Get-LocalUser | Select-Object Name, Enabled, LastLogon | Format-Table'
        source   = "custom-sim"
    }
)

# ─── Step 1: Create/ensure scripts exist on server ───────────────────────────

Write-Step "Creating test scripts on server..."

$createdTcodes = @()

foreach ($s in $testScripts) {
    try {
        $body = $s | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$Server/api/v2/scripts" -Method POST -Body $body -Headers $headers
        Write-Ok "Script created: $($s.tcode) - $($s.name) (ID=$($resp.id))"
        $createdTcodes += $s.tcode
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 409) {
            Write-Host "[SKIP]    Script $($s.tcode) already exists" -ForegroundColor DarkGray
        } else {
            # May already exist with a different id - try to continue
            Write-Host "[WARN]    $($s.tcode): $($_.ToString().Split("`n")[0])" -ForegroundColor DarkYellow
        }
        $createdTcodes += $s.tcode
    }
}

Write-Host ""
Write-Step "Injecting $Count jobs for agent '$AgentHostname'..."
Write-Host ""

# ─── Step 2: Send synchronize requests with state=running ─────────────────────

$tcodes = $testScripts | ForEach-Object { $_["tcode"] }

for ($i = 1; $i -le $Count; $i++) {
    $tcode = $tcodes[($i - 1) % $tcodes.Count]
    $opName = "SimTest-$i-$(Get-Date -Format 'HHmmss')"

    $item = @{
        operation_id  = [System.Guid]::NewGuid().ToString()
        adversary_id  = [System.Guid]::NewGuid().ToString()
        operation     = $opName
        adversary     = "Simulation"
        tcodes        = $tcode
        assigned      = $AgentHostname
        state         = "running"
        group         = "red"
    }
    # Force JSON array wrapping (synchronize expects a list)
    $syncPayload = "[" + ($item | ConvertTo-Json -Depth 10 -Compress) + "]"

    try {
        $resp = Invoke-RestMethod -Uri "$Server/api/v2/merlino/synchronize" -Method POST -Body $syncPayload -Headers $headers
        if ($resp.jobs_queued -gt 0) {
            Write-Ok "[$i/$Count] Job queued for $tcode -> $AgentHostname  (op: $opName)"
        } else {
            Write-Host "[WARN]    [$i/$Count] $tcode -> 0 jobs queued. Agent may be offline or script missing." -ForegroundColor DarkYellow
            Write-Host "           agents_found=$($resp.agents_found) jobs_queued=$($resp.jobs_queued)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Fail "[$i/$Count] Sync failed: $_"
    }

    Start-Sleep -Milliseconds 500
}

Write-Host ""
Write-Ok "Done. Check the agent simulator terminal and http://localhost:8888/ui/"
Write-Host ""
