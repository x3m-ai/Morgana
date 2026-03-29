# Morgana - Architecture

> Version: 0.1.0 | March 2026 | X3M.AI Ltd

---

## 1. Overview

Morgana is a three-tier system:

```
+---------------------------+
|   MERLINO (Excel Add-in)  |   Command & Intelligence Layer
+---------------------------+
             |
             | HTTPS  /api/v2/merlino/*
             v
+---------------------------+
|   MORGANA SERVER          |   Orchestration Layer
|   FastAPI + SQLite        |   localhost:8888 (or remote)
+---------------------------+
             |
             | HTTPS  /api/v2/agent/poll + /result
             v
+---------------------------+
|   MORGANA AGENT           |   Execution Layer
|   Go binary (NT Service / |
|   systemd daemon)         |
+---------------------------+
             |
             | subprocess
             v
+---------------------------+
|   EXECUTOR                |   Runtime Layer
|   PowerShell / cmd / bash |
+---------------------------+
             |
             v
+---------------------------+
|   SCRIPTS                 |   Payload Layer
|   Atomic Red Team YAML    |
|   + custom scripts        |
+---------------------------+
```

---

## 2. Component Details

### 2.1 Morgana Server

**Language:** Python 3.12  
**Framework:** FastAPI  
**Database:** SQLite (SQLAlchemy ORM)  
**Port:** 8888 (HTTPS, self-signed cert for local use)

Responsibilities:
- Expose the `/api/v2/merlino/*` API surface that Merlino calls
- Manage the lifecycle of Scripts, Chains, Tests, Campaigns, Agents
- Queue jobs for agents when a Test is submitted
- Receive results from agents and update Test state
- Serve the web UI on `/ui`
- Load and index Atomic Red Team YAML library into SQLite

Process:
```
main.py
  -> FastAPI app
     -> routers/merlino/*     (Merlino integration API)
     -> routers/agent/*       (Agent communication API)
     -> routers/ui/*          (Web UI static files)
  -> core/
     -> atomic_loader.py      (Atomic Red Team YAML parser)
     -> job_queue.py          (In-memory queue: pending jobs per agent)
     -> operations.py         (Test lifecycle state machine)
  -> models/
     -> script, chain, test, campaign, agent (SQLAlchemy models)
  -> db/
     -> morgana.db (SQLite file)
```

### 2.2 Morgana Agent

**Language:** Go 1.22  
**Distribution:** Single self-contained binary (~5 MB)  
**Windows:** Installed as Windows NT Service (`MorganaAgent`)  
**Linux:** Installed as systemd unit (`morgana-agent.service`)

Responsibilities:
- Register itself with the server on first start (one-time enrollment)
- Poll the server on a configurable beacon interval (default: 30s)
- Receive job descriptors from the server
- Execute scripts via the appropriate runtime (PowerShell, cmd, bash, python)
- Download payloads to the work directory when a download URL is provided
- Report results (stdout, stderr, exit_code, duration) back to the server
- Write an immutable local execution log

Internal modules:
```
cmd/agent/main.go          Entry point - flags: install/uninstall/run/debug
internal/
  beacon/beacon.go         Polling loop - GET /api/v2/agent/poll
  executor/
    executor.go            Interface + dispatcher
    powershell.go          PowerShell executor (Windows + PSCore Linux)
    cmd.go                 cmd.exe executor (Windows only)
    bash.go                bash/sh executor (Linux/Mac)
  service/
    service.go             Interface
    windows.go             NT Service implementation
    linux.go               systemd daemon implementation
  config/config.go         Load config from file + env vars
  logger/logger.go         Structured JSON logger
```

### 2.3 Web UI

**Technology:** Vanilla HTML5 / JavaScript / CSS3  
**Theme:** Dark, matching Merlino color scheme  
**Served by:** FastAPI static files from `/ui`

Pages:
- `/ui` - Dashboard: agents online, active tests, recent results
- `/ui/scripts` - Script library browser (Atomic + custom)
- `/ui/chains` - Chain builder (drag-and-drop script sequencer)
- `/ui/tests` - Test history and live execution view
- `/ui/campaigns` - Campaign management
- `/ui/agents` - Agent registry, health, last-seen

---

## 3. Security Model

### 3.1 Trust Boundary

Morgana is designed for **authorized penetration testing and purple team exercises** only. All the following controls enforce this:

**Enrollment token:**
- A deploy token is generated per agent deployment
- Token is single-use: after first registration, it is revoked
- Agent and server mutually verify via the token + agent PAW (unique ID)

**Agent-to-server authentication:**
- Every request from agent includes `Authorization: Bearer <agent_token>`
- Server validates token before returning any job
- Token stored in agent config file (not in registry, not in environment)

**Job signing:**
- Server signs every job payload with HMAC-SHA256
- Agent verifies signature before executing
- Prevents MITM job injection

**Execution log:**
- Agent writes every executed command to a local append-only log
- `%ProgramData%\Morgana\logs\execution.log` (Windows)
- `/var/log/morgana/execution.log` (Linux)
- Log includes: timestamp, job_id, tcode, command hash, exit_code

**HTTPS:**
- TLS 1.3 minimum
- Self-signed cert for localhost/LAN use
- Production deployments should use proper PKI

### 3.2 Scope Limitation

The agent is configured at install time with:
- The server URL it will ONLY communicate with
- The server's TLS certificate fingerprint (pinning)
- A maximum execution timeout (default: 300s)

The agent refuses to:
- Connect to any URL other than the configured server
- Execute jobs without a valid server signature
- Run commands that exceed the configured timeout

---

## 4. Data Flow - Full Cycle

### Test execution cycle (Merlino -> Morgana -> Agent -> Merlino):

```
1. [MERLINO] User marks rows Pick=TRUE in Tests table
2. [MERLINO] User clicks "Synchronize Morgana"
3. [MERLINO] POST /api/v2/merlino/synchronize
             Body: [{tcode, assigned_agent, chain, state, ...}, ...]

4. [SERVER]  Receives sync payload
             Creates/updates Test records in SQLite
             For each Test with state="running":
               -> Creates a Job record (pending)
               -> Adds Job to in-memory queue for target agent

5. [AGENT]   Beacon poll: GET /api/v2/agent/poll?paw=AGENT_PAW
6. [SERVER]  Returns pending Job (if any)
             Job includes: {job_id, tcode, executor, command,
                            cleanup_command, input_args, download_url?}

7. [AGENT]   If download_url: fetches payload to work dir
             Executes command via appropriate executor
             Captures stdout, stderr, exit_code, duration_ms

8. [AGENT]   POST /api/v2/agent/result
             Body: {paw, job_id, exit_code, stdout, stderr, duration_ms}

9. [SERVER]  Updates Test state in SQLite
             Sets: state="finished", exit_code, output, finished_at

10. [MERLINO] GET /api/v2/merlino/realtime
              Receives updated Test states
              Updates Tests table in Excel
              Smart View refreshes technique coverage colors
```

---

## 5. Beacon Protocol

The agent uses a simple long-poll mechanism:

```
Agent                         Server
  |                              |
  | GET /api/v2/agent/poll       |
  | ?paw=abc123&idle=true        |
  |----------------------------->|
  |                              | (waits up to 30s for job)
  |     200 { job: null }        |
  |<-----------------------------|  (no job: agent waits beacon_interval)
  |                              |
  | GET /api/v2/agent/poll       |
  |----------------------------->|
  |     200 { job: {...} }       |  (job available: agent executes)
  |<-----------------------------|
  |                              |
  | [executes job]               |
  |                              |
  | POST /api/v2/agent/result    |
  |----------------------------->|
  |     200 { ack: true }        |
  |<-----------------------------|
```

Beacon interval is configurable per agent (default 30s, min 5s).
A lower interval provides faster feedback but simulates more aggressive C2 traffic
which is itself a useful test for EDR/NDR detection rules.

---

## 6. Storage Schema

See [DOMAIN_MODEL.md](DOMAIN_MODEL.md) for the full SQLite schema.

---

## 7. Deployment Topologies

### Topology A: All-in-one (Purple Team lab)
```
[Windows laptop]
  Merlino (Excel Add-in)
  Morgana Server (localhost:8888)
  Morgana Agent (testing same machine)
```

### Topology B: Separate server (team exercise)
```
[Windows operator machine]           [Windows target]
  Merlino (Excel Add-in)               Morgana Agent (NT Service)
  Morgana Server (:8888)  <-HTTPS->    polls server every 30s
```

### Topology C: Multi-target (enterprise purple team)
```
[Operator: Merlino + Morgana Server]
        |
        +---> [Windows targets x N: Morgana Agent]
        +---> [Linux targets x N:   Morgana Agent]
        +---> [macOS targets x N:   Morgana Agent]
```

---

## 8. Technology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Server language | Python + FastAPI | Rapid development, rich YAML/JSON parsing, familiar |
| Agent language | Go 1.22 | Single binary, no runtime, cross-platform, ~5 MB |
| Database | SQLite | Zero setup, file-based, portable, no server process |
| Agent install model | OS Service / daemon | Survives reboot, auto-restart, no user session needed |
| Script library | Atomic Red Team | 6000+ MITRE-mapped tests, MIT license, industry standard |
| Transport | HTTPS (TLS 1.3) | Encrypts C2 comms, realistic simulation |
| UI | Vanilla HTML/JS | No build step, same tech as Merlino taskpane, fast |
