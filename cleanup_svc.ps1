$out = @()
# Kill any process on port 8888
$lines = netstat -ano | findstr ":8888"
foreach ($line in $lines) {
    if ($line -match "LISTENING\s+(\d+)") {
        $p = $Matches[1]
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        $out += "Killed PID $p"
    }
}
# Uninstall existing service
$nssm = "C:\Users\ninoc\OfficeAddinApps\Morgana\tools\nssm.exe"
$out += (& $nssm stop Morgana confirm 2>&1 | Out-String)
Start-Sleep 2
$out += (& $nssm remove Morgana confirm 2>&1 | Out-String)
Start-Sleep 1
$svc = Get-Service Morgana -ErrorAction SilentlyContinue
if ($svc) { $out += "Service still: $($svc.Status)" } else { $out += "Service REMOVED OK" }
$portCheck = netstat -ano | findstr ":8888"
if ($portCheck) { $out += "Port 8888: $portCheck" } else { $out += "Port 8888 FREE" }
$out | Out-File "C:\Users\ninoc\OfficeAddinApps\Morgana\cleanup_output.txt" -Encoding UTF8
