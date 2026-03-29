# Morgana - API Contract (Merlino Integration)

> Version: 0.1.0 | March 2026 | X3M.AI Ltd
> This document is the source of truth for the Morgana API surface consumed by Merlino.

---

## Base URL

```
https://<morgana-server>:8888
```

Default: `https://localhost:8888`

All API endpoints are under `/api/v2/`.  
Authentication uses the `KEY` header (matches Caldera convention for Merlino compatibility).

---

## Merlino Integration Endpoints

### POST /api/v2/merlino/synchronize

Receives the Tests table from Merlino. Creates/updates Tests in Morgana and queues jobs for agents.

**Request headers:**
```
KEY: <api_key>
Content-Type: application/json
```

**Request body:** Array of test descriptors from Merlino Tests table.
```json
[
  {
    "operation_id": "op-uuid-or-empty",
    "adversary_id": "adv-uuid-or-empty",
    "operation": "Ransomware Chain - Phase 1",
    "adversary": "APT29 Simulation",
    "description": "Tests initial access techniques",
    "tcodes": "T1059.001,T1082,T1003.001",
    "assigned": "Agent-Win01",
    "state": "running",
    "agents": 1,
    "group": "red"
  }
]
```

**Response 200:**
```json
{
  "synced": 5,
  "created": 3,
  "updated": 2,
  "agents_found": 2,
  "jobs_queued": 3,
  "operations": [
    {
      "operation_id": "test-uuid",
      "adversary_id": "chain-uuid",
      "operation": "Ransomware Chain - Phase 1",
      "adversary": "APT29 Simulation",
      "state": "running",
      "tcodes": "T1059.001,T1082,T1003.001",
      "agents": 1,
      "group": "red"
    }
  ]
}
```

---

### GET /api/v2/merlino/realtime

Returns real-time operational metrics for the Merlino Operations Intelligence Dashboard.

**Query parameters:**
- `window` (optional): `5m | 15m | 1h | 6h | 24h` (default: `15m`)
- `include_timeline` (optional): `true | false` (default: `true`)
- `timeline_limit` (optional): integer (default: `250`)

**Response 200:**
```json
{
  "operations": [
    {
      "id": "test-uuid",
      "name": "Ransomware Chain - Phase 1",
      "adversary": "APT29 Simulation",
      "state": "running",
      "started": "2026-03-29T10:00:00Z",
      "finish_time": null,
      "total_abilities": 3,
      "success_count": 1,
      "error_count": 0,
      "running_count": 1,
      "agents_count": 1,
      "techniques_count": 3,
      "tcodes": ["T1059.001", "T1082", "T1003.001"],
      "abilities": [
        {
          "name": "PowerShell Download Cradle",
          "tactic": "execution",
          "technique": "T1059.001",
          "status": "success"
        }
      ]
    }
  ],
  "agents": [
    {
      "paw": "abc123",
      "host": "WIN-TARGET01",
      "platform": "windows",
      "last_seen": "2026-03-29T10:05:30Z"
    }
  ],
  "globalStats": {
    "totalOps": 1,
    "totalAbilities": 3,
    "totalSuccess": 1,
    "totalErrors": 0,
    "successRate": 33.3,
    "runningOps": 1,
    "completedOps": 0,
    "failedOps": 0,
    "totalAgents": 2
  },
  "timeline": [
    {
      "ts": "2026-03-29T10:00:00Z",
      "type": "operation_started",
      "operation_id": "test-uuid",
      "operation_name": "Ransomware Chain - Phase 1"
    }
  ],
  "generatedAt": "2026-03-29T10:06:00Z",
  "window": "15m"
}
```

---

### POST /api/v2/merlino/ops-graph

Returns the force graph dataset for the Operations Intelligence Command Map.

**Request body:**
```json
{
  "window_minutes": 60,
  "include_problems": true
}
```

**Response 200:**
```json
{
  "nodes": [
    {"id": "op-uuid", "type": "operation", "label": "Ransomware P1", "state": "running"},
    {"id": "agent-uuid", "type": "agent", "label": "WIN-TARGET01", "platform": "windows"},
    {"id": "prob-uuid", "type": "problem", "label": "T1003.001 failed", "severity": "high"}
  ],
  "edges": [
    {"source": "agent-uuid", "target": "op-uuid", "type": "agent_in_operation"},
    {"source": "op-uuid", "target": "prob-uuid", "type": "operation_has_problem"}
  ],
  "generatedAt": "2026-03-29T10:06:00Z"
}
```

---

### GET /api/v2/merlino/ops-graph/problem-details

**Query parameters:** `problem_id`, `window_minutes` (default: 60), `limit` (default: 20)

**Response 200:**
```json
{
  "problem_id": "prob-uuid",
  "label": "T1003.001 failed",
  "tcode": "T1003.001",
  "total_failures": 3,
  "recent_events": [
    {
      "ts": "2026-03-29T10:02:00Z",
      "agent_paw": "abc123",
      "agent_host": "WIN-TARGET01",
      "exit_code": 1,
      "stderr_preview": "Access denied"
    }
  ]
}
```

---

### GET /api/v2/merlino/ops-graph/operation-details

**Query parameters:** `operation_id`, `window_minutes`, `limit`

**Response 200:**
```json
{
  "operation_id": "test-uuid",
  "name": "Ransomware Chain - Phase 1",
  "state": "running",
  "tcodes": ["T1059.001", "T1082", "T1003.001"],
  "steps": [
    {"step": 1, "script": "PowerShell Download Cradle", "tcode": "T1059.001", "status": "success", "exit_code": 0},
    {"step": 2, "script": "System Info Enum", "tcode": "T1082", "status": "running", "exit_code": null},
    {"step": 3, "script": "LSASS Dump", "tcode": "T1003.001", "status": "pending", "exit_code": null}
  ],
  "agents": [{"paw": "abc123", "host": "WIN-TARGET01"}]
}
```

---

### GET /api/v2/merlino/ops-graph/agent-details

**Query parameters:** `agent_paw`, `window_minutes`, `limit`

**Response 200:**
```json
{
  "paw": "abc123",
  "host": "WIN-TARGET01",
  "platform": "windows",
  "status": "busy",
  "last_seen": "2026-03-29T10:05:30Z",
  "active_tests": 1,
  "completed_tests": 4,
  "failed_tests": 1,
  "recent_activity": [
    {"ts": "2026-03-29T10:02:00Z", "tcode": "T1059.001", "status": "success"}
  ]
}
```

---

### GET /api/v2/agents

Returns the list of registered agents. Maintains Caldera API compatibility for Merlino's agent check.

**Response 200:** Array of agent objects.
```json
[
  {
    "paw": "abc123",
    "host": "WIN-TARGET01",
    "platform": "windows",
    "last_seen": "2026-03-29T10:05:30Z",
    "status": "online"
  }
]
```

---

## Agent Communication Endpoints

### GET /api/v2/agent/poll

Called by agents on each beacon interval.

**Headers:** `Authorization: Bearer <agent_token>`
**Query parameters:** `paw=<agent_paw>`

**Response 200 (no job):**
```json
{"job": null, "beacon_interval": 30}
```

**Response 200 (job available):**
```json
{
  "job": {
    "id": "job-uuid",
    "test_id": "test-uuid",
    "executor": "powershell",
    "command": "Invoke-AtomicTest T1059.001 -TestNumbers 1",
    "cleanup_command": "Invoke-AtomicTest T1059.001 -TestNumbers 1 -Cleanup",
    "input_args": {"PathToAtomicsFolder": "C:\\AtomicRedTeam\\atomics"},
    "download_url": null,
    "timeout_seconds": 300,
    "signature": "<hmac-sha256>"
  },
  "beacon_interval": 30
}
```

---

### POST /api/v2/agent/register

One-time agent enrollment.

**Request body:**
```json
{
  "deploy_token": "<single-use-token>",
  "hostname": "WIN-TARGET01",
  "platform": "windows",
  "architecture": "amd64",
  "os_version": "Windows 11 22H2",
  "agent_version": "0.1.0"
}
```

**Response 200:**
```json
{
  "paw": "abc123",
  "agent_token": "<long-lived-jwt>",
  "server_cert_fingerprint": "<sha256>",
  "beacon_interval": 30,
  "work_dir": "C:\\ProgramData\\Morgana\\work"
}
```

---

### POST /api/v2/agent/result

Agent reports job execution result.

**Headers:** `Authorization: Bearer <agent_token>`

**Request body:**
```json
{
  "paw": "abc123",
  "job_id": "job-uuid",
  "exit_code": 0,
  "stdout": "Atomic Test Completed",
  "stderr": "",
  "duration_ms": 1234
}
```

**Response 200:**
```json
{"ack": true}
```

---

### POST /api/v2/agent/heartbeat

Agent reports it is alive (called every 60s regardless of jobs).

**Request body:**
```json
{
  "paw": "abc123",
  "status": "idle",
  "ip_address": "192.168.1.50"
}
```

**Response 200:**
```json
{"ack": true, "beacon_interval": 30}
```
