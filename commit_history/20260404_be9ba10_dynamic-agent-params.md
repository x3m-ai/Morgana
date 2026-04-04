# MILESTONE - parametri dinamici per agents fatti

**Date:** 2026-04-04
**Base commit:** be9ba10
**Branch:** master

## Summary

Server Information panel in admin UI is now fully operational.
Deploy one-liners for agent installers use dynamic server parameters (IP address or DNS name)
instead of hardcoded localhost.

## Changes in this milestone

### ui/index.html
- Added `?v=2` cache-busting suffix to `app.js` script tag to force browser refresh of updated JS

### ui/app.js (be9ba10)
- `_serverInfo` global cache variable added
- `loadServerInfo()` fetches `/api/v2/admin/server-info` and populates all sinfo-* DOM cells
- `saveServerDns()` persists DNS name via `PUT /api/v2/admin/settings`
- `showDeployToken()` uses dynamic `host` (DNS if set, else server IP) for agent one-liner commands
- `loadAdminStatus()` calls `loadServerInfo()` on admin page load

### server/routers/admin.py (be9ba10)
- `GET /api/v2/admin/server-info` endpoint: hostname, IP (UDP trick), memory (psutil), disk (shutil)
- `dns_name` field added to `ServerSettingsBody` and persisted to `server-settings.json`

### server/requirements.txt (be9ba10)
- Added `psutil>=5.9.0`

### Start-Morgana.ps1 (be9ba10)
- Fixed `Join-Path` 3-arg bug (PowerShell 5.1 only accepts 2 positional args)

## Verified
- `GET /api/v2/admin/server-info` returns: hostname=windowspc01, ip=192.168.0.160, mem=83%, disk=48%
- DNS save/load round-trip confirmed
- Deploy one-liners show `http://192.168.0.160:8888` instead of browser origin
