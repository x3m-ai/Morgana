# Commit: fix: localStorage quota exceeded + console invisible on RDP (Windows Server 2022)

**Date:** 2026-04-27
**Branch:** master
**Repo:** Morgana

---

## Root cause 1 -- Console invisible on EC2 / Windows Server 2022 via RDP

**File:** `server/routers/console.py`

`WTSGetActiveConsoleSessionId()` returns the PHYSICAL console session.
On EC2 instances and VMs accessed exclusively via RDP, the physical console has
no logged-in user (returns session 0, the NT Service session). The PowerShell
window was spawned in Session 0, invisible to the RDP user. `Console.ReadKey()`
then threw an exception because there was no console attached, the PS1 exited
immediately, and the TCP relay got a `ConnectionResetError WinError 10054`.

**Fix:**
- Added `_find_user_session_id()` function that:
  1. Calls `WTSGetActiveConsoleSessionId()` first (works for physical console)
  2. If session_id == 0, falls back to `WTSEnumerateSessionsW` to find the
     first active non-service session (RDP sessions included)
  3. Logs clearly which session is being used and why
- `_spawn_in_user_session()` now calls `_find_user_session_id()` instead of
  calling `WTSGetActiveConsoleSessionId()` directly

**Result:** Console PowerShell window now opens correctly on EC2 instances
accessed via RDP with no physical console.

---

## Root cause 2 -- localStorage quota exceeded on Save Morgana

**File:** `N/A (Merlino fix — see Merlino commit)`

Documented here for reference: the quota was filled by Merlino's
`file-logger-service.ts` appending log lines to a localStorage key
without any size limit. Fixed in Merlino (see Merlino commit).
