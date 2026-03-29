# Morgana - Agent Protocol

> Version: 0.1.0 | March 2026 | X3M.AI Ltd

---

## 1. Overview

The Morgana Agent is a Go binary that:
1. Installs itself as a native OS service (NT Service on Windows, systemd daemon on Linux)
2. Polls the Morgana Server on a configurable beacon interval
3. Receives job descriptors and executes them via the appropriate executor
4. Reports results back to the server

The agent is designed to be **persistent, resilient, and self-contained** — no runtime dependencies, no Python, no Docker.

---

## 2. Agent Lifecycle

### 2.1 Installation

**Windows (Run as Administrator):**
```powershell
.\morgana-agent.exe install --server https://192.168.1.10:8888 --token DEPLOY_TOKEN_HERE
```

What happens:
1. Binary copies itself to `C:\ProgramData\Morgana\agent\morgana-agent.exe`
2. Creates work directory `C:\ProgramData\Morgana\work\`
3. Creates log directory `C:\ProgramData\Morgana\logs\`
4. Writes config to `C:\ProgramData\Morgana\agent\config.json`
5. Calls `/api/v2/agent/register` → receives `paw` + `agent_token`
6. Stores `paw` and `agent_token` in config (token stored hashed in registry)
7. Creates NT Service: `sc create MorganaAgent binPath= "..." start= auto`
8. Sets service description: "Morgana Red Team Agent - X3M.AI"
9. Sets failure action: restart after 5s (3 retries)
10. Starts the service: `sc start MorganaAgent`

**Linux (Run as root):**
```bash
./morgana-agent install --server https://192.168.1.10:8888 --token DEPLOY_TOKEN_HERE
```

What happens:
1. Binary copies itself to `/usr/local/bin/morgana-agent`
2. Creates work directory `/var/lib/morgana/work/`
3. Creates log directory `/var/log/morgana/`
4. Writes config to `/etc/morgana/config.json`
5. Calls `/api/v2/agent/register`
6. Creates systemd unit at `/etc/systemd/system/morgana-agent.service`
7. `systemctl daemon-reload && systemctl enable morgana-agent && systemctl start morgana-agent`

### 2.2 Enrollment (one-time)

```
Agent                                    Server
  |                                         |
  | POST /api/v2/agent/register             |
  | { deploy_token, hostname, platform,     |
  |   arch, os_version, agent_version }     |
  |---------------------------------------->|
  |                                         | Validates deploy_token (single-use)
  |                                         | Generates paw, agent_token
  |                                         | Creates Agent record in DB
  |                                         | Revokes deploy_token
  | 200 { paw, agent_token,                 |
  |       server_cert_fingerprint,          |
  |       beacon_interval, work_dir }       |
  |<----------------------------------------|
  |                                         |
  | Stores paw + agent_token in config      |
  | Pins server_cert_fingerprint            |
  | Starts beacon loop                      |
```

### 2.3 Beacon Loop

```
while running:
    sleep(beacon_interval)
    
    heartbeat_due = (now - last_heartbeat) > 60s
    if heartbeat_due:
        POST /api/v2/agent/heartbeat { paw, status, ip_address }
        last_heartbeat = now
    
    GET /api/v2/agent/poll?paw=PAW
    
    if response.job != null:
        execute_job(response.job)
    
    beacon_interval = response.beacon_interval  # Server can adjust dynamically
```

### 2.4 Job Execution

```
execute_job(job):
    // 1. Verify signature
    if not verify_hmac(job.id + job.command, job.signature):
        log ERROR "Job signature verification failed"
        return
    
    // 2. Download payload if needed
    if job.download_url != null:
        payload_path = download_to_work_dir(job.download_url, job.test_id)
        command = command.replace("{{payload}}", payload_path)
    
    // 3. Resolve input args
    command = resolve_input_args(command, job.input_args)
    
    // 4. Execute
    log_execution_start(job)
    start_time = now()
    result = execute(job.executor, command, job.timeout_seconds)
    duration_ms = now() - start_time
    
    // 5. Log immutably
    append_to_execution_log({
        timestamp: now(),
        job_id: job.id,
        test_id: job.test_id,
        tcode: job.tcode,
        executor: job.executor,
        command_hash: sha256(command),
        exit_code: result.exit_code,
        duration_ms: duration_ms
    })
    
    // 6. Report result
    POST /api/v2/agent/result {
        paw: PAW,
        job_id: job.id,
        exit_code: result.exit_code,
        stdout: result.stdout[:MAX_OUTPUT],
        stderr: result.stderr[:MAX_OUTPUT],
        duration_ms: duration_ms
    }
```

### 2.5 Uninstallation

**Windows:**
```powershell
.\morgana-agent.exe uninstall
```
Stops and removes NT Service. Optionally removes `C:\ProgramData\Morgana\` (flag `--purge`).

**Linux:**
```bash
./morgana-agent uninstall
```
Stops and disables systemd unit. Optionally removes `/etc/morgana/`, `/var/lib/morgana/`, `/var/log/morgana/`.

---

## 3. Executors

### 3.1 PowerShell (Windows + Linux with PS Core)

```
Executor: powershell
Invocation: powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "<command>"
Linux:      pwsh -NoProfile -NonInteractive -Command "<command>"
```

Flags used:
- `-NoProfile` — Do not load user profile (consistent execution)
- `-NonInteractive` — No prompts (unattended execution)
- `-ExecutionPolicy Bypass` — Do not let policy block test scripts
- `-Command` — Execute the provided command string

### 3.2 cmd.exe (Windows only)

```
Executor: cmd
Invocation: cmd.exe /C "<command>"
```

### 3.3 bash / sh (Linux / macOS)

```
Executor: bash
Invocation: /bin/bash -c "<command>"
Fallback:   /bin/sh -c "<command>"
```

### 3.4 Python

```
Executor: python
Windows: python.exe -c "<command>" (or run script file)
Linux:   python3 -c "<command>"
```

### 3.5 Manual

```
Executor: manual
Action: Skip execution, mark test as "manual" in results
Use case: Tests that require physical/human interaction
```

---

## 4. File System Layout

### Windows
```
C:\ProgramData\Morgana\
├── agent\
│   ├── morgana-agent.exe
│   └── config.json
├── work\
│   ├── <test_id>\           One directory per test (isolation)
│   │   ├── payload.ps1      Downloaded payloads
│   │   └── output.txt       Captured output
│   └── ...
└── logs\
    ├── agent.log            Agent operational log (debug/info)
    └── execution.log        Immutable execution audit log
```

### Linux
```
/etc/morgana/
    config.json
/usr/local/bin/
    morgana-agent
/var/lib/morgana/
    work/
        <test_id>/
/var/log/morgana/
    agent.log
    execution.log
```

---

## 5. Configuration File (config.json)

```json
{
  "server_url": "https://192.168.1.10:8888",
  "server_cert_fingerprint": "sha256:<hex>",
  "paw": "abc123",
  "beacon_interval": 30,
  "max_execution_timeout": 300,
  "max_output_bytes": 102400,
  "work_dir": "C:\\ProgramData\\Morgana\\work",
  "log_level": "info"
}
```

The `agent_token` is NOT stored in `config.json`. It is stored in:
- **Windows:** Windows Credential Manager (via `wincred`)
- **Linux:** `/etc/morgana/.agent_token` with mode `0600`, owned by `root`

---

## 6. NT Service Details (Windows)

Service name: `MorganaAgent`  
Display name: `Morgana Red Team Agent`  
Description: `Morgana Red Team Agent - X3M.AI Purple Team Platform`  
Start type: `Automatic`  
Account: `LocalSystem` (can be changed to a service account for least-privilege deployments)  

Failure actions:
- First failure: Restart after 5 seconds
- Second failure: Restart after 10 seconds
- Subsequent failures: Restart after 30 seconds

Registry key: `HKLM\SYSTEM\CurrentControlSet\Services\MorganaAgent`

---

## 7. systemd Unit (Linux)

```ini
[Unit]
Description=Morgana Red Team Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/morgana-agent run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=morgana-agent
User=root

[Install]
WantedBy=multi-user.target
```

---

## 8. Agent Commands (CLI)

```
morgana-agent install   --server <url> --token <deploy_token> [--interval 30]
morgana-agent uninstall [--purge]
morgana-agent run                          # Run in foreground (debug mode)
morgana-agent status                       # Show service status + last job
morgana-agent version                      # Print version
```
