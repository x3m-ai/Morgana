$src = "C:\Users\ninoc\OfficeAddinApps\Morgana\build\dist\morgana-server.exe"
$dst = "C:\Program Files\Morgana Server\morgana-server.exe"

Write-Host "[1/3] Stopping Morgana service..."
net stop Morgana
Start-Sleep -Seconds 4

Write-Host "[2/3] Swapping EXE..."
Copy-Item $src $dst -Force
Write-Host "      Copied: $src -> $dst"

Write-Host "[3/3] Starting Morgana service..."
net start Morgana
Start-Sleep -Seconds 4

$svc = Get-Service Morgana
Write-Host "Service status: $($svc.Status)"
