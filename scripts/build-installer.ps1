[CmdletBinding()]
param(
    [string]$LogoPath = "C:\Users\ninoc\OfficeAddinApps\Merlino\business\Logo\morgana\morgana-arsenal-logo.fw.png"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $repoRoot "build\build-server.py"
$distExe = Join-Path $repoRoot "build\dist\morgana-server.exe"
$installerScript = Join-Path $repoRoot "installer\MorganaServerSetup.iss"
$assetsDir = Join-Path $repoRoot "installer\assets"
$logoOut = Join-Path $assetsDir "morgana-logo.fw.png"
$wizardBmp = Join-Path $assetsDir "wizard.bmp"
$wizardSmallBmp = Join-Path $assetsDir "wizard-small.bmp"

function Write-Step([string]$msg) { Write-Host "[BUILD] $msg" -ForegroundColor Cyan }

function Find-Iscc {
    $candidates = @(
        $env:ISCC_PATH,
        "C:\Users\ninoc\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Convert-PngToBmp([string]$sourcePng, [string]$outputBmp, [int]$width, [int]$height) {
    Add-Type -AssemblyName System.Drawing

    $img = [System.Drawing.Image]::FromFile($sourcePng)
    try {
        $bmp = New-Object System.Drawing.Bitmap $width, $height
        try {
            $gfx = [System.Drawing.Graphics]::FromImage($bmp)
            try {
                $gfx.Clear([System.Drawing.Color]::FromArgb(44,44,44))
                $gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality

                $ratioX = $width / $img.Width
                $ratioY = $height / $img.Height
                $ratio = [Math]::Min($ratioX, $ratioY)

                $drawW = [int]($img.Width * $ratio)
                $drawH = [int]($img.Height * $ratio)
                $drawX = [int](($width - $drawW) / 2)
                $drawY = [int](($height - $drawH) / 2)

                $gfx.DrawImage($img, $drawX, $drawY, $drawW, $drawH)
            }
            finally {
                $gfx.Dispose()
            }

            $bmp.Save($outputBmp, [System.Drawing.Imaging.ImageFormat]::Bmp)
        }
        finally {
            $bmp.Dispose()
        }
    }
    finally {
        $img.Dispose()
    }
}

Write-Step "Building morgana-server.exe with PyInstaller"
$venvPython = Join-Path $repoRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Venv Python not found: $venvPython. Run: cd server && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
}
Push-Location $repoRoot
try {
    & $venvPython $buildScript
}
finally {
    Pop-Location
}

if (-not (Test-Path $distExe)) {
    throw "Build failed: missing $distExe"
}

# Ensure Windows agent binary exists -- it must be bundled in the installer.
$agentExe = Join-Path $repoRoot "build\morgana-agent.exe"
if (-not (Test-Path $agentExe)) {
    Write-Step "morgana-agent.exe not found. Attempting Go build..."
    $goCmd = Get-Command go -ErrorAction SilentlyContinue
    if ($goCmd) {
        Push-Location (Join-Path $repoRoot "agent")
        try {
            $env:GOOS   = "windows"
            $env:GOARCH = "amd64"
            & go build -o $agentExe .\cmd\agent
            if ($LASTEXITCODE -ne 0) { throw "Go build failed with exit code $LASTEXITCODE" }
            Write-Step "Agent compiled: $agentExe"
        } finally {
            Remove-Item Env:GOOS   -ErrorAction SilentlyContinue
            Remove-Item Env:GOARCH -ErrorAction SilentlyContinue
            Pop-Location
        }
    } else {
        throw "morgana-agent.exe not found and 'go' is not in PATH. Build agent first: cd agent && go build -o ../build/morgana-agent.exe ./cmd/agent"
    }
}
$agentSizeMB = [Math]::Round((Get-Item $agentExe).Length / 1MB, 1)
Write-Step "Agent binary ready: $agentExe ($agentSizeMB MB)"

if (-not (Test-Path $LogoPath)) {
    throw "Logo not found: $LogoPath"
}

if (-not (Test-Path $assetsDir)) {
    New-Item -Path $assetsDir -ItemType Directory -Force | Out-Null
}

Copy-Item -Path $LogoPath -Destination $logoOut -Force
Write-Step "Logo copied to $logoOut"

Write-Step "Generating Inno Setup wizard bitmaps from logo"
Convert-PngToBmp -sourcePng $logoOut -outputBmp $wizardBmp -width 164 -height 314
Convert-PngToBmp -sourcePng $logoOut -outputBmp $wizardSmallBmp -width 55 -height 55

$iscc = Find-Iscc
if (-not $iscc) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 or set ISCC_PATH."
}

Write-Step "Compiling installer with ISCC"
& $iscc $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE"
}

Write-Step "Installer build completed"
Write-Host "[SUCCESS] Output folder: $repoRoot\build\installer" -ForegroundColor Green

# ─── Publish to Merlino CDN (Cloudflare Pages) ────────────────────────────────
# CF Pages serves the auto-update EXE and version.json (both under 25 MB limit).
# The installer (28+ MB) is distributed via GitHub Releases instead.
$merlinoCdn = "C:\Users\ninoc\OfficeAddinApps\Merlino\docs\morgana"
if (Test-Path $merlinoCdn) {
    Write-Step "Publishing to Merlino CDN: $merlinoCdn"

    # Only copy the raw server EXE (for in-app auto-update swap) — NOT the installer.
    # The installer exceeds the 25 MB CF Pages file size limit.
    Copy-Item $distExe (Join-Path $merlinoCdn "morgana-server.exe") -Force

    # Read version from config.py
    $configPy = Get-Content (Join-Path $repoRoot "server\config.py") -Raw
    if ($configPy -match 'version\s*(?::\s*str\s*)?\s*=\s*"([^"]+)"') {
        $ver = $Matches[1]
    } else {
        $ver = "0.0.0"
    }

    $versionJson = @{
        version       = $ver
        download_url  = "https://github.com/x3m-ai/Morgana/releases/latest/download/Morgana-Server-Setup.exe"
        release_notes = "See https://github.com/x3m-ai/Morgana/releases"
    } | ConvertTo-Json -Compress
    Set-Content (Join-Path $merlinoCdn "version.json") $versionJson -Encoding UTF8

    # Also update version.json in the Morgana repo root (primary source for auto-update check)
    Set-Content (Join-Path $repoRoot "version.json") $versionJson -Encoding UTF8
    Write-Host "[SUCCESS] version.json updated in Morgana repo root (raw.githubusercontent.com)" -ForegroundColor Green

    Write-Host "[SUCCESS] Merlino CDN updated: v$ver" -ForegroundColor Green
    Write-Host "  server exe: https://merlino.x3m.ai/morgana/morgana-server.exe" -ForegroundColor DarkGray
    Write-Host "  version   : https://raw.githubusercontent.com/x3m-ai/Morgana/master/version.json" -ForegroundColor DarkGray
} else {
    Write-Warning "[WARN] Merlino CDN folder not found ($merlinoCdn) - skipping CDN publish."
}

# ─── Create GitHub Release ─────────────────────────────────────────────────────
# The installer (28+ MB) is uploaded as a GitHub Release asset.
# Requires: gh CLI authenticated (gh auth login).
$ghExe = Get-Command gh -ErrorAction SilentlyContinue
if ($ghExe) {
    if (-not $ver) {
        $configPy = Get-Content (Join-Path $repoRoot "server\config.py") -Raw
        if ($configPy -match 'version\s*(?::\s*str\s*)?\s*=\s*"([^"]+)"') { $ver = $Matches[1] } else { $ver = "0.0.0" }
    }
    $tag = "v$ver"
    $installerOut = Join-Path $repoRoot "build\installer\Morgana-Server-Setup.exe"
    $releaseExists = $false
    try { $null = gh release view $tag --repo x3m-ai/Morgana 2>&1; $releaseExists = ($LASTEXITCODE -eq 0) } catch { $releaseExists = $false }
    if ($releaseExists) {
        Write-Step "Uploading installer to existing GitHub Release $tag"
        gh release upload $tag $installerOut --repo x3m-ai/Morgana --clobber
    } else {
        Write-Step "Creating GitHub Release $tag and uploading installer"
        gh release create $tag $installerOut --repo x3m-ai/Morgana --title "Morgana $tag" --notes "See CHANGELOG. Auto-update EXE: https://merlino.x3m.ai/morgana/morgana-server.exe"
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[SUCCESS] GitHub Release ${tag}: https://github.com/x3m-ai/Morgana/releases/tag/${tag}" -ForegroundColor Green
    } else {
        Write-Warning "[WARN] GitHub Release upload failed - upload manually from build\installer\"
    }
} else {
    Write-Warning "[WARN] gh CLI not found - skipping GitHub Release. Upload build\installer\Morgana-Server-Setup.exe manually."
}

