# Morgana

<p align="center">
  <img src="ui/assets/morgana-logo.png" alt="Morgana" width="320" />
</p>

> **Version:** 0.2.5 | **April 2026** | **License:** AGPL-3.0
> **Publisher:** X3M.AI Ltd (UK) | **Author:** Nino Crudele
> **Companion to:** [Merlino Excel Add-in](https://merlino.x3m.ai) — free, no registration
> **Community releases:** [x3m-ai/Camelot](https://github.com/x3m-ai/Camelot)

---

## What is Morgana?

Morgana is a **free, open-source Purple Team execution platform** — the native execution engine designed to work alongside the [Merlino Excel Add-in](https://merlino.x3m.ai).

Together, **Merlino + Morgana** form a complete, integrated Purple Teaming platform:

- **[Merlino](https://merlino.x3m.ai)** is the command and intelligence center — a free Microsoft Excel Add-in for MITRE ATT&CK threat mapping, CTI correlation, detection coverage analysis, and reporting. No registration. No backend. All data stays local.
- **Morgana** is the execution engine — it deploys agents on target machines, runs red team scripts mapped to MITRE ATT&CK techniques, and streams results back to Merlino in real time.

Used together they cover the full Purple Team lifecycle: from threat intelligence and technique selection in Merlino, to controlled adversary simulation execution via Morgana, with live feedback and automated reporting back in Excel. This is **advanced Purple Teaming as it should be** — precise, integrated, and entirely under your control.

Morgana is a purpose-built platform designed from the ground up for operational red teamers:
- Domain model designed around real-world kill chains, not academic research
- Agents install as native OS services (NT Service on Windows, systemd on Linux) — no dependencies, single binary
- 6000+ scripts from [Atomic Red Team](https://github.com/redcanaryco/atomic-red-team), fully indexed and searchable by MITRE technique
- Clean HTTP API consumed directly by Merlino
- Dark-theme web UI for standalone use — agents, scripts, chains, campaigns, logs, all in one place
- In-app auto-update: new versions available as a one-click update from the Admin panel

---

## Domain Model

```
SCRIPT       Unit of execution. Single PowerShell/bash command or file.
             Maps 1:1 to a MITRE ATT&CK technique (TCode).

CHAIN        Ordered sequence of Scripts forming an attack path.
             Equivalent to a kill chain or playbook scenario.

TEST         An execution instance - a Chain or Script launched against an Agent.
             Records state, output, exit code, duration.
             Maps directly to Merlino's Tests table.

CAMPAIGN     A named group of Tests with a shared objective.
             e.g. "Q1 2026 Purple Team - Ransomware Scenario"

AGENT        A Morgana service installed on a target machine.
             NT Service on Windows, systemd daemon on Linux.
             Communicates with the Morgana server via HTTPS polling.
```

---

## Architecture

```
Merlino Excel Add-in (Windows)
        |
        | HTTP - /api/v2/merlino/*
        v
Morgana Server (FastAPI, localhost:8888)
        |
        | SQLite (morgana.db)
        |
        | HTTP - /api/v2/agent/poll + /result
        v
Morgana Agent (NT Service / systemd daemon)
        |
        | subprocess
        v
PowerShell / cmd / bash executor
        |
        v
Atomic Red Team scripts + custom scripts
```

---

## Installation

### Option A — Windows Installer (recommended)

Download the latest `Morgana-Server-Setup.exe` from the [Camelot releases page](https://github.com/x3m-ai/Camelot/tree/main/morgana/Install) and run it as Administrator.

The installer:
- Installs the Morgana server as a **Windows NT Service** (auto-starts at boot)
- Generates a self-signed TLS certificate (HTTPS on port 8888)
- Generates a random master API key stored in `C:\ProgramData\Morgana\data\master.key`
- Creates a Desktop shortcut to the Morgana web UI
- Downloads the Atomic Red Team script library (optional, ~300 MB)

After installation, open the web UI at `https://localhost:8888/ui/` and log in with the credentials shown during setup.

---

### Option B — Manual Installation from Source

#### Prerequisites

- Python 3.11 or 3.12
- Go 1.22+ (for the agent binary only)
- Git

#### 1. Clone the repository

```bash
git clone https://github.com/x3m-ai/Morgana.git
cd Morgana
```

#### 2. Set up the Python virtual environment

```bash
cd server
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# Linux / macOS
.venv/bin/pip install -r requirements.txt
```

#### 3. Build the Go agent (Windows)

```powershell
cd ..\agent
go build -o ..\build\morgana-agent\morgana-agent.exe .\cmd\agent\
```

#### 4. Build the Go agent (Linux)

```bash
cd agent
go build -o ../build/morgana-agent/morgana-agent ./cmd/agent/
```

#### 5. Start the server

```powershell
# Windows — run as Administrator (generates certs and master key on first run)
cd server
.venv\Scripts\python.exe main.py
```

```bash
# Linux
cd server
.venv/bin/python main.py
```

Server starts at `https://localhost:8888` (HTTPS) on first run after generating a self-signed certificate.

The master API key is printed in the console on first start and saved to:
- Windows: `C:\ProgramData\Morgana\data\master.key`
- Linux: `/var/lib/morgana/data/master.key`

#### 6. Open the web UI

Navigate to `https://localhost:8888/ui/` and accept the self-signed certificate warning.

#### 7. Install an agent on a target machine

```powershell
# Windows target — run as Administrator
.\scripts\install-agent-windows.ps1 -ServerUrl "https://YOUR_SERVER_IP:8888" -Token "YOUR_API_KEY"
```

```bash
# Linux target
chmod +x scripts/install-agent-linux.sh
sudo ./scripts/install-agent-linux.sh --server "https://YOUR_SERVER_IP:8888" --token "YOUR_API_KEY"
```

#### 8. Connect Merlino

In the Merlino **Settings** taskpane, set:
- **Morgana URL**: `https://YOUR_SERVER_IP:8888`
- **API Key**: your master key or a key created in the Morgana Admin panel

---

## Quick Start (process-based, no service — dev/testing only)

```powershell
# Windows — dev mode, no service installation needed
cd C:\path\to\Morgana
.\Morgana.ps1 start 8888 -NoWindow   # start in background
.\Morgana.ps1 stop
.\Morgana.ps1 status
```

---

## Uninstall / Fresh Reinstall

> **AWS SSM / headless sessions:** The Inno Setup uninstaller requires a desktop session and will hang on SSM even with `/SILENT`. Use the **SSM / Headless** steps below instead.

---

### On a normal desktop session (RDP)

Run all commands **one at a time** as **Administrator** in PowerShell.

**Step 1 — Stop the service**
```powershell
Stop-Service Morgana -Force
```

**Step 2 — Remove the service registration**
```powershell
Start-Process "C:\Program Files\Morgana Server\tools\nssm.exe" -ArgumentList "remove Morgana confirm" -Verb RunAs -Wait
```

**Step 3 — Run the Inno Setup uninstaller**
```powershell
Start-Process "C:\Program Files\Morgana Server\unins000.exe" -Verb RunAs -Wait
```

**Step 4 — Remove all data (optional)**
```powershell
Remove-Item "C:\ProgramData\Morgana" -Recurse -Force
```

**Step 5 — Download the latest installer**
```powershell
Invoke-WebRequest -Uri "https://github.com/x3m-ai/Camelot/raw/main/morgana/Install/Morgana-Server-Setup.exe" -OutFile "$env:TEMP\Morgana-Server-Setup.exe"
```

**Step 6 — Run the installer**
```powershell
Start-Process "$env:TEMP\Morgana-Server-Setup.exe" -Verb RunAs -Wait
```

---

### On AWS SSM or any headless session (no desktop)

Run all commands **one at a time** as **Administrator**. No GUI, no hanging.

**Step 1 — Stop the service**
```powershell
Stop-Service Morgana -Force
```

**Step 2 — Delete the service**
```powershell
sc.exe delete Morgana
```

**Step 3 — Delete the install folder**
```powershell
Remove-Item "C:\Program Files\Morgana Server" -Recurse -Force
```

**Step 4 — Delete all data (optional)**
```powershell
Remove-Item "C:\ProgramData\Morgana" -Recurse -Force
```

**Step 5 — Download the latest installer**
```powershell
Invoke-WebRequest -Uri "https://github.com/x3m-ai/Camelot/raw/main/morgana/Install/Morgana-Server-Setup.exe" -OutFile "$env:TEMP\Morgana-Server-Setup.exe"
```

**Step 6 — Run the installer silently**
```powershell
Start-Process "$env:TEMP\Morgana-Server-Setup.exe" -ArgumentList "/VERYSILENT" -Wait
```

**Step 7 — Verify the service is running**
```powershell
Get-Service Morgana
```

After installation the server starts automatically as an NT Service and the UI is available at `https://localhost:8888/ui/`.

> **Note:** `Morgana.ps1` is a developer utility included only in the source repository (`x3m-ai/Morgana`). It is not part of the installed product. End users manage the server exclusively via the steps above or from the Windows Services panel.

---

## Troubleshooting

### `Remove-Item` fails with "process cannot access the file" during uninstall

**Cause:** One or more processes still have a lock on files in `C:\Program Files\Morgana Server`. Common culprits:

- `unins000.exe` — the Inno Setup uninstaller was launched earlier (even with `/SILENT`) and is still running as a background process with a GUI waiting for input that cannot be displayed on SSM
- `morgana-agent.exe` — the agent binary was running independently
- NSSM itself holding a handle on the service EXE

**Fix — kill all processes from that folder, then delete:**

```powershell
Get-Process | Where-Object { $_.Path -like "*Morgana Server*" } | Stop-Process -Force
```

```powershell
Remove-Item "C:\Program Files\Morgana Server" -Recurse -Force
```

**If that still fails**, reboot the machine. After reboot no process will hold a lock:

```powershell
Restart-Computer -Force
```

Then reconnect via SSM and continue from the `Remove-Item` step.

---

## Tech Stack

| Component | Technology |
|---|---|
| Server | Python 3.12 + FastAPI + SQLAlchemy + SQLite |
| Agent | Go 1.22 - single binary, zero dependencies |
| UI | HTML5 / vanilla JS / CSS3 (dark theme matching Merlino) |
| Atomic library | Atomic Red Team YAML (git submodule) |
| Packaging | PyInstaller (server), Go build (agent) |

---

## Project Structure

```
Morgana/
├── server/          FastAPI backend - API, business logic, SQLite
├── agent/           Go agent - NT Service / systemd daemon
├── ui/              Web UI - dark theme dashboard
├── atomics/         Git submodule: redcanaryco/atomic-red-team
├── scripts/         Install helpers for agents
├── docs/            Full architecture and protocol documentation
└── build/           Build and packaging scripts
```

---

## Merlino API Compatibility

Morgana exposes the full `/api/v2/merlino/*` surface that Merlino expects:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/merlino/synchronize` | POST | Receive Tests table, create jobs |
| `/api/v2/merlino/realtime` | GET | Real-time ops metrics for dashboard |
| `/api/v2/merlino/ops-graph` | POST | Force graph dataset |
| `/api/v2/merlino/ops-graph/problem-details` | GET | Problem drilldown |
| `/api/v2/merlino/ops-graph/operation-details` | GET | Operation drilldown |
| `/api/v2/merlino/ops-graph/agent-details` | GET | Agent drilldown |
| `/api/v2/agents` | GET | Agent list |

---

## License

Morgana is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see [LICENSE](LICENSE).

This means:
- You can use, study, modify, and distribute Morgana freely
- If you run a modified version as a network service (hosted/SaaS), you must release your modifications under the same license
- Attribution to X3M.AI Ltd must be preserved

---

## Releases

Pre-built Windows installers and binaries are published in the [x3m-ai/Camelot](https://github.com/x3m-ai/Camelot/tree/main/morgana/Install) community repository.

---

## The X3M.AI Purple Team Platform

| | Merlino | Morgana |
|---|---|---|
| **Role** | Command & Intelligence | Execution Engine |
| **Type** | Microsoft Excel Add-in | Server + Agent |
| **Platform** | Any OS with Excel | Windows / Linux |
| **License** | Free, no registration | AGPL-3.0 open source |
| **Website** | [merlino.x3m.ai](https://merlino.x3m.ai) | This repo |
| **Integration** | Reads/writes Excel tables | HTTP API on localhost:8888 |

Both are built and maintained by [X3M.AI Ltd](https://x3m.ai) (UK). No telemetry, no accounts, no cloud dependency. Your data stays on your infrastructure.

---

## Merlino + Morgana: The Complete Purple Team Platform

Morgana and Merlino are two sides of the same coin, built to work together from day one.

**[Merlino](https://merlino.x3m.ai)** is a free Microsoft Excel Add-in — the intelligence and command layer. It integrates MITRE ATT&CK, CVE/NVD, Exploit-DB, Darktrace, Microsoft Sentinel and Defender, MISP, and multiple AI providers. Purple teamers use it to build threat profiles, map detection coverage, plan attack scenarios, and generate reports — all inside Excel, with zero data leaving the machine.

**Morgana** is the open-source execution layer. Once a red team scenario is planned in Merlino, Morgana executes it: it dispatches scripts to agents on target machines, collects results, and streams everything back to Merlino in real time. The loop is closed entirely on your own infrastructure.

They communicate over HTTP only. Neither depends on the other's internals.

| | [Merlino](https://merlino.x3m.ai) | Morgana |
|---|---|---|
| **Role** | Command, Intelligence & Reporting | Execution Engine |
| **Type** | Microsoft Excel Add-in | Server + Agent |
| **License** | Free, no registration | AGPL-3.0 open source |
| **Tech** | TypeScript + Office.js + React | Python + Go |
| **Data** | Local (Excel + localStorage) | Local (SQLite on your server) |
| **Integrations** | MITRE, CVE, Sentinel, AI, MISP... | Atomic Red Team (6000+ scripts) |
