# Morgana - Agent Project Guide

> **Version:** 0.2.0 | **April 2026** | **Publisher:** X3M.AI Ltd (UK) | Author: Nino Crudele
> **Repo:** `x3m-ai/Morgana` (private)

---

## CRITICAL CONSTRAINTS

1. **NEVER commit or push** — Do NOT run `git commit` or `git push` unless the user explicitly asks for it. No exceptions.
2. **NO EMOJI in code** — No emoji in `.py`, `.go`, `.js`, `.html` files. Use `[START]`, `[SUCCESS]`, `[ERROR]` tags. Reason: UTF-8 corruption breaks automation.
3. **Merlino integration layer is FROZEN** — The Merlino side of the Caldera/Morgana integration must not change. See Merlino copilot-instructions for details.
4. **commit_history folder is MANDATORY** — Every time the user asks to commit and push, you MUST create a Markdown file in `commit_history/` BEFORE committing. The filename format is `YYYYMMDD_<short-hash>_<slug>.md` where `<short-hash>` is the hash of the most recent existing commit (7 chars) and `<slug>` is a short kebab-case description. The file must contain: date, commit hash(es), full description of every change made (files modified, root causes, fixes, test results). Include the commit_history file in the same commit. No exceptions.

---

## WHAT IS MORGANA

Morgana is the X3M.AI Red Team execution platform, replacing Caldera. Windows-native, lightweight, zero dependencies, tightly integrated with Merlino and Atomic Red Team.

## TECH STACK

| Layer | Technology |
|-------|------------|
| Server | Python 3.12 + FastAPI + SQLAlchemy + SQLite, port 8888 |
| Agent | Go 1.22 - single binary, NT Service (Windows) / systemd (Linux) |
| Script library | Red Canary Atomic Red Team (YAML, git submodule at `atomics/`) |
| UI | Vanilla HTML5/JS/CSS3 dark theme, no framework |
| Build | PyInstaller (server EXE) + Go build (agent EXE) |

## DOMAIN MODEL

| Morgana term | Meaning | Caldera equivalent |
|---|---|---|
| **Script** | Atomic execution unit | Ability |
| **Chain** | Ordered sequence of scripts | Adversary |
| **Test** | Single execution instance | Operation |
| **Campaign** | Named exercise grouping multiple Tests | (new concept) |
| **Agent** | OS Service on a target machine | Agent |
| **Job** | Internal dispatch record (server -> agent) | Task |

## SERVER MANAGER: Morgana.ps1

All server operations go through `Morgana.ps1` (root of the repo).

```powershell
# Process-based (dev, no service installed)
.\Morgana.ps1 start              # foreground
.\Morgana.ps1 start 8888 -NoWindow  # background hidden
.\Morgana.ps1 stop
.\Morgana.ps1 restart
.\Morgana.ps1 status

# NT Service (requires Administrator)
.\Morgana.ps1 install                          # errors-only to Event Viewer, manual start
.\Morgana.ps1 install -LogLevel INFO -AutoStart # file log + auto-start at boot
.\Morgana.ps1 start    # sc start (service path) or process-based fallback
.\Morgana.ps1 stop
.\Morgana.ps1 restart
.\Morgana.ps1 uninstall
```

**Service name:** `Morgana`  
**Service script:** `server/morgana_service.py` (pywin32, requires `pywin32>=305` in venv)  
**Logging:** lifecycle events always to Windows Application Event Log (source=Morgana); app-level file log at `server/logs/service.log` only if `-LogLevel` was set at install time (stored in registry `HKLM\...\Services\Morgana\Parameters\LogLevel`).  
**Recovery:** auto-restart on failure (configured by `Morgana.ps1 install`).  

Web UI: `http://localhost:8888/ui/`
