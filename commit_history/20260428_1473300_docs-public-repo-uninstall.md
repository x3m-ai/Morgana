# docs: Morgana repo public + uninstall/reinstall guide

**Date:** 28 April 2026
**Branch:** master

---

## Summary

Documentation updates following the public release of x3m-ai/Morgana on GitHub.

---

## Files Modified

### `README.md`
- Bumped version header from `0.2.4` to `0.2.5`
- Added **Uninstall / Fresh Reinstall** section with 4-step guide:
  - Step 1: Stop service + `nssm remove Morgana confirm`
  - Step 2: Run Inno Setup uninstaller silently via `unins000.exe /VERYSILENT`
  - Step 3: Remove `C:\ProgramData\Morgana` data (optional)
  - Step 4: Download latest installer from Camelot CDN and run silently
- Added note clarifying `Morgana.ps1` is a dev-only utility, not part of the installed product

### `.github/copilot-instructions.md`
- Updated version header from `0.2.4` to `0.2.5`
- Changed repo visibility from `(private)` to `(public)` in header and workspace table
