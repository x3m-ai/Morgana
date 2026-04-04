# MILESTONE - implementato sistema di duplicazione script morgana

**Date:** 2026-04-04
**Base commit:** dbabe3f
**Branch:** master

## Summary

Removed the "custom" source concept entirely. All user-created and duplicated scripts
are now saved under the "morgana" source, building the Morgana script library over time.

## Changes

### server/routers/scripts.py
- Default source for new scripts changed from `"custom"` to `"morgana"`

### server/routers/admin.py
- Stats query now counts `source = 'morgana'` instead of `'custom'`
- API field renamed `custom_scripts_in_db` -> `morgana_scripts_in_db`

### ui/app.js
- `openNewScriptModal`: source field defaults to `"morgana"`
- `duplicateScript`: POST body explicitly sets `source: "morgana"`
- `openScriptModal`: source display fallback is `"morgana"`
- Read-only check: `source === "atomic-red-team"` (morgana scripts are always editable)
- Admin stat reads `morgana_scripts_in_db`
- Cache-busting bumped to `?v=4`

### ui/index.html
- Stat label "Custom Scripts" renamed to "Morgana Scripts"
- Cache-busting bumped to `?v=4`

### DB (live migration)
- 9 existing `source='custom'` scripts updated to `source='morgana'` via direct SQLite UPDATE
