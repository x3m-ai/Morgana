# Merlino + Morgana Integration Guide

> This document explains how to connect the Merlino Excel Add-in to a Morgana server, replacing the previous Caldera dependency.

---

## Overview

Merlino communicates with Morgana via the same HTTP API that previously targeted Caldera. The URL and API key are the only things that change — zero code changes in Merlino are required.

```
Merlino (Excel Add-in)
     |
     | HTTP POST /api/v2/merlino/synchronize
     | HTTP GET  /api/v2/merlino/realtime
     | HTTP POST /api/v2/merlino/ops-graph
     | HTTP GET  /api/v2/agents              (Caldera-compat)
     v
Morgana Server (local, port 8888)
     |
     | Job dispatch via beacon poll
     v
Morgana Agent (NT Service / systemd)
     |
     | Execute scripts (PowerShell / bash / cmd)
     v
Target system (or same machine for self-test)
```

---

## Step 1 - Start Morgana Server

```powershell
# Development
cd Morgana\server
python main.py

# Or run the built EXE
.\morgana-server.exe
```

Server starts on `https://localhost:8888` (self-signed cert).

---

## Step 2 - Configure Merlino Settings

In Excel, open the **Merlino Settings** taskpane. Under the **Caldera / Morgana** section:

| Setting | Old Value | New Value |
|---------|-----------|-----------|
| Server URL | `https://caldera-host:8888` | `https://morgana-host:8888` |
| API Key | Caldera REST key | `MORGANA_ADMIN_KEY` (or your custom value) |

Save settings. Merlino will immediately use Morgana for all subsequent sync operations.

---

## Step 3 - Deploy Agents

From the Merlino **Agents** taskpane (or Morgana Web UI at `/ui/`):

- Click **Deploy Agent** to get the install command.
- Run the install command on each target machine (Administrator / root required).
- Agents appear in the Merlino Agents table within one beacon interval (default: 30s).

---

## Step 4 - Run Tests

1. In Merlino, go to the **Tests & Operations** taskpane.
2. Mark rows in the Tests table with `Pick = TRUE`.
3. Click **Synchronize** — Merlino sends the selected tests to Morgana.
4. Morgana dispatches jobs to the appropriate agents (matched by hostname).
5. Results flow back in real-time via the **Realtime** endpoint.

---

## API Compatibility Map

| Merlino call | Caldera endpoint | Morgana equivalent |
|---|---|---|
| Check agents live | `GET /api/v2/agents` | `GET /api/v2/agents` (Caldera-compat) |
| Push tests | `POST /api/v2/merlino/synchronize` | `POST /api/v2/merlino/synchronize` |
| Real-time metrics | `GET /api/v2/merlino/realtime` | `GET /api/v2/merlino/realtime` |
| Ops graph | `POST /api/v2/merlino/ops-graph` | `POST /api/v2/merlino/ops-graph` |
| Problem details | `GET /api/v2/merlino/ops-graph/problem-details` | same |
| Operation details | `GET /api/v2/merlino/ops-graph/operation-details` | same |
| Agent details | `GET /api/v2/merlino/ops-graph/agent-details` | same |

All endpoints accept the same JSON shapes. Merlino requires no code changes.

---

## Reconnecting to Caldera (rollback)

To revert, simply change the Server URL back to your Caldera instance. Morgana and Caldera can coexist — they are independent services.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ECONNREFUSED` | Morgana not running | Start `python main.py` or the EXE |
| `401 Unauthorized` | Wrong API key | Check `MORGANA_API_KEY` env var matches Merlino settings |
| No agents shown | Agent not installed | Run `install-agent-windows.ps1` on target |
| No tests dispatched | Agent offline / hostname mismatch | Check agent `last_seen` in Morgana UI; ensure hostname in Merlino Tests table matches agent hostname |
| TLS cert error | Self-signed cert not trusted | Merlino already sets `rejectUnauthorized: false` for local servers — check proxy settings |

---

## Data Flow Detail

```
1. Merlino reads Tests sheet rows where Pick=TRUE
2. POST /api/v2/merlino/synchronize { payload: [{operation_name, tcode, agent_hostname, state}] }
3. Morgana creates/updates Test records; enqueues Jobs for state=running tests
4. Agent beacons: GET /api/v2/agent/poll?paw=PAW
5. Morgana returns job payload (command, executor, signed with HMAC)
6. Agent verifies HMAC, executes script, writes immutable audit log
7. Agent reports: POST /api/v2/agent/result { paw, job_id, exit_code, stdout, stderr, duration_ms }
8. Morgana updates Test state=finished/failed
9. Merlino polls: GET /api/v2/merlino/realtime -> receives updated operations
10. Merlino updates Tests table (State, ExitCode, Duration columns)
```
