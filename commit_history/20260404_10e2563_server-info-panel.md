# feat: Server Information panel + DNS config + server-aware deploy one-liners

**Date:** 2026-04-04  
**Commit:** (see HEAD after this commit)  
**Based on:** `10e2563` (MILESTONE - NT Service ok proseguo)  
**Author:** Nino Crudele / X3M.AI Ltd

---

## Summary

Added a "Server Information" card at the top of the Admin page, showing real-time host info (IP, hostname, memory, disk), a configurable public DNS name, and updated the deploy one-liner generator to use DNS (or IP) instead of the browser origin.

---

## Changes

### `server/routers/admin.py`

**New endpoint: `GET /api/v2/admin/server-info`**
- Returns: `hostname`, `ip_address` (primary outbound IP via UDP trick), `dns_name` (from settings), `platform`, `platform_version`, `python_version`, `server_port`, `memory` (total/available GB, used %), `disk` (path, total/free GB, used %)
- IP detection: opens UDP socket to 8.8.8.8, reads local address
- Memory via `psutil.virtual_memory()` (graceful fallback if psutil not installed)
- Disk via `shutil.disk_usage(db_path.parent)`
- Authentication: same `_require_api_key` guard

**Updated `PUT /api/v2/admin/settings`**
- Added `dns_name: Optional[str]` to `ServerSettingsBody`
- Persists `dns_name` to `server-settings.json` (stripped of whitespace)
- Empty string clears the DNS name (falls back to IP in UI)

**Updated docstring** to include new endpoint reference.

**New imports:** `platform`, `shutil`, `socket` (all stdlib)

---

### `server/requirements.txt`

- Added `psutil>=5.9.0` — used for accurate memory stats in `server-info` endpoint

---

### `ui/index.html`

**New "Server Information" card added at the top of `page-admin`** (before Atomic Red Team card):

- **Stats row 1:** IP Address (read-only), Machine Name, Platform / Python version, Server Port
- **Stats row 2:** Memory Used %, Memory Free GB, Disk Used %, Disk Free GB
- **DNS name field:** editable text input, "Save DNS" button, `[SAVED]` feedback
- **Helper text:** explains that IP is read-only, DNS is used for deploy one-liners
- All stat values use element IDs: `sinfo-ip`, `sinfo-hostname`, `sinfo-platform`, `sinfo-port`, `sinfo-mem-used`, `sinfo-mem-avail`, `sinfo-disk-used`, `sinfo-disk-free`
- DNS input ID: `sinfodns`, save feedback ID: `sinfoSaved`

Atomic Red Team card gets `margin-top:1rem` to follow cleanly.

---

### `ui/app.js`

**Added `_serverInfo` cache variable** (global, line 260):
```js
let _serverInfo = { ip_address: null, dns_name: "", server_port: 8888 };
```
Used by both `showDeployToken()` and updated in `loadServerInfo()`.

**`showDeployToken()` — updated:**
- Now fetches `GET /api/v2/admin/server-info` at the start to get fresh IP/DNS
- Builds `origin = http://${host}:${port}` where:
  - `host` = DNS name if configured, else server IP, else browser hostname
  - `port` = `server_port` from server-info, else 8888
- Removed HTTPS/SSL branch (Morgana server is HTTP-only in standard setup)
- Removed the `${k}` and `${curlK}` SSL certificate bypass variables
- One-liner commands now use real server address that agents can reach

**New `loadServerInfo()` function:**
- Calls `GET /api/v2/admin/server-info`
- Updates `_serverInfo` cache
- Populates all `sinfo-*` DOM elements
- Pre-fills `#sinfodns` input with current DNS value

**New `saveServerDns()` function:**
- Reads `#sinfodns` input value
- Calls `PUT /api/v2/admin/settings` with `{ dns_name: val }`
- Updates `_serverInfo.dns_name` in memory
- Shows `[SAVED]` feedback for 2 seconds

**Updated `loadAdminStatus()`:**
- Added `loadServerInfo()` call after `loadApiKeys()` and `loadGlobalSettings()`

---

### `Start-Morgana.ps1`

**Bug fix: `Join-Path` with 3 arguments fails in PowerShell 5.1**

```powershell
# Before (broken on PS 5.1):
$LogFile = Join-Path $ServerDir "logs" "server.log"

# After (fixed):
$LogFile = Join-Path (Join-Path $ServerDir "logs") "server.log"
```

---

## Testing

- `GET http://localhost:8888/api/v2/admin/server-info` with header `KEY: MORGANA_ADMIN_KEY`
- Response verified:
  ```json
  {
    "hostname": "windowspc01",
    "ip_address": "192.168.0.160",
    "dns_name": "",
    "platform": "Windows",
    "platform_version": "10.0.26200",
    "python_version": "3.11.9",
    "server_port": 8888,
    "memory": { "total_gb": 31.73, "available_gb": 3.65, "used_pct": 88.5 },
    "disk": { "path": "...\\db", "total_gb": 953.04, "free_gb": 497.59, "used_pct": 47.8 }
  }
  ```
- Deploy modal: `origin` now uses real server IP `192.168.0.160:8888`, not browser `localhost`

---

## Files Modified

| File | Change |
|------|--------|
| `server/routers/admin.py` | New `server-info` endpoint, `dns_name` in settings |
| `server/requirements.txt` | Added `psutil>=5.9.0` |
| `ui/index.html` | Server Information card at top of admin page |
| `ui/app.js` | `_serverInfo` cache, `loadServerInfo()`, `saveServerDns()`, updated `showDeployToken()` and `loadAdminStatus()` |
| `Start-Morgana.ps1` | Fix `Join-Path` 3-arg call (PS 5.1 incompatible) |
