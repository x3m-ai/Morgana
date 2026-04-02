# Morgana - Chains API

> Version: 0.2.0 | April 2026 | X3M.AI Ltd  
> This document covers the Chains CRUD, visual flow builder, execution engine, and post-mortem log API.

---

## Overview

A **Chain** is a visual kill-chain: an ordered graph of **Script nodes** and **If/Then/Else branch nodes**.  
When executed against an Agent, Morgana runs each node sequentially in a background thread, dispatching real `Test + Job` records and capturing every step's output into an **execution log**.

---

## Authentication

All endpoints require the `KEY` header (same as every other Morgana API).

```
KEY: <api_key>
```

---

## Base URL

```
https://<morgana-server>:8888/api/v2/chains
```

---

## Chain Object

```json
{
  "id":          "uuid",
  "name":        "Credential Harvesting",
  "description": "Mimikatz + LSASS dump chain",
  "objective":   "",
  "author":      "",
  "tags":        "",
  "flow": {
    "nodes": [ ... ]
  },
  "created_at":  "2026-04-02T10:00:00",
  "updated_at":  "2026-04-02T12:00:00"
}
```

### Flow Node Types

#### Script node
```json
{
  "id":          "n1a2b3",
  "type":        "script",
  "script_id":   "uuid-of-script",
  "script_name": "Mimikatz Credential Dump",
  "tcode":       "T1003.001",
  "tactic":      "credential-access"
}
```

#### If/Then/Else node
```json
{
  "id":         "nXYZ",
  "type":       "if_else",
  "contains":   "error",
  "if_nodes":   [ ... ],
  "else_nodes": [ ... ]
}
```

`contains` is matched case-insensitively against the `stdout` of the **previous step**.  
If it matches, `if_nodes` executes; otherwise `else_nodes`.  
Both sub-arrays follow the same node format and can themselves contain nested `if_else` nodes.

---

## Endpoints

### GET /api/v2/chains

List all chains, ordered by `updated_at` descending.

**Response:** array of Chain objects (see above).

---

### POST /api/v2/chains

Create a new chain.

**Request body:**
```json
{
  "name":        "My Chain",
  "description": "Optional description",
  "flow":        { "nodes": [] }
}
```

**Response:** the created Chain object.

---

### GET /api/v2/chains/{chain_id}

Get a single chain with its full `flow` JSON.

**Response:** Chain object.

---

### PUT /api/v2/chains/{chain_id}

Update name, description, and/or flow of an existing chain.

**Request body** (all fields optional):
```json
{
  "name":        "Updated Name",
  "description": "Updated description",
  "flow":        { "nodes": [ ... ] }
}
```

**Response:** updated Chain object.

---

### DELETE /api/v2/chains/{chain_id}

Delete a chain. Existing `ChainExecution` records are preserved with `chain_id = null`.

**Response:**
```json
{ "deleted": "uuid" }
```

---

### POST /api/v2/chains/import

Import a chain from a JSON export (name gets ` (imported)` appended).

**Request body:** same shape as the Chain export (output of GET /api/v2/chains/{id}).

**Response:** the newly created Chain object.

---

### POST /api/v2/chains/{chain_id}/execute

Start executing the chain on the given agent. Runs in a background thread.  
Returns immediately with the execution ID.

**Request body:**
```json
{ "agent_paw": "abc123" }
```

**Response:**
```json
{
  "execution_id": "uuid",
  "state":        "running"
}
```

**Error cases:**
- `404` — chain not found
- `404` — agent with given `paw` not found
- `400` — chain has no nodes

---

## Execution Endpoints

### GET /api/v2/chains/executions

List all executions, ordered by `started_at` descending (max 200).  
Optional query param: `?chain_id=<uuid>` to filter by chain.

**Response:** array of Execution summary objects:
```json
[
  {
    "id":             "uuid",
    "chain_id":       "uuid or null",
    "chain_name":     "Credential Harvesting",
    "agent_paw":      "abc123",
    "agent_hostname": "WORKSTATION-01",
    "state":          "completed",
    "started_at":     "2026-04-02T10:00:00",
    "finished_at":    "2026-04-02T10:02:14",
    "error":          ""
  }
]
```

`state` values: `running` | `completed` | `failed`

---

### GET /api/v2/chains/executions/{exec_id}

Get a single execution with full step logs and flow snapshot.

**Response:** same as list item but includes `steps` and `flow_snapshot` (see Log endpoint below).

---

### GET /api/v2/chains/executions/{exec_id}/log

**LogChainExecution** — full post-mortem execution log intended for debugging and reporting.

**Response:**
```json
{
  "execution_id":   "uuid",
  "chain_id":       "uuid or null",
  "chain_name":     "Credential Harvesting",
  "agent_paw":      "abc123",
  "agent_hostname": "WORKSTATION-01",
  "state":          "completed",
  "started_at":     "2026-04-02T10:00:00",
  "finished_at":    "2026-04-02T10:02:14",
  "error":          "",
  "flow_snapshot":  { "nodes": [ ... ] },
  "steps": [
    {
      "node_id":   "n1a2b3",
      "type":      "script",
      "tcode":     "T1003.001",
      "name":      "Mimikatz Credential Dump",
      "state":     "finished",
      "exit_code": 0,
      "stdout":    "...",
      "stderr":    "",
      "test_id":   "uuid",
      "job_id":    "uuid"
    },
    {
      "node_id":          "nXYZ",
      "type":             "if_else",
      "contains":         "error",
      "matched":          false,
      "branch_taken":     "else",
      "last_stdout_snippet": "first 200 chars of previous step stdout"
    },
    {
      "node_id":   "nABC",
      "type":      "script",
      "tcode":     "T1055",
      "name":      "Process Injection",
      "state":     "failed",
      "exit_code": 1,
      "stdout":    "",
      "stderr":    "Access denied",
      "test_id":   "uuid",
      "job_id":    "uuid"
    }
  ]
}
```

**Step `state` values (script nodes):** `finished` (exit 0) | `failed` (exit != 0 or timeout)

`flow_snapshot` is the chain's `flow_json` at the moment execution started, so logs are accurate even if the chain is later edited.

---

## Execution Engine Internals

The background thread (`_run_chain`) works as follows:

1. Walks `nodes` top to bottom via `_walk_nodes()`.
2. For each **script node**: creates a `Test` + `Job` record, enqueues the job on the agent via `job_queue.enqueue(paw, job_id)`, then polls `job.status == "completed"` every 3 seconds (max 310 seconds).
3. For each **if/else node**: checks `contains` (case-insensitive) in the `stdout` of the last script step. Recurses into `if_nodes` or `else_nodes` accordingly.
4. After every node, calls `_update_execution_logs()` to persist intermediate results (visible to polling clients mid-run).
5. On completion sets `state = "completed"` or `"failed"` and writes `finished_at`.

---

## Merlino Integration Note

Chains are **not part of the Merlino backward-compatibility contract**.  
Merlino does not call chain endpoints; chains are a Morgana-native feature operated from the Morgana web UI or third-party tooling.
