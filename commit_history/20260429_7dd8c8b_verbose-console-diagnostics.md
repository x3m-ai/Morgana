# v0.2.7 — Verbose Console Diagnostics for EC2 / Headless Environments

**Date:** 29 April 2026
**Version:** 0.2.7
**Previous hash (v0.2.6):** 7dd8c8b
**Repos touched:** Morgana (primary), Merlino (CDN update), Camelot (installer + README)

---

## Root Cause

On EC2 Windows instances running Morgana as an NT Service (Session 0), clicking
"Console DOS" in the Merlino UI silently failed: no PowerShell window appeared,
no useful log entries existed. The root causes were:

1. `WTSGetActiveConsoleSessionId()` returns 0 on headless EC2 (no physical console).
2. `WTSQueryUserToken(0)` fails with err=5 (needs `SeTcbPrivilege`) — so the code
   fell back to `subprocess.Popen`, which spawns in Session 0 (invisible to the user).
3. No diagnostics in the log made this impossible to diagnose remotely.

---

## Changes Made

### `server/routers/console.py`

#### `_find_user_session_id()`
- Added `platform.system()` + `platform.version()` log at entry.
- Enumerated **all** WTS sessions with state names (`WTSActive`, `WTSDisconnected`, etc.)
  so every session is visible in the log with its ID, username, and state.
- Marked the selected session with `<-- SELECTING THIS`.
- Added explicit EC2 headless warning when session_id == 0 and no active sessions found.

#### `_spawn_in_user_session()` — WTSQueryUserToken section
- Logged `session_id` before calling `WTSQueryUserToken`.
- Added detailed actionable hints per error code:
  - err=5: SeTcbPrivilege missing + how to grant
  - err=1008: no token for session (user not logged in)
  - err=1314: SeAssignPrimaryTokenPrivilege missing
- Added verbose fallback message before Popen (Session 0) fallback.

#### `_spawn_in_user_session()` — CreateProcessAsUserW section
- Added `log.info("[CONSOLE] Calling CreateProcessAsUserW: session=%d cmd=%s")` before the call.
- Extended error hints to include err=6 (stale handle).
- Added separate `log.warning("[CONSOLE] FALLBACK: Popen in Session 0 ...")` with script path.

#### `open_native_console()` — post-spawn section
- Replaced single-line log with three structured log lines:
  - PS1 script path
  - PS1 console log path
  - TCP relay port + WS URL
- After spawn: `[CONSOLE] *** SPAWN RESULT: PID=... ***` + DIAGNOSTIC guidance line.

### `agent/internal/console/console.go`

#### `Open()` — WebSocket dial
- Added `[CONSOLE] === CONSOLE SESSION STARTING ===` entry log with paw, URLs, OS, arch.
- Extended `dialer.Dial` error path: logs HTTP status code from response.
- Added explicit `[CONSOLE] WebSocket connected OK` on success.

#### `Open()` — shell launch
- Added `[CONSOLE] Shell config` log block with shell binary, args, workDir before exec.

### `server/config.py`
- `version: str = "0.2.7"`

### `installer/MorganaServerSetup.iss`
- `#define MyAppVersion "0.2.7"`

### `README.md`
- Lines 295, 331: download URL bumped from `v0.2.6` to `v0.2.7`.

### `scripts/build-installer.ps1`
- Fixed `$tag:` parsing error (colon → `${tag}:`).
- Fixed `gh release view` silencing: wrapped in try/catch (script uses `$ErrorActionPreference = "Stop"`).

---

## Build Output

- `build/dist/morgana-server.exe` — raw EXE (~22 MB) auto-pushed to Merlino CDN
- `build/installer/Morgana-Server-Setup.exe` — Inno Setup installer
- `Merlino/docs/morgana/version.json` — `{"version":"0.2.7",...}`
- GitHub Release: https://github.com/x3m-ai/Morgana/releases/tag/v0.2.7

---

## Test Plan for EC2

1. Install v0.2.7 on EC2 Windows instance running Morgana as NT Service.
2. Click "Console DOS" for any agent in Merlino.
3. Tail `C:\ProgramData\Morgana\logs\server.log` and search for `[CONSOLE]`.
4. Observe: all WTS sessions listed, exact error code for WTSQueryUserToken/CreateProcessAsUserW,
   and whether fallback to Session 0 occurred.
5. If err=5 on WTSQueryUserToken: grant `SeTcbPrivilege` to the service account.
