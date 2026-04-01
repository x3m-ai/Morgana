/**
 * Morgana UI - Main application script
 * Dark-theme dashboard for the Morgana Red Team Platform
 */

"use strict";

const API_BASE = window.location.origin;
const API_KEY = localStorage.getItem("morgana_api_key") || "MORGANA_ADMIN_KEY";
const REFRESH_INTERVAL = 15000; // 15 seconds

let allScripts = [];
let refreshTimer = null;

// ─── Navigation ──────────────────────────────────────────────────────────────

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    const page = item.dataset.page;
    navigateTo(page);
  });
});

function navigateTo(page) {
  document.querySelectorAll(".nav-item").forEach((i) => i.classList.remove("active"));
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));

  const navItem = document.querySelector(`[data-page="${page}"]`);
  const pageEl = document.getElementById(`page-${page}`);
  if (navItem) navItem.classList.add("active");
  if (pageEl) pageEl.classList.add("active");

  // Load page data
  switch (page) {
    case "dashboard": refreshDashboard(); break;
    case "agents":    loadAgents(); break;
    case "scripts":   loadScripts(); break;
    case "tests":     loadTests(); break;
    case "tags":      loadTags(); break;
    case "admin":     loadAdminStatus(); break;
  }
}

// ─── Health check ────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const resp = await fetch(`${API_BASE}/health`);
    const dot = document.querySelector(".status-dot");
    const label = document.getElementById("serverStatus");
    if (resp.ok) {
      const data = await resp.json();
      dot.className = "status-dot online";
      label.innerHTML = `<span class="status-dot online"></span> Portal v${data.version || "?"}`;
    } else {
      dot.className = "status-dot offline";
      label.innerHTML = `<span class="status-dot offline">e"></span> Server error`;
    }
  } catch {
    const label = document.getElementById("serverStatus");
    label.innerHTML = `<span class="status-dot offline"></span> Offline`;
  }
}

// ─── API helpers ─────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "KEY": API_KEY,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ─── Dashboard ───────────────────────────────────────────────────────────────

async function refreshDashboard() {
  try {
    const [realtime, agents] = await Promise.all([
      apiFetch("/api/v2/merlino/realtime?window=1h"),
      apiFetch("/api/v2/agents"),
    ]);

    // Stats
    const stats = realtime.globalStats || {};
    setVal("stat-agents-online", agents.filter((a) => a.status === "online" || a.status === "idle" || a.status === "busy").length);
    setVal("stat-tests-running", stats.runningOps || 0);
    setVal("stat-tests-success", stats.completedOps || 0);
    setVal("stat-tests-failed", stats.failedOps || 0);

    // Agents grid
    renderAgentsGrid(agents);

    // Operations table
    renderRecentTests(realtime.operations || []);
  } catch (err) {
    console.error("[DASHBOARD] Load failed:", err.message);
  }
}

function renderRecentTests(operations) {
  const tbody = document.getElementById("recentTestsBody");
  if (!operations.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-row">No tests in the last hour</td></tr>`;
    return;
  }
  tbody.innerHTML = operations.slice(0, 20).map((op) => `
    <tr>
      <td>${op.tcodes ? op.tcodes.map((t) => `<span class="tcode">${t}</span>`).join(" ") : "-"}</td>
      <td>${escHtml(op.name || "-")}</td>
      <td>${escHtml(op.adversary || "-")}</td>
      <td>${stateBadge(op.state)}</td>
      <td>${op.error_count > 0 ? `<span style="color:var(--danger)">${op.error_count}</span>` : `<span style="color:var(--success)">${op.success_count}</span>`}</td>
      <td>${fmtDate(op.started)}</td>
      <td>-</td>
    </tr>
  `).join("");
}

function renderAgentsGrid(agents) {
  const grid = document.getElementById("agentsGrid");
  if (!agents.length) {
    grid.innerHTML = `<div class="empty-state">No agents registered yet. Deploy an agent to get started.</div>`;
    return;
  }
  grid.innerHTML = agents.map((a) => {
    const label = a.alias || a.host || a.hostname || "unknown";
    const sub = a.alias ? (a.host || a.hostname || "") : "";
    return `
    <div class="agent-chip">
      <div class="agent-chip-hostname">${escHtml(label)}</div>
      ${sub ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:2px">${escHtml(sub)}</div>` : ""}
      <div class="agent-chip-meta">${escHtml(a.platform || "?")} &bull; PAW: ${escHtml(a.paw)}</div>
      ${stateBadge(a.status)}
    </div>`;
  }).join("");
}

// ─── Agents ──────────────────────────────────────────────────────────────────

async function loadAgents() {
  try {
    const agents = await apiFetch("/api/v2/agents");
    const tbody = document.getElementById("agentsTableBody");
    if (!agents.length) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty-row">No agents registered</td></tr>`;
      return;
    }
    tbody.innerHTML = agents.map((a) => {
      const nameCell = a.alias
        ? `<span class="agent-alias" id="alias-label-${escHtml(a.paw)}">${escHtml(a.alias)}</span> <button class="rename-btn" onclick="startRenameAgent('${escHtml(a.paw)}','${escHtml(a.alias)}')" title="Rename">[edit]</button>`
        : `<span class="agent-alias-unset" id="alias-label-${escHtml(a.paw)}">${escHtml(a.host || a.hostname || "?")}</span> <button class="rename-btn" onclick="startRenameAgent('${escHtml(a.paw)}','')" title="Set name">[name]</button>`;
      return `
      <tr id="agent-row-${escHtml(a.paw)}">
        <td>${nameCell}</td>
        <td><code style="font-size:11px">${escHtml(a.host || a.hostname || "?")} <span style="color:var(--text-muted)">${escHtml(a.paw)}</span></code></td>
        <td>${escHtml(a.platform || "?")}</td>
        <td>${escHtml(a.os_version || "-")}</td>
        <td>${stateBadge(a.status)}</td>
        <td>${fmtDate(a.last_seen)}</td>
        <td>${a.beacon_interval || 30}s</td>
        <td>${a.tags ? escHtml(a.tags) : "-"}</td>
        <td><span class="version-badge" title="Agent version">${escHtml(a.agent_version || "?")}</span></td>
        <td><button class="btn btn-secondary btn-sm" onclick="openConsole('${escHtml(a.paw)}', '${escHtml(a.alias || a.host || a.hostname || a.paw)}')" title="Open interactive console">Console</button></td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteAgent('${escHtml(a.paw)}')" title="Remove agent">x</button></td>
      </tr>`;
    }).join("");
  } catch (err) {
    console.error("[AGENTS] Load failed:", err.message);
  }
}

function startRenameAgent(paw, currentAlias) {
  const cell = document.querySelector(`#agent-row-${paw} td:first-child`);
  if (!cell) return;
  cell.innerHTML = `
    <input class="agent-alias-edit" id="rename-input-${escHtml(paw)}" value="${escHtml(currentAlias)}" placeholder="Enter name..." />
    <button class="btn btn-primary btn-sm" style="margin-left:4px" onclick="saveAgentAlias('${escHtml(paw)}')">OK</button>
    <button class="btn btn-secondary btn-sm" style="margin-left:2px" onclick="loadAgents()">x</button>
  `;
  const inp = document.getElementById(`rename-input-${paw}`);
  if (inp) { inp.focus(); inp.select(); inp.addEventListener("keydown", (e) => { if (e.key === "Enter") saveAgentAlias(paw); if (e.key === "Escape") loadAgents(); }); }
}

async function saveAgentAlias(paw) {
  const inp = document.getElementById(`rename-input-${paw}`);
  const alias = inp ? inp.value.trim() : "";
  try {
    await apiFetch(`/api/v2/agents/${paw}`, { method: "PATCH", body: JSON.stringify({ alias }) });
    await loadAgents();
  } catch (err) {
    alert("Rename failed: " + err.message);
  }
}

async function deleteAgent(paw) {
  if (!confirm(`Remove agent ${paw} from the database?`)) return;
  try {
    await apiFetch(`/api/v2/agents/${paw}`, { method: "DELETE" });
    await loadAgents();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function purgeStaleAgents() {
  if (!confirm("Delete all agents not seen in the last 24 hours?")) return;
  try {
    const result = await apiFetch("/api/v2/agents?older_than_hours=24", { method: "DELETE" });
    alert(`Purged ${result.purged} stale agent(s).`);
    await loadAgents();
  } catch (err) {
    alert("Purge failed: " + err.message);
  }
}

function showDeployToken() {
  const serverUrl = window.location.origin.replace(/:\/\/[^:]+/, "://SERVER_IP");
  const cmd = `# Windows (run as Administrator)\n.\\morgana-agent.exe install --server ${serverUrl} --token ${API_KEY}\n\n# Linux (run as root)\n./morgana-agent install --server ${serverUrl} --token ${API_KEY}`;
  document.getElementById("installCommand").textContent = cmd;
  document.getElementById("deployModal").classList.remove("hidden");
}

function closeDeployModal() {
  document.getElementById("deployModal").classList.add("hidden");
}

// ─── Scripts ─────────────────────────────────────────────────────────────────

async function loadScripts() {
  if (allScripts.length) { renderScripts(allScripts); return; }
  try {
    // Scripts endpoint - note: this needs server-side implementation
    const resp = await fetch(`${API_BASE}/api/v2/scripts`, { headers: { KEY: API_KEY } });
    if (resp.ok) {
      allScripts = await resp.json();
    } else {
      allScripts = [];
    }
    renderScripts(allScripts);
  } catch {
    renderScripts([]);
  }
}

function renderScripts(scripts) {
  const tbody = document.getElementById("scriptsTableBody");
  if (!scripts.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No scripts loaded. Make sure the Atomic Red Team submodule is initialized.</td></tr>`;
    return;
  }
  tbody.innerHTML = scripts.slice(0, 500).map((s) => `
    <tr>
      <td><span class="tcode">${escHtml(s.tcode || "?")}</span></td>
      <td>${escHtml(s.name || "?")}</td>
      <td>${escHtml(s.tactic || "-")}</td>
      <td><code>${escHtml(s.executor || "?")}</code></td>
      <td>${escHtml(s.platform || "all")}</td>
      <td><span style="font-size:11px;color:var(--text-muted)">${escHtml(s.source || "custom")}</span></td>
      <td id="tags-script-${escHtml(s.id)}" class="tags-container" style="min-width:80px"></td>
      <td><button class="btn-open" onclick="openScriptModal('${escHtml(s.id)}')">Open</button></td>
    </tr>
  `).join("");
  // Load tags asynchronously for each row (batch, non-blocking)
  scripts.slice(0, 500).forEach((s) => loadEntityTagsInline("script", s.id, `tags-script-${s.id}`));
}

function filterScripts() {
  const query = (document.getElementById("scriptSearch").value || "").toLowerCase();
  const platform = document.getElementById("scriptPlatform").value;
  const filtered = allScripts.filter((s) => {
    const matchQuery = !query || (s.tcode || "").toLowerCase().includes(query) || (s.name || "").toLowerCase().includes(query);
    const matchPlatform = !platform || (s.platform || "all").includes(platform) || s.platform === "all";
    return matchQuery && matchPlatform;
  });
  renderScripts(filtered);
}

// ─── Tests ───────────────────────────────────────────────────────────────────

async function loadTests() {
  try {
    const realtime = await apiFetch("/api/v2/merlino/realtime?window=24h");
    const tbody = document.getElementById("testsTableBody");
    const ops = realtime.operations || [];
    if (!ops.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No tests in the last 24 hours</td></tr>`;
      return;
    }
    tbody.innerHTML = ops.map((op) => `
      <tr>
        <td>${escHtml(op.name || "-")}</td>
        <td>${(op.tcodes || []).map((t) => `<span class="tcode">${t}</span>`).join(" ")}</td>
        <td>${escHtml(op.adversary || "-")}</td>
        <td>${stateBadge(op.state)}</td>
        <td>${op.error_count > 0 ? `<span style="color:var(--danger)">${op.error_count} errors</span>` : `<span style="color:var(--success)">${op.success_count} ok</span>`}</td>
        <td>${op.total_abilities || 1}</td>
        <td>${fmtDate(op.started)}</td>
        <td>${fmtDate(op.finish_time)}</td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("[TESTS] Load failed:", err.message);
  }
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function stateBadge(state) {
  const s = (state || "unknown").toLowerCase();
  const map = {
    running: "badge-running", finished: "badge-finished", failed: "badge-failed",
    pending: "badge-pending", paused: "badge-paused", online: "badge-online",
    offline: "badge-offline", idle: "badge-idle", busy: "badge-busy",
  };
  return `<span class="badge ${map[s] || "badge-pending"}">${s}</span>`;
}

function escHtml(str) {
  return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return isoStr; }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ─── Admin ───────────────────────────────────────────────────────────────────

async function loadAdminStatus() {
  try {
    const data = await apiFetch("/api/v2/admin/atomics/status");
    setVal("admin-atomic-db", data.atomic_scripts_in_db ?? "-");
    setVal("admin-custom-db", data.custom_scripts_in_db ?? "-");
    setVal("admin-yaml-disk", data.yaml_files_on_disk ?? "-");

    const tbody = document.getElementById("admin-last-run-body");
    const stats = data.last_run_stats || {};
    if (!Object.keys(stats).length) {
      tbody.innerHTML = `<tr><td colspan="2" class="empty-row">No run data yet</td></tr>`;
    } else {
      tbody.innerHTML = [
        ["New scripts loaded", stats.loaded ?? 0],
        ["Updated (changed)", stats.updated ?? 0],
        ["Skipped (unchanged)", stats.skipped ?? 0],
        ["Errors", stats.errors ?? 0],
      ].map(([label, val]) =>
        `<tr><td>${label}</td><td><strong>${val}</strong></td></tr>`
      ).join("");
    }

    // Pre-fill API key input
    const input = document.getElementById("apiKeyInput");
    if (input) input.value = API_KEY;

  } catch (err) {
    console.error("[ADMIN] Status load failed:", err.message);
  }
}

async function reloadAtomics() {
  const btn = document.getElementById("reloadBtn");
  const log = document.getElementById("admin-reload-log");
  btn.disabled = true;
  btn.textContent = "Reloading...";
  log.className = "admin-log";
  log.textContent = "[START] Sending reload request...";

  try {
    const data = await apiFetch("/api/v2/admin/atomics/reload", { method: "POST", body: "{}" });
    const s = data.stats || {};
    log.textContent = `[SUCCESS] Reload complete\n  loaded:  ${s.loaded ?? 0}\n  updated: ${s.updated ?? 0}\n  skipped: ${s.skipped ?? 0}\n  errors:  ${s.errors ?? 0}`;
    log.classList.add("log-success");
    // Refresh stats
    await loadAdminStatus();
    // Refresh script count on dashboard
    apiFetch("/api/v2/scripts?limit=1&count_only=true")
      .then((d) => setVal("stat-scripts-total", d.total || 0))
      .catch(() => {});
  } catch (err) {
    log.textContent = `[ERROR] Reload failed: ${err.message}`;
    log.classList.add("log-error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Reload Atomic Scripts";
  }
}

function saveApiKey() {
  const val = (document.getElementById("apiKeyInput").value || "").trim();
  if (!val) return;
  localStorage.setItem("morgana_api_key", val);
  const saved = document.getElementById("apiKeySaved");
  saved.style.display = "inline";
  setTimeout(() => { saved.style.display = "none"; }, 2000);
  // Reload page to pick up new key
  location.reload();
}

// ─── Script Editor Modal ──────────────────────────────────────────────────────

let _currentScriptId = null;
let _currentScriptIsAtomic = false;

function openNewScriptModal() {
  _currentScriptId = null;
  _currentScriptIsAtomic = false;
  document.getElementById("scriptModalTitle").textContent = "New Script";
  ["sm-name", "sm-tcode", "sm-tactic", "sm-description", "sm-command", "sm-cleanup", "sm-source"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  setVal("sm-source", "custom");
  document.getElementById("sm-executor").value = "powershell";
  document.getElementById("sm-platform").value = "windows";
  document.getElementById("sm-delete-btn").style.display = "none";
  document.getElementById("sm-tags-container").innerHTML = "<span class='admin-hint'>Save script first to assign tags.</span>";
  _loadAgentOptions();
  document.getElementById("sm-execute-result").style.display = "none";
  document.getElementById("scriptModal").classList.remove("hidden");
}

function openScriptModal(scriptId) {
  const s = allScripts.find((x) => String(x.id) === String(scriptId));
  if (!s) { console.warn("[SCRIPT_MODAL] Script not found:", scriptId); return; }
  _currentScriptId = s.id;
  _currentScriptIsAtomic = (s.source || "") !== "custom";

  document.getElementById("scriptModalTitle").textContent = escHtml(s.name || "Script");
  document.getElementById("sm-name").value = s.name || "";
  document.getElementById("sm-tcode").value = s.tcode || "";
  document.getElementById("sm-tactic").value = s.tactic || "";
  document.getElementById("sm-description").value = s.description || "";
  document.getElementById("sm-command").value = s.command || "";
  document.getElementById("sm-cleanup").value = s.cleanup_command || "";
  document.getElementById("sm-source").value = s.source || "custom";
  document.getElementById("sm-executor").value = s.executor || "powershell";
  document.getElementById("sm-platform").value = s.platform || "all";

  // Atomic scripts are read-only except for tags/execute
  const readOnly = _currentScriptIsAtomic;
  ["sm-name", "sm-tcode", "sm-tactic", "sm-description", "sm-command", "sm-cleanup"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.readOnly = readOnly;
  });
  document.getElementById("sm-delete-btn").style.display = readOnly ? "none" : "inline-flex";

  document.getElementById("sm-execute-result").style.display = "none";
  _loadAgentOptions();
  loadEntityTagsInModal("script", s.id, "sm-tags-container");
  document.getElementById("scriptModal").classList.remove("hidden");
}

function closeScriptModal() {
  document.getElementById("scriptModal").classList.add("hidden");
  _currentScriptId = null;
}

async function saveScriptFromModal() {
  const payload = {
    name: document.getElementById("sm-name").value.trim(),
    tcode: document.getElementById("sm-tcode").value.trim(),
    tactic: document.getElementById("sm-tactic").value.trim(),
    description: document.getElementById("sm-description").value.trim(),
    command: document.getElementById("sm-command").value,
    cleanup_command: document.getElementById("sm-cleanup").value,
    executor: document.getElementById("sm-executor").value,
    platform: document.getElementById("sm-platform").value,
  };
  if (!payload.name || !payload.tcode || !payload.command) {
    alert("Name, TCode and Command are required.");
    return;
  }
  try {
    if (_currentScriptId) {
      await apiFetch(`/api/v2/scripts/${_currentScriptId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const created = await apiFetch("/api/v2/scripts", { method: "POST", body: JSON.stringify(payload) });
      _currentScriptId = created.id;
    }
    // Refresh local cache
    const updated = await apiFetch("/api/v2/scripts?limit=5000");
    allScripts = updated.scripts || updated || [];
    document.getElementById("scriptModalTitle").textContent = escHtml(payload.name);
    document.getElementById("sm-delete-btn").style.display = "inline-flex";
    alert("Script saved.");
  } catch (err) {
    alert("Save failed: " + err.message);
  }
}

async function deleteScriptFromModal() {
  if (!_currentScriptId) return;
  if (!confirm("Delete this script permanently?")) return;
  try {
    await apiFetch(`/api/v2/scripts/${_currentScriptId}`, { method: "DELETE" });
    allScripts = allScripts.filter((s) => String(s.id) !== String(_currentScriptId));
    renderScripts(allScripts);
    closeScriptModal();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function _loadAgentOptions() {
  const sel = document.getElementById("sm-agent-select");
  try {
    const agents = await apiFetch("/api/v2/agents");
    const list = agents.agents || agents || [];
    sel.innerHTML = `<option value="">Select agent...</option>` +
      list.map((a) => {
        const host = a.host || a.hostname || "";
        let label = a.alias ? `${a.alias}  (${host})` : host;
        label += `  [${a.paw}]`;
        return `<option value="${escHtml(a.paw)}">${escHtml(label)}</option>`;
      }).join("");
  } catch (err) {
    sel.innerHTML = `<option value="">Could not load agents</option>`;
  }
}

async function executeScriptFromModal() {
  if (!_currentScriptId) { alert("Save the script before executing."); return; }
  const paw = document.getElementById("sm-agent-select").value;
  if (!paw) { alert("Select an agent first."); return; }
  const resultEl = document.getElementById("sm-execute-result");
  const outputSec = document.getElementById("sm-output-section");
  const outputPre = document.getElementById("sm-output-pre");
  const outputStatus = document.getElementById("sm-output-status");

  resultEl.textContent = "Queuing...";
  resultEl.style.display = "inline";
  outputSec.style.display = "none";
  outputPre.textContent = "";

  try {
    const result = await apiFetch(`/api/v2/scripts/${_currentScriptId}/execute`, {
      method: "POST",
      body: JSON.stringify({ paw }),
    });
    if (!result.queued) {
      resultEl.textContent = "[WARN] Unexpected response.";
      return;
    }
    resultEl.textContent = `[OK] Job queued (${result.job_id.slice(0, 8)}...)`;
    // Show output panel and start polling
    outputSec.style.display = "block";
    outputStatus.textContent = "Running...";
    outputPre.textContent = "";
    pollJobOutput(result.job_id, outputPre, outputStatus, resultEl);
  } catch (err) {
    resultEl.textContent = "[ERROR] " + err.message;
  }
}

async function pollJobOutput(jobId, pre, statusEl, resultEl) {
  const MAX_POLLS = 120; // 60 s at 500 ms
  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const job = await apiFetch(`/api/v2/jobs/${jobId}`);
      if (job.status === "completed" || job.status === "failed" || job.state === "finished" || job.state === "failed") {
        const exitOk = job.exit_code === 0;
        statusEl.textContent = `Exit code: ${job.exit_code ?? "?"} | ${job.duration_ms ?? 0} ms`;
        resultEl.textContent = `[${exitOk ? "SUCCESS" : "FAILED"}] Exit ${job.exit_code ?? "?"}` ;
        let out = "";
        if (job.stdout) out += job.stdout;
        if (job.stderr) out += (out ? "\n--- STDERR ---\n" : "") + job.stderr;
        pre.textContent = out || "(no output)";
        return;
      }
    } catch (_) { /* server may not have result yet */ }
  }
  statusEl.textContent = "(timeout - check Tests page for result)";
}


// ─── Tags ─────────────────────────────────────────────────────────────────────


// --- Console (reverse shell) --------------------------------------------------

let _consoleWS = null;
let _consoleTerm = null;
let _consoleFitAddon = null;

function openConsole(paw, label) {
  if (_consoleWS) { _consoleWS.close(); _consoleWS = null; }
  document.getElementById("consoleAgentLabel").textContent = label || paw;
  document.getElementById("consoleStatus").textContent = "Connecting...";
  document.getElementById("consoleModal").classList.remove("hidden");

  const container = document.getElementById("consoleTerminal");
  container.innerHTML = "";

  _consoleTerm = new Terminal({
    fontFamily: "Consolas, 'Courier New', monospace",
    fontSize: 13,
    theme: { background: "#0d0d0d", foreground: "#e0e0e0", cursor: "#667eea" },
    cursorBlink: true,
    convertEol: true,
    scrollback: 2000,
  });
  _consoleFitAddon = new FitAddon.FitAddon();
  _consoleTerm.loadAddon(_consoleFitAddon);
  _consoleTerm.open(container);
  _consoleFitAddon.fit();

  _consoleTerm.onData((data) => {
    if (_consoleWS && _consoleWS.readyState === WebSocket.OPEN) _consoleWS.send(data);
  });

  const proto = API_BASE.startsWith("https") ? "wss" : "ws";
  const wsURL = `${proto}://${window.location.host}/api/v2/console/ws/${encodeURIComponent(paw)}?key=${encodeURIComponent(API_KEY)}`;
  _consoleWS = new WebSocket(wsURL);

  _consoleWS.onopen = () => { document.getElementById("consoleStatus").textContent = "Connected"; };
  _consoleWS.onmessage = (evt) => { _consoleTerm.write(evt.data); };
  _consoleWS.onerror = () => { document.getElementById("consoleStatus").textContent = "Error"; _consoleTerm.write("\r\n[ERROR] WebSocket error.\r\n"); };
  _consoleWS.onclose = () => { document.getElementById("consoleStatus").textContent = "Disconnected"; if (_consoleTerm) _consoleTerm.write("\r\n[CONSOLE] Session closed.\r\n"); };

  window.addEventListener("resize", _consoleResize);
}

function _consoleResize() { if (_consoleFitAddon) { try { _consoleFitAddon.fit(); } catch (_) {} } }

function closeConsole() {
  if (_consoleWS) { _consoleWS.close(); _consoleWS = null; }
  if (_consoleTerm) { _consoleTerm.dispose(); _consoleTerm = null; }
  window.removeEventListener("resize", _consoleResize);
  document.getElementById("consoleModal").classList.add("hidden");
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("consoleModal").classList.contains("hidden")) closeConsole();
});
let _allTags = [];
let _tagPickerContext = { entityType: null, entityId: null };

async function loadTags() {
  try {
    const data = await apiFetch("/api/v2/tags");
    _allTags = data.tags || data || [];
    renderTagsAdmin(_allTags);
  } catch (err) {
    console.error("[TAGS] Load failed:", err.message);
  }
}

function renderTagsAdmin(tags) {
  const tbody = document.getElementById("tagsTableBody");
  if (!tbody) return;
  if (!tags.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No tags defined yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = tags.map((t) => `
    <tr>
      <td><span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}">${escHtml(t.name)}</span></td>
      <td>${escHtml(t.group_name || "-")}</td>
      <td>${escHtml(t.scope || "all")}</td>
      <td style="font-size:12px">${escHtml(t.description || "")}</td>
      <td>-</td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteTag('${escHtml(t.id)}')">Delete</button></td>
    </tr>
  `).join("");
}

function showCreateTagForm() {
  const form = document.getElementById("createTagForm");
  if (form) form.classList.remove("hidden");
}

function hideCreateTagForm() {
  const form = document.getElementById("createTagForm");
  if (form) form.classList.add("hidden");
  ["tagName", "tagGroup", "tagDescription"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const scopeEl = document.getElementById("tagScope");
  if (scopeEl) scopeEl.value = "all";
  const colorEl = document.getElementById("tagColor");
  if (colorEl) colorEl.value = "#667eea";
}

async function createTag() {
  const name = (document.getElementById("tagName")?.value || "").trim();
  const group = (document.getElementById("tagGroup")?.value || "").trim();
  const scope = document.getElementById("tagScope")?.value || "all";
  const color = document.getElementById("tagColor")?.value || "#667eea";
  const description = (document.getElementById("tagDescription")?.value || "").trim();
  if (!name) { alert("Tag name is required."); return; }
  try {
    await apiFetch("/api/v2/tags", {
      method: "POST",
      body: JSON.stringify({ name, group_name: group, scope, color, description }),
    });
    hideCreateTagForm();
    await loadTags();
  } catch (err) {
    alert("Create tag failed: " + err.message);
  }
}

async function deleteTag(tagId) {
  if (!confirm("Delete this tag? All assignments will also be removed.")) return;
  try {
    await apiFetch(`/api/v2/tags/${tagId}`, { method: "DELETE" });
    await loadTags();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

// Load tags for a table-row cell (inline, non-blocking)
async function loadEntityTagsInline(entityType, entityId, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  try {
    const data = await apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}`);
    const tags = data.tags || data || [];
    el.innerHTML = tags.map((t) =>
      `<span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}" title="${escHtml(t.description || t.name)}">${escHtml(t.name)}</span>`
    ).join("");
  } catch (err) {
    el.innerHTML = "";
  }
}

// Load tags for the script modal (with remove buttons)
async function loadEntityTagsInModal(entityType, entityId, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "<span class='admin-hint'>Loading...</span>";
  try {
    const data = await apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}`);
    const tags = data.tags || data || [];
    if (!tags.length) {
      el.innerHTML = "<span class='admin-hint'>No tags assigned.</span>";
    } else {
      el.innerHTML = tags.map((t) =>
        `<span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}">
          ${escHtml(t.name)}
          <span class="tag-x" onclick="removeEntityTag('${escHtml(entityType)}','${escHtml(entityId)}','${escHtml(t.id)}','${escHtml(containerId)}')" title="Remove">x</span>
        </span>`
      ).join("");
    }
  } catch (err) {
    el.innerHTML = "<span class='admin-hint'>[ERROR] Could not load tags.</span>";
  }
}

async function removeEntityTag(entityType, entityId, tagId, containerId) {
  try {
    await apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}/${tagId}`, { method: "DELETE" });
    loadEntityTagsInModal(entityType, entityId, containerId);
    // Also refresh inline row if on scripts page
    loadEntityTagsInline(entityType, entityId, `tags-${entityType}-${entityId}`);
  } catch (err) {
    alert("Remove tag failed: " + err.message);
  }
}

// Tag picker modal
function openTagPicker(entityType, entityId) {
  if (!entityId) return;
  _tagPickerContext = { entityType, entityId };
  document.getElementById("tagPickerSearch").value = "";
  _renderTagPickerList(entityType, entityId);
  document.getElementById("tagPickerModal").classList.remove("hidden");
}

function closeTagPicker() {
  document.getElementById("tagPickerModal").classList.add("hidden");
  // Refresh modal tags if open
  if (_currentScriptId) {
    loadEntityTagsInModal("script", _currentScriptId, "sm-tags-container");
    loadEntityTagsInline("script", _currentScriptId, `tags-script-${_currentScriptId}`);
  }
}

async function _renderTagPickerList(entityType, entityId, filter) {
  const listEl = document.getElementById("tagPickerList");
  listEl.innerHTML = "<span class='admin-hint'>Loading...</span>";
  try {
    const [allData, assigned] = await Promise.all([
      apiFetch("/api/v2/tags"),
      apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}`),
    ]);
    const all = allData.tags || allData || [];
    const assignedIds = new Set((assigned.tags || assigned || []).map((t) => String(t.id)));
    const q = (filter || "").toLowerCase();
    const filtered = q ? all.filter((t) => t.name.toLowerCase().includes(q) || (t.group_name || "").toLowerCase().includes(q)) : all;
    if (!filtered.length) {
      listEl.innerHTML = "<span class='admin-hint'>No tags available. Create them in Admin.</span>";
      return;
    }
    listEl.innerHTML = filtered.map((t) => {
      const isAssigned = assignedIds.has(String(t.id));
      return `<span class="tag-item ${isAssigned ? "assigned" : ""}"
        onclick="toggleTagAssignment('${escHtml(entityType)}','${escHtml(entityId)}','${escHtml(t.id)}',${!isAssigned})"
        style="border-color:${isAssigned ? escHtml(t.color || "#667eea") : ""}">
        <span style="width:10px;height:10px;border-radius:50%;background:${escHtml(t.color || "#667eea")};display:inline-block"></span>
        ${escHtml(t.name)}${t.group_name ? ` <span style="opacity:.5;font-size:11px">${escHtml(t.group_name)}</span>` : ""}
      </span>`;
    }).join("");
  } catch (err) {
    listEl.innerHTML = `<span class='admin-hint'>[ERROR] ${escHtml(err.message)}</span>`;
  }
}

function filterTagPicker() {
  const q = document.getElementById("tagPickerSearch").value;
  _renderTagPickerList(_tagPickerContext.entityType, _tagPickerContext.entityId, q);
}

async function toggleTagAssignment(entityType, entityId, tagId, assign) {
  try {
    if (assign) {
      await apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}`, {
        method: "POST",
        body: JSON.stringify({ tag_id: tagId }),
      });
    } else {
      await apiFetch(`/api/v2/tags/entity/${entityType}/${entityId}/${tagId}`, { method: "DELETE" });
    }
    _renderTagPickerList(entityType, entityId, document.getElementById("tagPickerSearch").value);
  } catch (err) {
    alert("Tag assignment failed: " + err.message);
  }
}


// ─── Boot ─────────────────────────────────────────────────────────────────────

(function init() {
  checkHealth();
  refreshDashboard();
  setInterval(checkHealth, 30000);
  setInterval(() => {
    const activePage = document.querySelector(".page.active");
    if (activePage && activePage.id === "page-dashboard") refreshDashboard();
  }, REFRESH_INTERVAL);

  // Try to load script count for stat
  apiFetch("/api/v2/scripts?limit=1&count_only=true")
    .then((data) => setVal("stat-scripts-total", data.total || 0))
    .catch(() => {});
})();
