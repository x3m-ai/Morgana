# MILESTONE - morgana update to test

**Date:** 2026-04-28  
**Commits:** 50ddc3e, 75b9588, dd1bdbf, b725eed, 83d6a27  
**Repos affected:** Morgana, Merlino, Camelot

---

## Summary

Full milestone covering Morgana CDN migration, Merlino distribution pipeline, and EC2/SSM operational improvements.

---

## Changes

### Morgana — `server/routers/update.py`
- Changed `_VERSION_JSON_URL` from GitHub raw Camelot to `https://merlino.x3m.ai/morgana/version.json`
- Updated docstring to reflect new Merlino CF Pages CDN as primary distribution point
- The in-app auto-update banner now fetches version.json from Cloudflare Pages (faster, no GitHub rate limits)

### Morgana — `scripts/build-installer.ps1`
- Added publish block at end of build: automatically copies installer (`Morgana-Server-Setup.exe`), raw server EXE (`morgana-server.exe`), and generated `version.json` to `Merlino/docs/morgana/`
- version.json is generated from `server/config.py` version string at build time
- Download URLs in version.json point to `https://merlino.x3m.ai/morgana/`

### Morgana — `ui/app.js` + `ui/index.html` + `ui/style.css`
- Added **Uninstall** button (orange, `btn-warning`) to each agent row in the agents table
- Added `removeAgentModal` with platform-specific uninstall commands (Windows + Linux)
- Windows path: `Stop-Service MorganaAgent`, `sc.exe delete`, `Remove-Item` data folders
- Linux path: `systemctl stop/disable`, remove systemd unit, remove binary and data dirs
- Modal auto-hides the irrelevant platform block based on agent platform field
- Copy button for each command block
- Added `showRemoveAgentModal`, `closeRemoveAgentModal`, `copyRemoveCmd` functions
- Added `.btn-warning` CSS class (orange `#e65100`)

### Morgana — `README.md`
- Added Troubleshooting section: file locks during uninstall on SSM
- Documented causes: `unins000.exe` zombie, `morgana-agent.exe` child process
- Added `Restart-Computer -Force` as nuclear option
- Updated SSM Step 6 to use `/VERYSILENT /LOG` with `Get-Content` to show install output

### Merlino — `docs/morgana/`
- New folder created as CF Pages CDN for Morgana binaries
- Files: `Morgana-Server-Setup.exe` (28 MB), `morgana-server.exe` (22 MB), `version.json`
- Served at `https://merlino.x3m.ai/morgana/`

### All three repos — `.github/copilot-instructions.md`
- Updated publish pipeline documentation to reference Merlino CDN as primary distribution
- Added CDN table with all three URLs (installer, raw EXE, version.json)
- Camelot remains in sync but is no longer the auto-update source

---

## Test checklist

- [ ] EC2: download installer from `https://merlino.x3m.ai/morgana/Morgana-Server-Setup.exe`
- [ ] Auto-update: bump version in next release, verify banner appears in Morgana UI
- [ ] Uninstall modal: click Uninstall button on agent row, verify platform-correct commands shown
- [ ] Build pipeline: run `scripts/build-installer.ps1`, verify Merlino CDN folder is updated
