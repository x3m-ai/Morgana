# Commit: Open Source Release — AGPL-3.0, In-App Auto-Update, Stale Log Fix

**Date:** 28 April 2026
**Branch:** master
**Author:** Nino Crudele — X3M.AI Ltd (UK)

---

## Summary

This commit marks the **public open-source release** of Morgana under the AGPL-3.0 license. It introduces a full in-app auto-update system, a stale log cleanup fix on version upgrades, and a complete README rewrite reflecting Morgana's positioning as the open-source execution engine of the Merlino + Morgana Purple Team platform.

---

## Files Changed

### `LICENSE`
- **Replaced** MIT License with **GNU Affero General Public License v3.0 (AGPL-3.0)**
- Added X3M.AI Ltd copyright header: `Copyright (C) 2026 X3M.AI Ltd (UK) - Nino Crudele`
- Full AGPL-3.0 text follows the copyright preamble

### `README.md`
- Header updated: version `0.2.4`, license badge AGPL-3.0, link to Merlino (free, no registration), link to Camelot
- **What is Morgana** section rewritten: opens with the Merlino+Morgana joint platform story, full Purple Team lifecycle description, innovation positioning
- Installation section: Option A (Windows installer from Camelot), Option B (manual from source)
- **Merlino + Morgana** section at the bottom: replaces old "Relation to Merlino" with full narrative + comparison table
- License section: explains AGPL-3.0 obligations (network service clause, attribution)
- Releases section: links to x3m-ai/Camelot

### `server/routers/update.py` (NEW FILE)
- New FastAPI router for in-app auto-update
- `GET /api/v2/update/check` — fetches `version.json` from Camelot CDN, compares with current version, returns update_available flag + release notes + download URL
- `POST /api/v2/update/apply` — requires API key, launches background update thread, returns 202
- `GET /api/v2/update/status` — returns live update progress (phase, percent, message)
- Background `_run_update()`: downloads new EXE to `C:\ProgramData\Morgana\temp\`, writes PS1 swap script, launches detached PowerShell as Administrator, server self-terminates
- Dev mode: skips actual swap, simulates progress for testing

### `server/main.py`
- **Change 1 (update router):** Registered `update_router` at prefix `/api/v2/update`
- **Change 2 (stale log fix):** Added version-stamp block in `lifespan()` startup:
  - Reads `C:\ProgramData\Morgana\db\last-version.txt`
  - If version differs from current: archives old `server.log` to `server-{old_version}.log`
  - Writes current version to stamp file
  - Prevents stale logs from previous installs appearing in new version sessions

### `ui/index.html`
- Added two update banner divs immediately after `<main class="main-content">`:
  - `id="update-banner"`: blue banner, shown when update available — displays versions, "Update Now" button, "Dismiss" button
  - `id="update-progress-banner"`: green banner, shown during update download/apply — displays phase and percent

### `ui/app.js`
- Added `setTimeout(checkForUpdate, 4000)` in `init()` IIFE — checks for updates 4 seconds after page load
- New `checkForUpdate()` function: calls `/api/v2/update/check`, shows update banner if `update_available`
- New `applyUpdate()` function: confirms with user (shows versions + release notes), calls `/api/v2/update/apply`, polls `/api/v2/update/status` every second, detects when server comes back up (health check), reloads page
- `_updateDismissed` flag to avoid re-showing dismissed banners in same session
- `_updatePollingInterval` handle for cleanup

---

## Testing

- EXE rebuilt with PyInstaller (21.8 MB) and deployed via Stop-Service → Copy → Start-Service (Admin)
- Morgana NT Service confirmed Running after deployment
- Auto-update endpoints verified reachable at `https://localhost:8888/api/v2/update/check`
- Stale log fix verified: version stamp written to `last-version.txt` on startup

---

## Related Camelot Commit

Companion commit in `x3m-ai/Camelot`:
- `morgana/Install/version.json` (NEW) — canonical latest version metadata for auto-update check
