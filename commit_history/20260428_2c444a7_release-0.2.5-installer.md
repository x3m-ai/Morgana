# Morgana v0.2.5 — Official Release with Auto-Update and AGPL-3.0

**Date:** 28 April 2026  
**Commit hash:** (to be updated after commit)  
**Branch:** master

---

## Summary

Official 0.2.5 release. Bumps version numbers, bundles the auto-update router, and produces the new installer distributed via Camelot.

---

## Files Modified

### `server/config.py`
- Bumped `version` from `"0.2.4"` to `"0.2.5"`

### `installer/MorganaServerSetup.iss`
- Bumped `#define MyAppVersion` from `"0.2.4"` to `"0.2.5"`

### `server/routers/update.py` (previously uncommitted)
- New router: `/api/v2/update/check` and `/api/v2/update/apply`
- Checks `version.json` from Camelot CDN via HTTPS
- Downloads new EXE to `C:\ProgramData\Morgana\temp\` (Defender-excluded)
- Swap executed via detached PowerShell script (Stop/Copy/Start NT Service)
- Key fix: uses `utf-8-sig` decoder to handle BOM-encoded JSON from PowerShell

---

## What Changed End-to-End

1. **Auto-update system** — in-app update check + one-click apply via `/api/v2/update`
2. **AGPL-3.0 license** — LICENSE replaced from MIT to AGPL-3.0 (X3M.AI Ltd copyright)
3. **README rewrite** — open source positioning, Merlino+Morgana joint narrative, no Caldera references
4. **Stale log fix** — `server/main.py` lifespan no longer re-opens stale log handles across restarts
5. **Camelot publish** — `Morgana-Server-Setup.exe` (0.2.5) and `morgana-server.exe` raw EXE pushed to Camelot CDN

---

## Build Details

- PyInstaller: `build/dist/morgana-server.exe`
- Inno Setup: `build/installer/Morgana-Server-Setup.exe`
- Both artifacts copied to `Camelot/morgana/Install/` and committed to Camelot

---

## Test Results

- Auto-update check: confirmed working (version banner shown after 4s on UI page load)
- BOM decode fix: version.json parsed correctly with `utf-8-sig`
- NT Service swap: tested manually via Stop/Copy/Start — server comes back on HTTPS within ~5s
- Full installer: Inno Setup compile successful (4.4s), output verified
