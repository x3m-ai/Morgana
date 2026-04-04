# Morgana Agent Build Script
# Builds Windows (amd64) and Linux (amd64) agent binaries using Go cross-compilation.
#
# Usage (from Morgana root):
#   .\build-agents.ps1
#
# Output:
#   build\morgana-agent.exe   -- Windows amd64
#   build\morgana-agent       -- Linux  amd64

$ErrorActionPreference = "Stop"

$AgentDir  = Join-Path $PSScriptRoot "agent"
$BuildDir  = Join-Path $PSScriptRoot "build"
$AgentDir  = Resolve-Path $AgentDir
$BuildDir  = Resolve-Path $BuildDir

Write-Host ""
Write-Host "  Morgana Agent Builder - X3M.AI Red Team Platform"
Write-Host "  Agent source : $AgentDir"
Write-Host "  Output dir   : $BuildDir"
Write-Host ""

if (-not (Get-Command "go" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Go not found in PATH. Install from https://go.dev/dl/" -ForegroundColor Red
    exit 1
}

$goVersion = & go version
Write-Host "[INFO] $goVersion"
Write-Host ""

Push-Location $AgentDir

# --- Windows amd64 ---
Write-Host "[BUILD] morgana-agent.exe (windows/amd64) ..."
$outWin = Join-Path $BuildDir "morgana-agent.exe"

$env:GOOS        = "windows"
$env:GOARCH      = "amd64"
$env:CGO_ENABLED = "0"

& go build -ldflags="-s -w" -o $outWin .\cmd\agent 2>&1 | ForEach-Object { Write-Host "  $_" }
$exitWin = $LASTEXITCODE

$env:GOOS = ""; $env:GOARCH = ""; $env:CGO_ENABLED = ""

if ($exitWin -ne 0) {
    Pop-Location
    Write-Host "[ERROR] Windows build failed (exit $exitWin)" -ForegroundColor Red
    exit 1
}

$sizeWin = [math]::Round((Get-Item $outWin).Length / 1MB, 1)
Write-Host "[SUCCESS] $outWin  ($sizeWin MB)" -ForegroundColor Green

# --- Linux amd64 ---
Write-Host "[BUILD] morgana-agent (linux/amd64) ..."
$outLin = Join-Path $BuildDir "morgana-agent"

$env:GOOS        = "linux"
$env:GOARCH      = "amd64"
$env:CGO_ENABLED = "0"

& go build -ldflags="-s -w" -o $outLin .\cmd\agent 2>&1 | ForEach-Object { Write-Host "  $_" }
$exitLin = $LASTEXITCODE

$env:GOOS = ""; $env:GOARCH = ""; $env:CGO_ENABLED = ""

Pop-Location

if ($exitLin -ne 0) {
    Write-Host "[ERROR] Linux build failed (exit $exitLin)" -ForegroundColor Red
    exit 1
}

$sizeLin = [math]::Round((Get-Item $outLin).Length / 1MB, 1)
Write-Host "[SUCCESS] $outLin  ($sizeLin MB)" -ForegroundColor Green

Write-Host ""
Write-Host "[DONE] Both agent binaries built successfully." -ForegroundColor Cyan
Write-Host "  Windows : $outWin"
Write-Host "  Linux   : $outLin"
Write-Host ""
Write-Host "  Served by Morgana server at:"
Write-Host "    GET /download/morgana-agent.exe"
Write-Host "    GET /download/morgana-agent"
Write-Host ""
