# Commit: MILESTONE - Tests to go for updates all three areas ok

**Date:** 2026-04-28  
**Repo:** x3m-ai/Morgana  
**Short hash (pre-commit):** acbf2e5  

---

## Summary

Milestone commit confirming end-to-end update flow is working across all three repositories:
- Morgana server (this repo)
- Merlino CDN (docs/morgana/)
- Camelot community (morgana/Install/)

## Changes in this commit

### `ui/app.js`
- `checkForUpdate()` now logs `console.warn` when `check_error` is present in the update response, making auto-update failures visible in the browser console.

### `version.json` (repo root)
- Version manifest served via `raw.githubusercontent.com/x3m-ai/Morgana/master/version.json`
- Content: `{"version":"0.2.7","release_notes":"Verbose console diagnostics for EC2 headless environments","download_url":"https://github.com/x3m-ai/Morgana/releases/latest/download/Morgana-Server-Setup.exe"}`

## Test results

- Local Morgana v0.2.7 running as NT Service: OK
- `/api/v2/update/check` returns `current_version: 0.2.7`, `latest_version: 0.2.7`, `check_error: null`: OK
- Auto-update version.json URL (`raw.githubusercontent.com`) resolving correctly: OK
- EC2 install of v0.2.7 via GitHub Releases installer: OK
- All three repos (Morgana, Merlino, Camelot) in sync at v0.2.7: OK
