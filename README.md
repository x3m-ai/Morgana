# Morgana

<p align="center">
  <img src="ui/assets/morgana-logo.png" alt="Morgana" width="320" />
</p>

> **Version:** 0.1.0 (Alpha) | **March 2026**
> **Publisher:** X3M.AI Ltd (UK) | **Author:** Nino Crudele
> **Companion to:** [Merlino Excel Add-in](https://merlino.x3m.ai)
> **Repo:** `x3m-ai/Morgana` (private)

---

## What is Morgana?

Morgana is a **Windows-first Purple Team execution platform** built as the native companion to the Merlino Excel Add-in.

Where Merlino is the **command and intelligence center** (threat mapping, ATT&CK correlation, reporting), Morgana is the **execution engine**: it deploys agents on target machines, runs red team scripts mapped to MITRE ATT&CK techniques, and reports results back to Merlino in real time.

Morgana is **not a fork of Caldera**. It is a purpose-built platform with:
- A domain model designed for operational red teamers, not researchers
- Agents that install as native OS services (NT Service on Windows, systemd daemon on Linux)
- Scripts drawn from [Atomic Red Team](https://github.com/redcanaryco/atomic-red-team) (6000+ MITRE-mapped tests)
- A clean HTTP API that Merlino consumes directly
- A dark-theme web UI for standalone use

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

## Quick Start

### 1. Start the server
```bash
cd server
pip install -r requirements.txt
python main.py
```
Server starts on `https://localhost:8888`.

### 2. Install an agent on a Windows target
```powershell
# Run on the target machine (as Administrator)
.\scripts\install-agent-windows.ps1 -ServerUrl "https://192.168.1.10:8888" -Token "YOUR_DEPLOY_TOKEN"
```

### 3. Configure Merlino
In the Merlino Settings taskpane, set **Morgana URL** to `https://localhost:8888` (or the server IP).

### 4. Synchronize
In Merlino's **Tests & Operations** taskpane, click **Synchronize Morgana**. Morgana receives the Tests table, queues jobs for agents, and streams results back.

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
| `/api/v2/agents` | GET | Agent list (Caldera-compatible) |

---

## License

MIT License - see [LICENSE](LICENSE)

---

## Relation to Merlino

Morgana is the execution backend. Merlino is the intelligence and command center. They communicate over HTTP only. Neither depends on the other's internal implementation.

| Merlino | Morgana |
|---|---|
| Excel Add-in (TypeScript) | Standalone server + agent (Python + Go) |
| Threat intelligence, mapping, reporting | Script execution, agent management |
| CTI / Blue Team / Purple Team analysis | Red Team execution engine |
| Cloudflare Pages (hosted) | Local / on-premise (your infrastructure) |
