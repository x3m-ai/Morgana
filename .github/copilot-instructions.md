# Morgana - Agent Project Guide

> **Version:** 0.2.5 | **April 2026** | **Publisher:** X3M.AI Ltd (UK) | **Author:** Nino Crudele
> **Repo:** `x3m-ai/Morgana` (public) | **Community releases:** `x3m-ai/Camelot` (public)

---

## UNIFIED WORKSPACE

This repo is part of the **X3M.AI multi-root workspace** (`X3MAI.code-workspace` in `C:\Users\ninoc\OfficeAddinApps\`).
All three projects are open simultaneously in the same VS Code window:

| Folder | Repo | copilot-instructions | Role |
|--------|------|----------------------|------|
| `Merlino/` | `x3m-ai/Merlino` (private) | `Merlino/.github/copilot-instructions.md` | Excel Add-in — command & intelligence layer |
| `Morgana/` | `x3m-ai/Morgana` (public) | `Morgana/.github/copilot-instructions.md` | Red Team Server + Agent — execution layer |
| `Camelot/` | `x3m-ai/Camelot` (public) | `Camelot/.github/copilot-instructions.md` | Community releases, installers, templates, labs |

All three `copilot-instructions.md` files are loaded simultaneously by Copilot when the workspace is open.

---

## CRITICAL CONSTRAINTS

1. **NEVER commit or push** — Do NOT run `git commit` or `git push` unless the user explicitly asks for it. No exceptions.
2. **NO EMOJI in code** — No emoji in `.py`, `.go`, `.js`, `.html` files. Use `[START]`, `[SUCCESS]`, `[ERROR]`, `[INFO]`, `[WARN]` tags. Reason: UTF-8 corruption breaks automation.
3. **Merlino integration layer is FROZEN** — The API surface consumed by Merlino (`/api/v2/merlino/*`, `/api/v2/agents`) must remain backward compatible forever. Merlino users switch from Caldera to Morgana by changing URL + API key only — zero Merlino code changes.
4. **Camelot is the release gate** — When a new installer or public asset is ready, copy it to `Camelot/morgana/Install/` and commit there. Never publish binaries directly from this repo.
5. **Defender exclusion** — Always write temp files and PS1 scripts to `C:\ProgramData\Morgana\temp\` (Defender-excluded). Never use `C:\Windows\Temp\` — Defender terminates PowerShell processes there.
6. **commit_history folder is MANDATORY** — Every time the user asks to commit and push, create a Markdown file in `commit_history/` BEFORE committing. Filename: `YYYYMMDD_<short-hash>_<slug>.md`. Include: date, commit hash(es), full description of every change (files modified, root causes, fixes, test results). Include the commit_history file in the same commit.

---

## WHAT IS MORGANA

Morgana is the X3M.AI Red Team execution platform for Purple Teaming. It **replaces Caldera completely**.
Windows-native, lightweight, zero dependencies, tightly integrated with Merlino and Atomic Red Team.

Not a plugin. Not a wrapper. A first-class product.

### Domain model — use ONLY these terms, never Caldera names

| Morgana term | Meaning | Caldera equivalent |
|---|---|---|
| **Script** | Atomic execution unit (PowerShell/bash/cmd/python) | Ability |
| **Chain** | Ordered sequence of scripts forming a kill chain | Adversary |
| **Test** | Single execution instance, linked to a Merlino row | Operation |
| **Campaign** | Named exercise grouping multiple Tests | (new concept) |
| **Agent** | OS Service installed on a target machine | Agent |
| **Job** | Internal dispatch record (server -> agent) | Task |

---

## TECH STACK

| Layer | Technology |
|-------|------------|
| Server | Python 3.12 + FastAPI + SQLAlchemy + SQLite, port 8888 HTTPS |
| Agent | Go 1.22 — single binary, NT Service (Windows) / systemd (Linux) |
| Script library | Red Canary Atomic Red Team (YAML, git submodule at `atomics/`) |
| UI | Vanilla HTML5/JS/CSS3 dark theme (accent `#667eea`, base `#1a1a1a` — matches Merlino) |
| Build | PyInstaller (server EXE) + Go build (agent EXE) + Inno Setup (installer) |

---

## KEY COMMANDS

```powershell
# Dev (process-based, no service)
cd C:\Users\ninoc\OfficeAddinApps\Morgana
.\Morgana.ps1 start 8888 -NoWindow   # background
.\Morgana.ps1 stop
.\Morgana.ps1 status

# Build full installer
powershell -File scripts\build-installer.ps1
# Output: build\installer\Morgana-Server-Setup.exe

# Quick EXE-only rebuild (no installer, swap in place)
& "server\.venv\Scripts\python.exe" "build\build-server.py"
Stop-Service Morgana -Force; Start-Sleep 3
Copy-Item "build\dist\morgana-server.exe" "C:\Program Files\Morgana Server\morgana-server.exe" -Force
Start-Service Morgana

# NT Service (requires Administrator)
.\Morgana.ps1 install -LogLevel INFO -AutoStart
.\Morgana.ps1 start
.\Morgana.ps1 stop
.\Morgana.ps1 uninstall
```

Web UI: `https://localhost:8888/ui/`

---

## DEPLOY WORKFLOW

### Normal workflow (code change — test without reinstalling)
1. Quick EXE rebuild (see above)
2. Logs at `C:\ProgramData\Morgana\logs\server.log`

### Full installer (ONLY when explicitly requested, or to test installer itself)
```powershell
powershell -File scripts\build-installer.ps1
Start-Process "build\installer\Morgana-Server-Setup.exe" -ArgumentList "/VERYSILENT" -Verb RunAs -Wait
```

### Persistent data — never touch unless debugging
All runtime data: `C:\ProgramData\Morgana\`

| Path | Content |
|------|--------|
| `certs\server.crt` / `server.key` | TLS cert (auto-generated) |
| `db\morgana.db` | SQLite database |
| `logs\server.log` | Server log |
| `data\master.key` | Persisted API key |
| `atomics\atomics\` | Atomic Red Team YAML library |
| `temp\` | Defender-excluded temp dir for PS1 scripts |

---

## PUBLISH PIPELINE

When a new version is ready (user must explicitly ask for commit/push):
1. Bump `server/config.py` → `version = "X.Y.Z"`
2. Bump `installer/MorganaServerSetup.iss` → `#define MyAppVersion "X.Y.Z"`
3. Run `powershell -File scripts\build-installer.ps1`
4. git commit + push on Morgana
5. Copy installer to `Camelot/morgana/Install/Morgana-Server-Setup.exe`
6. Update `Camelot/morgana/Install/README.md` version header
7. git commit + push on Camelot

---

## KEY DOCS

| Doc | When to read |
|-----|--------------|
| `docs/ARCHITECTURE.md` | 3-tier architecture, security model |
| `docs/DOMAIN_MODEL.md` | Entity definitions + SQL schema |
| `docs/API_CONTRACT.md` | All HTTP endpoints |
| `docs/CHAINS_API.md` | Chain CRUD, flow format, execution |
| `docs/AGENT_PROTOCOL.md` | Agent lifecycle, beacon loop, NT Service |
| `docs/MERLINO_INTEGRATION.md` | How Merlino connects to Morgana |


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
| Build | PyInstaller (server EXE) + Go build (agent EXE) + Inno Setup installer |

---

## DEPLOY WORKFLOW — CRITICAL

**Code fixes and new features do NOT require a full reinstall. Rebuild only the EXE and swap it.**

### Normal workflow (code change -> test in place)
```powershell
cd C:\Users\ninoc\OfficeAddinApps\Morgana
# 1. Build only the EXE
& "server\.venv\Scripts\python.exe" "build\build-server.py"
# 2. Stop, swap, restart (run as admin)
Stop-Service Morgana -Force; Start-Sleep 3
Copy-Item "build\dist\morgana-server.exe" "C:\Program Files\Morgana Server\morgana-server.exe" -Force
Start-Service Morgana
```

### Full reinstall (ONLY when explicitly requested by the user, or to test the installer itself)
```powershell
powershell -File scripts\build-installer.ps1   # builds EXE + Inno Setup package
# Produces: build\installer\Morgana-Server-Setup.exe
Start-Process "build\installer\Morgana-Server-Setup.exe" -ArgumentList "/VERYSILENT" -Verb RunAs -Wait
```

### Persistent data (survives all restarts and reinstalls)
All runtime data lives in `C:\ProgramData\Morgana\` — never touch it unless debugging.

| Path | Content |
|------|---------|
| `certs\server.crt` / `server.key` | TLS cert (auto-generated on first run) |
| `db\morgana.db` | SQLite database |
| `logs\server.log` | Server log |
| `data\master.key` | Persisted API key |
| `atomics\atomics\` | Atomic Red Team YAML library |

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
