# Morgana - Domain Model

> Version: 0.1.0 | March 2026 | X3M.AI Ltd

---

## 1. Entities

### 1.1 Script

The atomic unit of execution. A single command or script that exercises one MITRE ATT&CK technique.

```
Script {
    id              TEXT PRIMARY KEY    -- UUID
    name            TEXT NOT NULL       -- Human-readable name
    description     TEXT                -- What this script does and why
    tcode           TEXT NOT NULL       -- MITRE ATT&CK technique ID (e.g. T1059.001)
    tactic          TEXT                -- MITRE tactic (e.g. execution)
    executor        TEXT NOT NULL       -- powershell | cmd | bash | python | manual
    command         TEXT NOT NULL       -- The command to execute
    cleanup_command TEXT                -- Command to undo the test (optional)
    input_args      TEXT                -- JSON: {arg_name: {type, default, description}}
    download_url    TEXT                -- URL to fetch payload before executing (optional)
    source          TEXT                -- atomic-red-team | custom | merlino
    atomic_id       TEXT                -- Original Atomic test GUID (if from Atomic RT)
    platform        TEXT                -- windows | linux | macos | all
    created_at      DATETIME
    updated_at      DATETIME
}
```

Scripts are the building blocks. They come from two sources:
1. **Atomic Red Team** (auto-imported via YAML loader) — thousands of community-maintained tests
2. **Custom** (created in the UI or via API) — your own organization's test procedures

### 1.2 Chain

An ordered sequence of Scripts that forms an attack scenario (kill chain, playbook).

```
Chain {
    id              TEXT PRIMARY KEY    -- UUID
    name            TEXT NOT NULL       -- e.g. "Initial Access via Phishing + Persistence"
    description     TEXT
    objective       TEXT                -- What this chain is trying to prove/test
    tcode_coverage  TEXT                -- Comma-separated TCodes covered
    author          TEXT
    tags            TEXT                -- JSON array of tags
    created_at      DATETIME
    updated_at      DATETIME
}

ChainStep {
    id              TEXT PRIMARY KEY
    chain_id        TEXT NOT NULL       -- FK -> Chain
    script_id       TEXT NOT NULL       -- FK -> Script
    step_order      INTEGER NOT NULL    -- Execution order (1, 2, 3...)
    input_overrides TEXT                -- JSON: arg overrides for this step
    stop_on_failure BOOLEAN DEFAULT 1   -- Stop chain if this step fails
    delay_seconds   INTEGER DEFAULT 0   -- Wait N seconds before next step
}
```

### 1.3 Test

An execution instance. Records what was run, when, where, by whom, and what the result was.

```
Test {
    id              TEXT PRIMARY KEY    -- UUID
    -- What was run
    chain_id        TEXT                -- FK -> Chain (null if single script run)
    script_id       TEXT                -- FK -> Script (null if chain run)
    tcode           TEXT                -- MITRE TCode of the primary technique
    -- Where / by whom
    agent_id        TEXT                -- FK -> Agent (target machine)
    campaign_id     TEXT                -- FK -> Campaign (optional grouping)
    -- Merlino integration fields
    operation_id    TEXT                -- Merlino operation reference
    adversary_id    TEXT                -- Merlino adversary reference (legacy compat)
    operation_name  TEXT                -- Display name from Merlino
    adversary_name  TEXT                -- Adversary name from Merlino
    assigned        TEXT                -- Who this test is assigned to
    group_name      TEXT                -- Agent group (red, blue, etc.)
    -- Lifecycle
    state           TEXT DEFAULT 'pending'   -- pending|queued|running|finished|failed|cleanup
    -- Results
    exit_code       INTEGER             -- Process exit code (0 = success convention)
    stdout          TEXT                -- Captured standard output
    stderr          TEXT                -- Captured standard error
    duration_ms     INTEGER             -- Execution duration in milliseconds
    -- Timestamps
    created_at      DATETIME
    started_at      DATETIME
    finished_at     DATETIME
}
```

Test state machine:
```
pending -> queued -> running -> finished
                             -> failed
                  -> cleanup  (when cleanup_command is run)
```

### 1.4 Agent

A Morgana agent installed on a target machine.

```
Agent {
    id              TEXT PRIMARY KEY    -- UUID
    paw             TEXT UNIQUE NOT NULL -- Short identifier (e.g. "abc123")
    hostname        TEXT NOT NULL       -- Machine hostname
    ip_address      TEXT                -- Last known IP
    platform        TEXT NOT NULL       -- windows | linux | macos
    architecture    TEXT                -- amd64 | arm64 | x86
    os_version      TEXT                -- e.g. "Windows 11 22H2"
    agent_version   TEXT                -- Morgana agent binary version
    -- Status
    status          TEXT DEFAULT 'offline'  -- online | offline | idle | busy
    last_seen       DATETIME
    -- Configuration
    beacon_interval INTEGER DEFAULT 30  -- Seconds between polls
    work_dir        TEXT                -- Working directory for payloads
    token_hash      TEXT                -- HMAC of auth token (never store plaintext)
    -- Registration
    enrolled_at     DATETIME
    enrolled_by     TEXT                -- Deploy token used (hash only)
    tags            TEXT                -- JSON array (e.g. ["prod", "dc01", "domain-controller"])
}
```

### 1.5 Campaign

A named grouping of Tests for a specific exercise or objective.

```
Campaign {
    id              TEXT PRIMARY KEY    -- UUID
    name            TEXT NOT NULL       -- e.g. "Q1 2026 Purple Team - Ransomware"
    description     TEXT
    objective       TEXT                -- What are we trying to prove?
    status          TEXT DEFAULT 'planning' -- planning|active|completed|archived
    created_at      DATETIME
    started_at      DATETIME
    completed_at    DATETIME
}

CampaignTest {
    campaign_id     TEXT                -- FK -> Campaign
    test_id         TEXT                -- FK -> Test
    PRIMARY KEY (campaign_id, test_id)
}
```

### 1.6 Job (internal)

Internal record created by the server when a Test is queued for execution. Not exposed to Merlino directly.

```
Job {
    id              TEXT PRIMARY KEY    -- UUID
    test_id         TEXT NOT NULL       -- FK -> Test
    agent_id        TEXT NOT NULL       -- FK -> Agent
    script_id       TEXT NOT NULL       -- FK -> Script
    step_order      INTEGER DEFAULT 1   -- Which step in a chain
    -- Payload
    executor        TEXT NOT NULL
    command         TEXT NOT NULL
    cleanup_command TEXT
    input_args      TEXT                -- Resolved JSON (after applying overrides)
    download_url    TEXT
    -- Lifecycle
    status          TEXT DEFAULT 'pending'  -- pending|dispatched|completed|failed
    dispatched_at   DATETIME            -- When agent received it
    completed_at    DATETIME
    -- Signing (security)
    signature       TEXT                -- HMAC-SHA256 of job payload
}
```

---

## 2. Full SQLite Schema

```sql
CREATE TABLE scripts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    tcode           TEXT NOT NULL,
    tactic          TEXT,
    executor        TEXT NOT NULL CHECK (executor IN ('powershell','cmd','bash','python','manual')),
    command         TEXT NOT NULL,
    cleanup_command TEXT,
    input_args      TEXT,
    download_url    TEXT,
    source          TEXT DEFAULT 'custom' CHECK (source IN ('atomic-red-team','custom','merlino')),
    atomic_id       TEXT,
    platform        TEXT DEFAULT 'all',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chains (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    objective       TEXT,
    tcode_coverage  TEXT,
    author          TEXT,
    tags            TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chain_steps (
    id              TEXT PRIMARY KEY,
    chain_id        TEXT NOT NULL REFERENCES chains(id) ON DELETE CASCADE,
    script_id       TEXT NOT NULL REFERENCES scripts(id),
    step_order      INTEGER NOT NULL,
    input_overrides TEXT,
    stop_on_failure BOOLEAN DEFAULT 1,
    delay_seconds   INTEGER DEFAULT 0,
    UNIQUE(chain_id, step_order)
);

CREATE TABLE agents (
    id              TEXT PRIMARY KEY,
    paw             TEXT UNIQUE NOT NULL,
    hostname        TEXT NOT NULL,
    ip_address      TEXT,
    platform        TEXT NOT NULL CHECK (platform IN ('windows','linux','macos')),
    architecture    TEXT,
    os_version      TEXT,
    agent_version   TEXT,
    status          TEXT DEFAULT 'offline' CHECK (status IN ('online','offline','idle','busy')),
    last_seen       DATETIME,
    beacon_interval INTEGER DEFAULT 30,
    work_dir        TEXT,
    token_hash      TEXT,
    enrolled_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    enrolled_by     TEXT,
    tags            TEXT
);

CREATE TABLE campaigns (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    objective       TEXT,
    status          TEXT DEFAULT 'planning',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    completed_at    DATETIME
);

CREATE TABLE tests (
    id              TEXT PRIMARY KEY,
    chain_id        TEXT REFERENCES chains(id),
    script_id       TEXT REFERENCES scripts(id),
    tcode           TEXT,
    agent_id        TEXT REFERENCES agents(id),
    campaign_id     TEXT REFERENCES campaigns(id),
    operation_id    TEXT,
    adversary_id    TEXT,
    operation_name  TEXT,
    adversary_name  TEXT,
    assigned        TEXT,
    group_name      TEXT,
    state           TEXT DEFAULT 'pending',
    exit_code       INTEGER,
    stdout          TEXT,
    stderr          TEXT,
    duration_ms     INTEGER,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    finished_at     DATETIME
);

CREATE TABLE campaign_tests (
    campaign_id     TEXT REFERENCES campaigns(id) ON DELETE CASCADE,
    test_id         TEXT REFERENCES tests(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, test_id)
);

CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    test_id         TEXT NOT NULL REFERENCES tests(id),
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    script_id       TEXT NOT NULL REFERENCES scripts(id),
    step_order      INTEGER DEFAULT 1,
    executor        TEXT NOT NULL,
    command         TEXT NOT NULL,
    cleanup_command TEXT,
    input_args      TEXT,
    download_url    TEXT,
    status          TEXT DEFAULT 'pending',
    dispatched_at   DATETIME,
    completed_at    DATETIME,
    signature       TEXT
);

-- Performance indexes
CREATE INDEX idx_scripts_tcode ON scripts(tcode);
CREATE INDEX idx_tests_state ON tests(state);
CREATE INDEX idx_tests_agent ON tests(agent_id);
CREATE INDEX idx_jobs_agent_status ON jobs(agent_id, status);
CREATE INDEX idx_agents_paw ON agents(paw);
CREATE INDEX idx_agents_status ON agents(status);
```

---

## 3. Terminology Mapping (vs Caldera)

For reference only — Morgana does NOT use Caldera terminology internally.

| Morgana | Caldera (equivalent) | Why Morgana's term is better |
|---|---|---|
| Script | Ability | Concrete — it's code that runs |
| Chain | Adversary | Intuitive — kill chain, attack chain |
| Test | Operation | Precise — an instance of execution |
| Campaign | (none) | Higher-level grouping, new concept |
| Agent | Agent | Kept — universally understood |
| Job | Task | Internal only, not surfaced to users |
