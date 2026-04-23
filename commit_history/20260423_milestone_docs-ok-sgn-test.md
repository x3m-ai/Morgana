# Commit: MILESTONE - Documentation looks ok - test installation in SGN

**Date:** 2026-04-23  
**Branch:** main  
**Repos committed:** Morgana, Merlino, Camelot  

---

## Summary

Milestone checkpoint before SGN (staging) installation test.
Documentation for Morgana community release reviewed and corrected across all repos.

---

## Changes

### Morgana
- `atomics/` submodule pointer updated (latest Atomic Red Team library sync)

### Merlino
- Full production build committed to `docs/` for CF Pages deployment (v1.5.0, commit 45378cb)
- New chunk files added: 140, 239, 306, 312, 434, 481, 482, 499, 663, 715, 814, 925, 931, d3, react, vendors
- Compressed `.gz` variants for all assets
- Deleted stale `.js.map` files removed from `docs/`
- `docs/version.json` updated

### Camelot
- `laboratories/Merlino User Guide-Lab 03--Red Team Testing with Morgana Arsenal.md`:
  - Image reference added to Step 8 (Morgana Chains execution screenshot)
- `laboratories/img/325-morgana-chains-execute.png`: new screenshot — Morgana Chains list ready for execution
- `laboratories/img/314-morgana-adversaries-list.png`: updated screenshot

---

## Documentation corrections (previous commits this session)

- SSL Certificate section: installer handles cert automatically on clean install — no manual `certutil` steps
- API Key section: user generates key from Morgana web UI → Admin → Generate API Key (not from file on disk)
- Desktop shortcut: installer optionally creates desktop shortcut for quick access to Morgana UI
- All Lab 01/02/03: "Caldera" and "Arsenal" references removed
- Install/README.md: API key and Merlino integration sections updated to match real flow
