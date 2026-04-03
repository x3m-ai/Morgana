# MILESTONE - NT Service ok proseguo

**Date:** 2026-04-03  
**Commit:** `d4723a7` (master)  
**Tag:** MILESTONE  
**Author:** Nino Crudele / X3M.AI Ltd

---

## Summary

This milestone covers all work done to bring the Morgana NT Service agent lifecycle to a fully working and robust state. Six distinct work streams were completed.

---

## Work Stream 1 - Uninstall MorganaAgent NT Service

- Verified the NT Service `MorganaAgent` was Running on the local machine
- Ran elevated uninstall via `Start-Process powershell -Verb RunAs`
- Confirmed removal: `sc.exe query MorganaAgent` returned error 1060 (service does not exist)

---

## Work Stream 2 - Stale Agent Auto-Offline + UI Auto-Refresh

**Problem:** After uninstalling the agent, it remained visible in the UI with `status: online` indefinitely.

**Changes:**

### `server/main.py`
- Added `import asyncio`
- Added `_stale_agent_monitor()` async coroutine — runs every 15s, marks agents `offline` when `last_seen > max(beacon_interval * 3, 30)` seconds
- Started monitor task at lifespan startup, cancelled on shutdown
- Log entry on start: `[MONITOR] Stale agent monitor started`

### `ui/app.js`
- Extended `setInterval` block to call `loadAgents()` when the active page is `page-agents`
- Interval: 15000ms (same as dashboard refresh)

**Result:** Agents go offline automatically within ~20s of beacon stopping.

---

## Work Stream 3 - Manual Refresh Button (Agents Page)

**Change: `ui/index.html`**
- Added `<button class="btn btn-secondary" onclick="loadAgents()" title="Refresh agent list">Refresh</button>` in the agents page header, between "Purge stale" and "+ Deploy Agent"

---

## Work Stream 4 - Server Crash Fix (Windows File-Lock)

**Root cause (3-iteration investigation):**

The command `Start-Morgana.ps1 -NoWindow` used `-RedirectStandardOutput morgana-server.log`. This opened the log file as OS write handle #1. Python's `RotatingFileHandler` also opened the same file as handle #2. On Windows, this causes a file-lock conflict, silently crashing the server after ~1-2 minutes.

**Iteration 1** (commit `f135226`):
- `server/main.py`: added `sys.stdout.isatty()` guard — `StreamHandler` only added when running in a TTY
- Partial fix, did not address the OS-level redirect

**Iteration 2** (commit `16a9846`):
- `Start-Morgana.ps1`: changed redirect to `-RedirectStandardOutput "NUL"`
- Problem: on Windows, `"NUL"` is treated as a literal filename, creating a `NUL` file and breaking logging entirely

**Final fix** (commit `10ef8ad`):
- `Start-Morgana.ps1`: removed ALL `-RedirectStandardOutput` and `-RedirectStandardError` args from `Start-Process`
- Only `WindowStyle=Hidden` + `PassThru` used for background mode
- `$LogFile` path corrected: `Join-Path $ServerDir "logs" "server.log"` (was `morgana-server.log` at repo root)
- Critical comment added in script: "do NOT add -RedirectStandardOutput or -RedirectStandardError here"

**Result:** Server runs stably indefinitely. Python owns the log file exclusively.

---

## Work Stream 5 - Working End-to-End Agent Deploy Flow

**Problem 1:** `GET /download/morgana-agent.exe` returned 404 — binary did not exist.
- Fix: compiled with `go build -o ../build/morgana-agent.exe ./cmd/agent/main.go` (9.5MB, Go 1.26.1 windows/amd64)

**Problem 2:** UI passed the `mrg_...` API key as `--token` to the agent installer. The register endpoint validates tokens via `_deploy_tokens` dict (or `settings.api_key`). SHA-256 API keys are not deploy tokens — returned 403.

**Changes:**

### `server/routers/admin.py`
- New endpoint: `POST /api/v2/admin/deploy-token`
- Authenticated with `_require_api_key`
- Calls `create_deploy_token()` from `routers/agent/register.py`
- Returns: `{"deploy_token": "<token>"}`

### `ui/app.js`
- `showDeployToken()` made `async`
- Before showing modal, calls `POST /api/v2/admin/deploy-token` to get a fresh one-time token
- One-liner installer commands use that token (not the API key)

**Result:** Full deploy flow verified end-to-end. Agent registered with `paw=5e97d494b873b0ef`, beaconing at 5s interval.

---

## Work Stream 6 - Final Verification

- Agent installed, beaconing confirmed
- Agent uninstalled, stale monitor detected offline within ~20s
- Server remained stable throughout (log: `server/logs/server.log`, 277KB+)
- `sc.exe query MorganaAgent` confirmed error 1060 (NOT installed)

---

## Commits Included in This Milestone

| Hash | Message |
|------|---------|
| `5a46702` | feat: stale agent auto-offline + UI agents page auto-refresh |
| `f019e70` | ui: add manual Refresh button to agents page header |
| `f135226` | fix: prevent silent crash from double file-lock on morgana-server.log |
| `16a9846` | fix: redirect Python stdout to NUL in NoWindow mode (intermediate) |
| `68d3880` | feat: working end-to-end agent deploy flow |
| `10ef8ad` | fix: correct log path and remove all stdout redirection in NoWindow mode |
| `d4723a7` | MILESTONE - NT Service ok proseguo |

---

## Files Modified

- `server/main.py` — stale monitor, isatty guard
- `server/routers/admin.py` — deploy-token endpoint
- `Start-Morgana.ps1` — removed redirects, fixed log path
- `ui/app.js` — auto-refresh, async showDeployToken, deploy-token API call
- `ui/index.html` — Refresh button
- `build/morgana-agent.exe` — compiled binary (gitignored, must rebuild on new machine)
