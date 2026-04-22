# MILESTONE - deployment in tests e working in scripts area

**Date:** 2026-04-22
**Base commit:** 9473ada
**Branch:** master

---

## Changes

### Installer / Build pipeline
- `scripts/build-installer.ps1` — Full build pipeline: PyInstaller EXE + Inno Setup package
- `scripts/post-install.ps1` — Post-install NSSM service setup
- `server/morgana-server.spec` — PyInstaller spec file
- `installer/` — Inno Setup project files

### config.py — Frozen-EXE path fix
- Added `_FROZEN` / `_DATA_DIR` logic: when running as PyInstaller EXE, all persistent paths (certs, db, logs, atomics) default to `C:\ProgramData\Morgana\` instead of `_MEIPASS` temp folder. NSSM env vars always override.
- Fixed `ssl_certfile`, `ssl_keyfile`, `db_path`, `log_file`, `atomic_path` defaults.

### server/routers/scripts.py — Bulk delete endpoint
- Added `DELETE /api/v2/scripts` — bulk delete all scripts (or filtered by `?source=`), cleaning up FK dependents (Job, Test, ChainStep) in a single transaction.

### ui/app.js — Scripts area fixes
- `deleteAllScripts()`: replaced N individual DELETE calls with single call to new bulk endpoint; calls `loadScripts()` after to reload from server.
- `loadScripts()`: removed early-return cache guard so table always refreshes from server after delete.
- `_scriptSort` sort state restored (was accidentally dropped in previous refactor).
- `refreshCanaryScripts()`: full rewrite — POST starts download, polls `GET /atomics/download-progress` every 500ms for real % progress.

### server/routers/admin.py — Real progress download
- Background thread (`_run_download`) streams ZIP with `Content-Length`-based real %, extracts per-file, imports to DB — all updating thread-safe `_dl_state`.
- `POST /atomics/download` returns immediately `{"status":"started"}`.
- `GET /atomics/download-progress` polling endpoint added.

### ui/style.css — Progress bar
- Removed indeterminate CSS animation; bar now shows real % via `width` + CSS transition.

### ui/index.html — UI updates
- Added `<span id="canary-pct">` percentage label next to download title.
- Cache buster bumped to `v=24`.

### .github/copilot-instructions.md
- Added DEPLOY WORKFLOW section: build-only EXE swap is the standard workflow; full reinstall only when explicitly requested or to test the installer.
- Added persistent data paths table.
- Added Inno Setup installer to tech stack.

### Other
- `server/routers/console.py`, `server/routers/compat/agents.py`, `server/main.py` — minor fixes from this session.
- `deploy-ui-hotfix.ps1` — utility script for quick UI hotfix deploy.
