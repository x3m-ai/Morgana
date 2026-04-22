# Run this script as Administrator to push UI hotfixes to the installed Morgana Server
# Right-click -> Run as Administrator

$src = "C:\Users\ninoc\OfficeAddinApps\Morgana\ui"
$dst = "C:\Program Files\Morgana Server\ui"

Copy-Item "$src\app.js"    "$dst\app.js"    -Force
Copy-Item "$src\index.html" "$dst\index.html" -Force

Write-Host "[SUCCESS] UI files deployed. Hard-refresh the browser (Ctrl+Shift+R) at https://localhost:8888/ui/" -ForegroundColor Green
