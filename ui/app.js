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

// Chain builder state
let _allChains = [];
let _allCampaigns = [];
let _editingChain = { id: null, name: "", description: "", nodes: [] };
let _chainAddMenuCtx = null; // { branch, index, ifElseId }
let _chainPickerCtx  = null; // { type: "insert"|"replace", nodeId, branch, ifElseId, index }
// Unsaved-changes flags for save-before-execute
let _scriptDirty   = false;
let _chainDirty    = false;
let _campaignDirty = false;

// Campaign builder state
let _editingCampaign = { id: null, name: "New Campaign", description: "", agent_paw: "", nodes: [] };
let _campAddMenuCtx  = null;
let _campPickerCtx   = null;
let _campAllChains   = [];

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
    case "dashboard": refreshDashboard();   break;
    case "agents":    loadAgents();          break;
    case "scripts":   loadScripts();         break;
    case "tests":     loadTests();           break;
    case "chains":    loadChains();          break;
    case "campaigns": loadCampaigns();       break;
    case "tags":      loadTags();            break;
    case "admin":     loadAdminStatus();     break;
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
  if (resp.status === 204 || resp.headers.get("content-length") === "0") return null;
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
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No tests in the last hour</td></tr>`;
    return;
  }
  tbody.innerHTML = operations.slice(0, 20).map((op) => {
    const tcode = op.tcodes && op.tcodes.length
      ? op.tcodes.map((t) => `<span class="tcode">${t}</span>`).join(" ")
      : "-";
    const typeBadge = op.type === "Chain"
      ? `<span style="color:#f59e0b;font-size:11px">Chain</span>`
      : `<span style="color:var(--accent);font-size:11px">Script</span>`;
    const agent = op.agent_hostname
      ? `${escHtml(op.agent_hostname)} [${escHtml(op.agent_paw || "")}]`
      : (op.agent_paw ? escHtml(op.agent_paw) : "-");
    const dur = op.duration_ms != null ? `${op.duration_ms} ms` : "-";
    const exit = op.error_count > 0
      ? `<span style="color:var(--danger)">${op.error_count} err</span>`
      : `<span style="color:var(--success)">${op.success_count} ok</span>`;
    return `<tr>
      <td>${tcode}</td>
      <td>${typeBadge}</td>
      <td>${escHtml(op.op_name || op.name || "-")}</td>
      <td>${agent}</td>
      <td>${stateBadge(op.state)}</td>
      <td>${exit}</td>
      <td style="white-space:nowrap;font-size:0.8rem">${fmtDateTime(op.started)}</td>
      <td style="white-space:nowrap">${dur}</td>
    </tr>`;
  }).join("");
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
        <td><span class="beacon-click" id="beacon-${escHtml(a.paw)}" onclick="editAgentBeacon('${escHtml(a.paw)}', ${a.beacon_interval || 30})" title="Click to change beacon interval">${a.beacon_interval || 30}s</span></td>
        <td>${a.tags ? escHtml(a.tags) : "-"}</td>
        <td><span class="version-badge" title="Agent version">${escHtml(a.agent_version || "?")}</span></td>
        <td style="white-space:nowrap">
          <button class="btn btn-secondary btn-sm" onclick="openNativeConsole('${escHtml(a.paw)}')" title="Open native terminal window connected to this agent">Console</button>
          <button class="console-reset-btn" onclick="resetAndRelaunchConsole('${escHtml(a.paw)}')" title="Kill current session and open a fresh console">Reset</button>
        </td>
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
  const origin = window.location.origin;
  const isHttps = origin.startsWith("https");
  const token   = typeof API_KEY !== "undefined" ? API_KEY : "MORGANA_ADMIN_KEY";

  // Windows one-liner (PS 5.1 compatible, handles self-signed TLS)
  const winCmd = isHttps
    ? `[Net.ServicePointManager]::ServerCertificateValidationCallback={$true}; iex (New-Object Net.WebClient).DownloadString('${origin}/install/windows?token=${token}')`
    : `iex (irm '${origin}/install/windows?token=${token}')`;

  // Linux one-liner
  const linCmd = isHttps
    ? `curl -ksSL '${origin}/install/linux?token=${token}' | sudo bash`
    : `curl -sSL '${origin}/install/linux?token=${token}' | sudo bash`;

  document.getElementById("deploy-win-cmd").textContent = winCmd;
  document.getElementById("deploy-lin-cmd").textContent = linCmd;
  document.getElementById("deployModal").classList.remove("hidden");
}

function copyDeployCmd(elId) {
  const txt = document.getElementById(elId).textContent;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(txt).then(() => {
      alert("[OK] Command copied to clipboard.");
    }).catch(() => _copyFallback(txt));
  } else {
    _copyFallback(txt);
  }
}

function _copyFallback(txt) {
  const ta = document.createElement("textarea");
  ta.value = txt;
  ta.style.position = "fixed";
  ta.style.opacity  = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  alert("[OK] Command copied to clipboard.");
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
    populateTacticDropdown();
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
      <td style="white-space:nowrap">
        <button class="btn-open" onclick="openScriptModal('${escHtml(s.id)}')">Open</button>
        <button class="btn btn-primary btn-sm" style="margin-left:4px" onclick="quickExecuteScript('${escHtml(s.id)}')">Execute</button>
        <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="duplicateScript('${escHtml(s.id)}')">Duplicate</button>
        <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteScript('${escHtml(s.id)}')">Delete</button>
      </td>
    </tr>
  `).join("");
  // Load tags asynchronously for each row (batch, non-blocking)
  scripts.slice(0, 500).forEach((s) => loadEntityTagsInline("script", s.id, `tags-script-${s.id}`));
}

function filterScripts() {
  const query = (document.getElementById("scriptSearch").value || "").toLowerCase();
  const tactic = document.getElementById("scriptTactic")?.value || "";
  const executor = document.getElementById("scriptExecutor")?.value || "";
  const platform = document.getElementById("scriptPlatform").value;
  const filtered = allScripts.filter((s) => {
    const matchQuery = !query || (s.tcode || "").toLowerCase().includes(query) || (s.name || "").toLowerCase().includes(query);
    const matchTactic = !tactic || (s.tactic || "") === tactic;
    const matchExecutor = !executor || (s.executor || "") === executor;
    const matchPlatform = !platform || (s.platform || "all").includes(platform) || s.platform === "all";
    return matchQuery && matchTactic && matchExecutor && matchPlatform;
  });
  renderScripts(filtered);
}

function clearScriptFilters() {
  document.getElementById("scriptSearch").value = "";
  const t = document.getElementById("scriptTactic"); if (t) t.value = "";
  const e = document.getElementById("scriptExecutor"); if (e) e.value = "";
  document.getElementById("scriptPlatform").value = "";
  renderScripts(allScripts);
}

function populateTacticDropdown() {
  const sel = document.getElementById("scriptTactic");
  if (!sel) return;
  const tactics = [...new Set(allScripts.map((s) => s.tactic).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All tactics</option>' +
    tactics.map((t) => `<option value="${escHtml(t)}">${escHtml(t)}</option>`).join("");
}

async function deleteScript(scriptId) {
  if (!confirm("Delete this script? This cannot be undone.")) return;
  try {
    await apiFetch(`/api/v2/scripts/${scriptId}`, { method: "DELETE" });
    allScripts = allScripts.filter((s) => s.id !== scriptId);
    filterScripts();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

// Returns the next available " - Copy N" name given a base name and a list of existing names
function _nextCopyName(name, existingNames) {
  const base = name.replace(/ - Copy( \d+)?$/, "");
  const taken = new Set(existingNames);
  let candidate = base + " - Copy";
  if (!taken.has(candidate)) return candidate;
  for (let i = 2; i < 200; i++) {
    candidate = base + " - Copy " + i;
    if (!taken.has(candidate)) return candidate;
  }
  return base + " - Copy " + Date.now();
}

async function duplicateScript(id) {
  const s = allScripts.find((x) => String(x.id) === String(id));
  if (!s) { alert("Script not found."); return; }
  const newName = _nextCopyName(s.name, allScripts.map((x) => x.name));
  try {
    await apiFetch("/api/v2/scripts", {
      method: "POST",
      body: JSON.stringify({
        name: newName,
        tcode: s.tcode,
        tactic: s.tactic,
        description: s.description,
        command: s.command,
        cleanup_command: s.cleanup_command,
        executor: s.executor,
        platform: s.platform,
      }),
    });
    allScripts = [];
    await loadScripts();
  } catch (err) {
    alert("Duplicate failed: " + err.message);
  }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

let _testDetailId = null;

async function loadTests() {
  const tbody = document.getElementById("testsTableBody");
  try {
    const tests = await apiFetch("/api/v2/tests?limit=200");
    if (!tests.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty-row">No tests yet</td></tr>`;
      return;
    }
    tbody.innerHTML = tests.map((t) => {
      const agent = t.agent_hostname ? `${escHtml(t.agent_hostname)} [${escHtml(t.agent_paw || "")}]` : "-";
      const dur = t.duration_ms != null ? `${t.duration_ms} ms` : "-";
      const tcode = t.tcode ? `<span class="tcode">${escHtml(t.tcode)}</span>` : "-";
      const opName = t.operation_name || "";
      let testType, testName;
      if (opName.startsWith("chain:"))       { testType = "Chain";  testName = opName.slice(6) || "-"; }
      else if (opName.startsWith("manual:")) { testType = "Script"; testName = opName.slice(7) || "-"; }
      else if (opName === "adhoc")           { testType = "Script"; testName = "Ad-hoc"; }
      else                                   { testType = "Script"; testName = opName || "-"; }
      const typeBadge = testType === "Chain"
        ? `<span style="color:#f59e0b;font-size:11px">Chain</span>`
        : `<span style="color:var(--accent);font-size:11px">Script</span>`;
      return `<tr>
        <td style="white-space:nowrap;font-size:0.8rem">${fmtDateTime(t.created_at)}</td>
        <td>${tcode}</td>
        <td>${typeBadge}</td>
        <td>${escHtml(testName)}</td>
        <td>${escHtml(agent)}</td>
        <td>${stateBadge(t.state)}</td>
        <td style="text-align:center">${t.exit_code != null ? t.exit_code : "-"}</td>
        <td style="white-space:nowrap">${dur}</td>
        <td style="white-space:nowrap">
          <button class="btn btn-secondary btn-sm" onclick="openTestModal('${escHtml(t.id)}')">View</button>
          <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteTest('${escHtml(t.id)}')">Delete</button>
        </td>
      </tr>`;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-row">Error: ${escHtml(err.message)}</td></tr>`;
    console.error("[TESTS] Load failed:", err.message);
  }
}

async function openTestModal(testId) {
  _testDetailId = testId;
  try {
    const t = await apiFetch(`/api/v2/tests/${testId}`);
    document.getElementById("testDetailTitle").textContent = `Test: ${t.tcode || t.operation_name || testId.slice(0,8)}`;
    document.getElementById("td-id").textContent = t.id;
    document.getElementById("td-tcode").textContent = t.tcode || "-";
    document.getElementById("td-state").innerHTML = stateBadge(t.state);
    document.getElementById("td-exit").textContent = t.exit_code != null ? t.exit_code : "-";
    document.getElementById("td-agent").textContent = t.agent_hostname ? `${t.agent_hostname} [${t.agent_paw}]` : "-";
    document.getElementById("td-duration").textContent = t.duration_ms != null ? `${t.duration_ms} ms` : "-";
    document.getElementById("td-created").textContent = fmtDateTime(t.created_at);
    document.getElementById("td-finished").textContent = fmtDateTime(t.finished_at);
    document.getElementById("td-stdout").textContent = t.stdout || "(no output)";
    document.getElementById("td-stderr").textContent = t.stderr || "";
    document.getElementById("testDetailModal").classList.remove("hidden");
  } catch (err) {
    alert("Could not load test: " + err.message);
  }
}

function closeTestModal() {
  document.getElementById("testDetailModal").classList.add("hidden");
  _testDetailId = null;
}

async function deleteTestFromModal() {
  if (!_testDetailId) return;
  if (!confirm("Delete this test?")) return;
  await deleteTest(_testDetailId);
  closeTestModal();
}

async function deleteTest(testId) {
  if (!confirm("Delete this test? This cannot be undone.")) return;
  try {
    await apiFetch(`/api/v2/tests/${testId}`, { method: "DELETE" });
    await loadTests();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function deleteAllTests() {
  if (!confirm("Delete ALL tests and their output? This cannot be undone.")) return;
  try {
    await apiFetch("/api/v2/tests", { method: "DELETE" });
    await loadTests();
  } catch (err) {
    alert("Delete all failed: " + err.message);
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

function fmtDateTime(isoStr) {
  if (!isoStr) return "-";
  try {
    const d = new Date(isoStr);
    const date = d.toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "2-digit" });
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `${date} ${time}`;
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

    // Load global settings (beacon default)
    loadGlobalSettings();

  } catch (err) {
    console.error("[ADMIN] Status load failed:", err.message);
  }
}

async function loadGlobalSettings() {
  try {
    const data = await apiFetch("/api/v2/admin/settings");
    const el = document.getElementById("globalBeaconInput");
    if (el && data.default_beacon_interval) el.value = data.default_beacon_interval;
  } catch (err) {
    console.warn("[ADMIN] Load global settings failed:", err.message);
  }
}

async function saveGlobalSettings() {
  const val = parseInt(document.getElementById("globalBeaconInput").value, 10);
  if (!val || val < 5 || val > 3600) { alert("Beacon must be 5-3600 seconds"); return; }
  try {
    await apiFetch("/api/v2/admin/settings", { method: "PUT", body: JSON.stringify({ default_beacon_interval: val }) });
    const saved = document.getElementById("globalSettingsSaved");
    if (saved) { saved.style.display = "inline"; setTimeout(() => { saved.style.display = "none"; }, 2000); }
  } catch (err) {
    console.error("[ADMIN] Save global settings failed:", err.message);
  }
}

function editAgentBeacon(paw, current) {
  const span = document.getElementById(`beacon-${paw}`);
  if (!span) return;
  const td = span.closest("td");
  td.innerHTML = `
    <input type="number" class="beacon-edit-input" id="beacon-input-${escHtml(paw)}"
      value="${current}" min="5" max="3600" style="width:58px;text-align:center" />
    <button class="btn btn-primary btn-sm" style="margin-left:3px" onclick="saveAgentBeacon('${escHtml(paw)}')">OK</button>
    <button class="btn btn-secondary btn-sm" style="margin-left:2px" onclick="loadAgents()">x</button>
  `;
  const inp = document.getElementById(`beacon-input-${paw}`);
  if (inp) { inp.focus(); inp.select(); }
}

async function saveAgentBeacon(paw) {
  const inp = document.getElementById(`beacon-input-${paw}`);
  if (!inp) return;
  const val = parseInt(inp.value, 10);
  if (!val || val < 5 || val > 3600) { alert("Beacon must be 5-3600 seconds"); return; }
  try {
    await apiFetch(`/api/v2/agents/${encodeURIComponent(paw)}`, {
      method: "PATCH",
      body: JSON.stringify({ beacon_interval: val }),
    });
    await loadAgents();
  } catch (err) {
    console.error("[AGENTS] Save beacon failed:", err.message);
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
  _scriptDirty = true;
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
  document.getElementById("sm-delete-btn").style.display = "inline-flex";

  document.getElementById("sm-execute-result").style.display = "none";
  _loadAgentOptions();
  loadEntityTagsInModal("script", s.id, "sm-tags-container");
  _scriptDirty = false;
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
    // Refresh local cache and re-render list
    const updated = await apiFetch("/api/v2/scripts?limit=5000");
    allScripts = updated.scripts || updated || [];
    populateTacticDropdown();
    filterScripts();
    document.getElementById("scriptModalTitle").textContent = escHtml(payload.name);
    document.getElementById("sm-delete-btn").style.display = "inline-flex";
    _scriptDirty = false;
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
  const paw = document.getElementById("sm-agent-select").value;
  if (!paw) { alert("Select an agent first."); return; }
  const command = (document.getElementById("sm-command").value || "").trim();
  if (!command) { alert("Enter a command first."); return; }

  const resultEl = document.getElementById("sm-execute-result");
  const outputSec = document.getElementById("sm-output-section");
  const outputPre = document.getElementById("sm-output-pre");
  const outputStatus = document.getElementById("sm-output-status");

  resultEl.textContent = "Queuing...";
  resultEl.style.display = "inline";
  outputSec.style.display = "none";
  outputPre.textContent = "";

  try {
    let result;
    if (_currentScriptId && _scriptDirty) {
      // Saved script with unsaved changes - prompt to save first
      if (!confirm("Script has unsaved changes. Save now before executing?")) return;
      await saveScriptFromModal();
      if (!_currentScriptId) return;
    }
    if (_currentScriptId) {
      // Saved script - use its stored command/cleanup
      result = await apiFetch(`/api/v2/scripts/${_currentScriptId}/execute`, {
        method: "POST",
        body: JSON.stringify({ paw }),
      });
    } else {
      // New Script modal - run ad-hoc without saving
      const executor = document.getElementById("sm-executor").value || "powershell";
      const cleanup = (document.getElementById("sm-cleanup").value || "").trim();
      result = await apiFetch("/api/v2/scripts/execute-adhoc", {
        method: "POST",
        body: JSON.stringify({ command, cleanup_command: cleanup, executor, paw }),
      });
    }
    if (!result.queued) {
      resultEl.textContent = "[WARN] Unexpected response.";
      return;
    }
    resultEl.textContent = `[OK] Job queued (${result.job_id.slice(0, 8)}...)`;
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

async function resetConsoleSession(paw) {
  try {
    const r = await fetch(`${API_BASE}/api/v2/console/session/${encodeURIComponent(paw)}?key=${encodeURIComponent(API_KEY)}`, { method: "DELETE" });
    const j = await r.json();
    console.log("[CONSOLE] Reset", paw, j.action);
  } catch (err) {
    console.warn("[CONSOLE] Reset failed:", err.message);
  }
}

async function resetAndRelaunchConsole(paw) {
  // Show feedback in the agent row
  const row = document.getElementById(`agent-row-${paw}`);
  const setStatus = (msg, color) => {
    if (!row) return;
    let el = row.querySelector(".native-console-status");
    if (!el) {
      el = document.createElement("span");
      el.className = "native-console-status";
      el.style.cssText = "margin-left:8px;font-size:11px;font-style:italic;";
      const td = row.querySelector("td:nth-child(10)");
      if (td) td.appendChild(el);
    }
    el.textContent = msg;
    el.style.color = color || "var(--text-muted)";
  };
  setStatus("resetting...", "#e08030");
  await resetConsoleSession(paw);
  setStatus("relaunching...", "var(--accent-color)");
  await openNativeConsole(paw);
}

async function openNativeConsole(paw) {
  // Show inline status next to the button while launching
  const row = document.getElementById(`agent-row-${paw}`);
  const statusSpan = row ? row.querySelector(".native-console-status") : null;
  const setStatus = (msg, color) => {
    if (!row) return;
    let el = row.querySelector(".native-console-status");
    if (!el) {
      el = document.createElement("span");
      el.className = "native-console-status";
      el.style.cssText = "margin-left:8px;font-size:11px;font-style:italic;";
      const td = row.querySelector("td:nth-child(10)");
      if (td) td.appendChild(el);
    }
    el.textContent = msg;
    el.style.color = color || "var(--text-muted)";
  };
  setStatus("launching...", "var(--accent-color)");
  try {
    const r = await fetch(`${API_BASE}/api/v2/console/native/${encodeURIComponent(paw)}?key=${encodeURIComponent(API_KEY)}`, { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    setStatus(`shell opening for ${j.hostname}`, "#6bcb77");
    setTimeout(() => setStatus(""), 5000);
  } catch (err) {
    setStatus("[ERROR] " + err.message, "#e53e3e");
    console.error("[CONSOLE] Native launch failed:", err.message);
  }
}

async function openConsole(paw, label) {
  // Auto-reset any stale session before opening a fresh one
  await resetConsoleSession(paw);
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

  // Focus the terminal. openConsole() is async so a direct focus() call may be
  // blocked by the browser (not a user-gesture frame). Use setTimeout to escape
  // the async chain and get a reliable focus.
  setTimeout(() => { if (_consoleTerm) _consoleTerm.focus(); }, 50);

  // Re-focus whenever the user clicks anywhere inside the terminal container
  container.addEventListener("mousedown", () => { if (_consoleTerm) _consoleTerm.focus(); });

  _consoleTerm.onData((data) => {
    if (_consoleWS && _consoleWS.readyState === WebSocket.OPEN) _consoleWS.send(data);
  });

  const proto = API_BASE.startsWith("https") ? "wss" : "ws";
  const wsURL = `${proto}://${window.location.host}/api/v2/console/ws/${encodeURIComponent(paw)}?key=${encodeURIComponent(API_KEY)}`;
  _consoleWS = new WebSocket(wsURL);

  _consoleWS.onopen = () => {
    document.getElementById("consoleStatus").textContent = "Connected";
    setTimeout(() => { if (_consoleTerm) _consoleTerm.focus(); }, 50);
  };
  _consoleWS.onmessage = (evt) => { _consoleTerm.write(evt.data); };
  _consoleWS.onerror = () => { document.getElementById("consoleStatus").textContent = "Error"; _consoleTerm.write("\r\n[ERROR] WebSocket error.\r\n"); };
  _consoleWS.onclose = () => { document.getElementById("consoleStatus").textContent = "Disconnected"; if (_consoleTerm) _consoleTerm.write("\r\n[CONSOLE] Session closed.\r\n"); };

  window.addEventListener("resize", _consoleResize);
}

function _consoleResize() { if (_consoleFitAddon) { try { _consoleFitAddon.fit(); } catch (_) {} } }

// Relay keystrokes that land on the modal backdrop to the terminal.
// This handles the edge case where the browser gave focus to the backdrop div.
function _consoleModalKeydown(e) {
  if (!_consoleTerm) return;
  // If already inside the xterm textarea just let it pass through
  if (e.target && e.target.classList && e.target.classList.contains("xterm-helper-textarea")) return;
  _consoleTerm.focus();
}

function closeConsole() {
  if (_consoleWS) { _consoleWS.close(); _consoleWS = null; }
  if (_consoleTerm) { _consoleTerm.dispose(); _consoleTerm = null; }
  window.removeEventListener("resize", _consoleResize);
  document.getElementById("consoleModal").classList.add("hidden");
}

document.addEventListener("keydown", (e) => {
  const modal = document.getElementById("consoleModal");
  if (modal && !modal.classList.contains("hidden")) {
    if (e.key === "Escape") { closeConsole(); return; }
    // If focus escaped the terminal (e.g. user clicked modal backdrop), recapture it.
    // Check active element is not already inside the xterm helper textarea.
    const active = document.activeElement;
    const inTerminal = active && (active.classList.contains("xterm-helper-textarea") || modal.contains(active));
    if (!inTerminal && _consoleTerm) {
      _consoleTerm.focus();
    }
  }
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



// ─── Chains ───────────────────────────────────────────────────────────────────

// ── List view ─────────────────────────────────────────────────────────────────

async function loadChains() {
  document.getElementById("chain-list-view").style.display  = "";
  document.getElementById("chain-editor-view").style.display = "none";

  const tbody = document.getElementById("chainListBody");
  tbody.innerHTML = `<tr><td colspan="5" class="empty-row">Loading...</td></tr>`;
  try {
    _allChains = await apiFetch("/api/v2/chains");
    _renderChainList();
    loadChainExecutionsList();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">Error: ${escHtml(err.message)}</td></tr>`;
  }
}

function _renderChainList() {
  const tbody = document.getElementById("chainListBody");
  if (!_allChains.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">No chains yet. Click "+ New Chain" to build one.</td></tr>`;
    return;
  }
  tbody.innerHTML = _allChains.map((c) => {
    const nodeCount = (c.flow && c.flow.nodes) ? c.flow.nodes.length : 0;
    const updated   = c.updated_at ? c.updated_at.slice(0, 16).replace("T", " ") : "-";
    return `<tr>
      <td><strong>${escHtml(c.name)}</strong></td>
      <td style="color:var(--text-secondary)">${escHtml(c.description || "-")}</td>
      <td>${nodeCount}</td>
      <td style="font-size:12px;color:var(--text-muted)">${escHtml(updated)}</td>
      <td style="white-space:nowrap">
        <button class="btn-open" onclick="editChain('${escHtml(c.id)}')">Open</button>
        <button class="btn btn-primary btn-sm" style="margin-left:4px" onclick="quickExecuteChain('${escHtml(c.id)}')">Execute</button>
        <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="duplicateChain('${escHtml(c.id)}')">Duplicate</button>
        <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteChain('${escHtml(c.id)}')">Delete</button>
      </td>
    </tr>`;
  }).join("");
}

async function loadChainExecutionsList() {
  const tbody = document.getElementById("chainExecsBody");
  try {
    const execs = await apiFetch("/api/v2/chains/executions");
    if (!execs.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No executions yet</td></tr>`;
      return;
    }
    tbody.innerHTML = execs.slice(0, 50).map((e) => {
      const started  = e.started_at  ? e.started_at.slice(0, 16).replace("T", " ")  : "-";
      const finished = e.finished_at ? e.finished_at.slice(0, 16).replace("T", " ") : "-";
      const stateCls = e.state === "completed" ? "var(--success)" : e.state === "failed" ? "var(--danger)" : "var(--warning)";
      return `<tr>
        <td>${escHtml(e.chain_name || "-")}</td>
        <td style="font-size:12px">${escHtml(e.agent_paw || "-")} ${e.agent_hostname ? "(" + escHtml(e.agent_hostname) + ")" : ""}</td>
        <td><span style="color:${stateCls};font-weight:600">${escHtml(e.state)}</span></td>
        <td style="font-size:12px">${escHtml(started)}</td>
        <td style="font-size:12px">${escHtml(finished)}</td>
        <td><button class="btn-open" onclick="openChainExecLog('${escHtml(e.id)}')">Log</button></td>
      </tr>`;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">Error: ${escHtml(err.message)}</td></tr>`;
  }
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

function newChain() {
  _editingChain = { id: null, name: "New Chain", description: "", agent_paw: "", nodes: [] };
  _chainDirty = true;
  _openChainEditor();
}

async function editChain(id) {
  try {
    const c = await apiFetch(`/api/v2/chains/${id}`);
    _editingChain = {
      id:          c.id,
      name:        c.name,
      description: c.description || "",
      agent_paw:   c.agent_paw || "",
      nodes:       (c.flow && c.flow.nodes) ? c.flow.nodes : [],
    };
    _chainDirty = false;
    _openChainEditor();
  } catch (err) {
    alert("Could not load chain: " + err.message);
  }
}

function _openChainEditor() {
  document.getElementById("chain-list-view").style.display   = "none";
  document.getElementById("chain-editor-view").style.display = "";
  document.getElementById("chain-editor-title").textContent  = _editingChain.id ? _editingChain.name : "New Chain";
  document.getElementById("chain-name-input").value          = _editingChain.name;
  document.getElementById("chain-desc-input").value          = _editingChain.description;
  const execBtn = document.getElementById("chain-exec-btn");
  if (execBtn) execBtn.disabled = !_editingChain.id;
  // Populate agent selector
  const sel = document.getElementById("chain-agent-sel");
  if (sel) {
    sel.innerHTML = `<option value="">-- select agent --</option>`;
    apiFetch("/api/v2/agents").then((agents) => {
      (agents || []).forEach((a) => {
        const label = a.alias || a.host || a.hostname || a.paw;
        const status = a.status || "unknown";
        const opt = document.createElement("option");
        opt.value       = a.paw;
        opt.textContent = `${label} [${a.paw}] - ${status}`;
        if (a.paw === _editingChain.agent_paw) opt.selected = true;
        sel.appendChild(opt);
      });
    }).catch(() => {});
  }
  renderChainFlow();
}

function closeChainEditor() {
  document.getElementById("chain-editor-view").style.display = "none";
  document.getElementById("chain-list-view").style.display   = "";
}

async function saveChain() {
  const name      = (document.getElementById("chain-name-input").value || "").trim();
  const desc      = (document.getElementById("chain-desc-input").value || "").trim();
  const agentPaw  = (document.getElementById("chain-agent-sel").value || "").trim();
  if (!name) { alert("Chain name is required."); return; }

  _editingChain.name        = name;
  _editingChain.description = desc;
  _editingChain.agent_paw   = agentPaw;

  const body = { name, description: desc, agent_paw: agentPaw || null, flow: { nodes: _editingChain.nodes } };
  try {
    let saved;
    if (_editingChain.id) {
      saved = await apiFetch(`/api/v2/chains/${_editingChain.id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      saved = await apiFetch("/api/v2/chains", { method: "POST", body: JSON.stringify(body) });
    }
    _editingChain.id = saved.id;
    document.getElementById("chain-editor-title").textContent = saved.name;
    const execBtn = document.getElementById("chain-exec-btn");
    if (execBtn) execBtn.disabled = false;
    _chainDirty = false;
    alert("Chain saved.");
    loadChains();
    _openChainEditor(); // keep editor open and re-render
  } catch (err) {
    alert("Save failed: " + err.message);
  }
}

async function deleteChain(id) {
  const c = _allChains.find((x) => x.id === id);
  if (!confirm(`Delete chain "${c ? c.name : id}"? This cannot be undone.`)) return;
  try {
    await apiFetch(`/api/v2/chains/${id}`, { method: "DELETE" });
    _allChains = _allChains.filter((x) => x.id !== id);
    _renderChainList();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function deleteAllChains() {
  if (!confirm("Delete ALL chains? This cannot be undone.")) return;
  try {
    await apiFetch("/api/v2/chains", { method: "DELETE" });
    _allChains = [];
    _renderChainList();
    loadChainExecutionsList();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function clearChainExecutions() {
  if (!confirm("Clear the entire chain execution log? This cannot be undone.")) return;
  try {
    await apiFetch("/api/v2/chains/executions", { method: "DELETE" });
    loadChainExecutionsList();
  } catch (err) {
    alert("Clear failed: " + err.message);
  }
}

async function duplicateChain(id) {
  try {
    const full = await apiFetch(`/api/v2/chains/${id}`);
    const newName = _nextCopyName(full.name, _allChains.map((x) => x.name));
    await apiFetch("/api/v2/chains", {
      method: "POST",
      body: JSON.stringify({
        name: newName,
        description: full.description || "",
        agent_paw: full.agent_paw || null,
        flow: full.flow || { nodes: [] },
      }),
    });
    _allChains = await apiFetch("/api/v2/chains");
    _renderChainList();
  } catch (err) {
    alert("Duplicate failed: " + err.message);
  }
}

function exportChainJSON() {
  if (!_editingChain.id) { alert("Save the chain first."); return; }
  const c = _allChains.find((x) => x.id === _editingChain.id);
  const data = c || { name: _editingChain.name, description: _editingChain.description, flow: { nodes: _editingChain.nodes } };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (data.name || "chain").replace(/\s+/g, "_") + ".json";
  a.click();
}

function importChainJSON() {
  const input = document.createElement("input");
  input.type   = "file";
  input.accept = ".json,application/json";
  input.onchange = async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const saved = await apiFetch("/api/v2/chains/import", { method: "POST", body: JSON.stringify(data) });
      _allChains.unshift(saved);
      _renderChainList();
      alert(`Imported: "${saved.name}"`);
    } catch (err) {
      alert("Import failed: " + err.message);
    }
  };
  input.click();
}

// ── Execute ───────────────────────────────────────────────────────────────────

async function executeChainFromEditor() {
  if (_chainDirty) {
    if (!confirm("Chain has unsaved changes. Save now before executing?")) return;
    await saveChain();
    if (!_editingChain.id) return;
  }
  if (!_editingChain.id) { alert("Save the chain first."); return; }
  const paw = (document.getElementById("chain-agent-sel").value || "").trim();
  if (!paw) { alert("Select a Default Agent before executing."); return; }
  if (!confirm(`Execute chain "${_editingChain.name}" on agent ${paw}?`)) return;
  try {
    const r = await apiFetch(`/api/v2/chains/${_editingChain.id}/execute`, {
      method: "POST",
      body: JSON.stringify({ agent_paw: paw }),
    });
    alert(`Chain execution started.\nExecution ID: ${r.execution_id}\n\nCheck the Executions list on the Chains page for the live log.`);
    loadChainExecutionsList();
  } catch (err) {
    alert("Execute failed: " + err.message);
  }
}

// ── Execution log modal ───────────────────────────────────────────────────────

async function openChainExecLog(execId) {
  document.getElementById("chainExecLogModal").classList.remove("hidden");
  document.getElementById("chainExecLogTitle").textContent = "Execution Log (loading...)";
  document.getElementById("chainExecLogBody").innerHTML    = `<p style="color:var(--text-muted)">Loading...</p>`;
  try {
    const data = await apiFetch(`/api/v2/chains/executions/${execId}/log`);
    const title = `${data.chain_name} | ${data.agent_paw} | ${data.state.toUpperCase()}`;
    document.getElementById("chainExecLogTitle").textContent = title;
    document.getElementById("chainExecLogBody").innerHTML = _renderExecLog(data);
  } catch (err) {
    document.getElementById("chainExecLogBody").innerHTML = `<p style="color:var(--danger)">Error: ${escHtml(err.message)}</p>`;
  }
}

function closeChainExecLog() {
  document.getElementById("chainExecLogModal").classList.add("hidden");
}

function _renderExecLog(data) {
  let html = `<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:16px;color:var(--text-secondary);font-size:13px">
    <span>Chain: <strong style="color:var(--text-primary)">${escHtml(data.chain_name)}</strong></span>
    <span>Agent: <strong style="color:var(--text-primary)">${escHtml(data.agent_paw)}</strong></span>
    <span>State: <strong style="color:${data.state === "completed" ? "var(--success)" : data.state === "failed" ? "var(--danger)" : "var(--warning)"}">${escHtml(data.state)}</strong></span>
    ${data.started_at  ? `<span>Started: ${escHtml(data.started_at.slice(0, 19).replace("T", " "))}</span>`  : ""}
    ${data.finished_at ? `<span>Finished: ${escHtml(data.finished_at.slice(0, 19).replace("T", " "))}</span>` : ""}
    ${data.error       ? `<span style="color:var(--danger)">Error: ${escHtml(data.error)}</span>`              : ""}
  </div>`;
  const steps = data.steps || [];
  if (!steps.length) {
    html += `<p style="color:var(--text-muted)">No steps recorded yet (chain may still be running).</p>`;
    return html;
  }
  steps.forEach((s, i) => {
    if (s.type === "if_else") {
      html += `<div class="exec-step step-ifelse">
        <div class="step-header">
          <span style="color:#f59e0b;font-weight:600">[IF/ELSE]</span>
          <span style="font-size:12px">contains: <code>${escHtml(s.contains || "(empty)")}</code></span>
          <span style="font-size:12px;color:${s.matched ? "var(--success)" : "var(--danger)"}">
            matched: ${s.matched ? "YES" : "NO"} &rarr; branch: <strong>${escHtml(s.branch_taken)}</strong>
          </span>
        </div>
        ${s.last_stdout_snippet ? `<div class="step-output">${escHtml(s.last_stdout_snippet)}</div>` : ""}
      </div>`;
    } else {
      const cls = s.state === "finished" ? "step-finished" : s.state === "failed" ? "step-failed" : "";
      html += `<div class="exec-step ${cls}">
        <div class="step-header">
          <span style="font-size:11px;color:var(--text-muted)">#${i + 1}</span>
          <span class="tcode">${escHtml(s.tcode || "?")}</span>
          <span style="font-weight:500">${escHtml(s.name || "?")}</span>
          <span style="color:${s.state === "finished" ? "var(--success)" : "var(--danger)"}">
            ${escHtml(s.state || "?")} (exit ${s.exit_code != null ? s.exit_code : "?"})
          </span>
        </div>
        ${(s.stdout || s.stderr) ? `<div class="step-output">${escHtml((s.stdout || "") + (s.stderr ? "\n--- stderr ---\n" + s.stderr : ""))}</div>` : ""}
      </div>`;
    }
  });
  return html;
}

// ── Flow renderer ─────────────────────────────────────────────────────────────

function renderChainFlow() {
  const container = document.getElementById("chain-flow");
  if (!container) return;
  container.innerHTML = _buildFlowHTML(_editingChain.nodes, "root", null);
}

function _buildFlowHTML(nodes, branch, ifElseId) {
  let html = "";

  // Start dot (only for root level)
  if (branch === "root") {
    html += `<div class="chain-start-dot" title="Start"></div>`;
  }

  // Add button before first node
  html += _addBtnHTML(branch, 0, ifElseId);

  nodes.forEach((node, idx) => {
    if (node.type === "if_else") {
      html += `<div class="chain-vline"></div>`;
      html += _renderIfElseNodeHTML(node, branch, ifElseId);
    } else {
      html += `<div class="chain-vline"></div>`;
      html += _renderScriptNodeHTML(node, branch, ifElseId);
    }
    // Add button after this node
    html += _addBtnHTML(branch, idx + 1, ifElseId);
  });

  return html;
}

function _renderScriptNodeHTML(node, branch, ifElseId) {
  const nid = escHtml(node.id);
  const br  = escHtml(branch);
  const iid = ifElseId ? escHtml(ifElseId) : "null";
  return `
    <div class="chain-script-node" id="cnode-${nid}">
      <div class="csn-tactic">${escHtml(node.tactic || "-")}</div>
      <div class="csn-tcode">${escHtml(node.tcode || "?")}</div>
      <div class="csn-name">${escHtml(node.script_name || "Unknown Script")}</div>
      <div class="csn-actions">
        <button class="btn btn-secondary btn-sm" onclick="replaceChainScript('${nid}','${br}','${iid}')">Open</button>
        <button class="btn btn-danger btn-sm"    onclick="removeChainNode('${nid}','${br}','${iid}')">Remove</button>
      </div>
    </div>`;
}

function _renderIfElseNodeHTML(node, branch, ifElseId) {
  const nid = escHtml(node.id);
  const br  = escHtml(branch);
  const iid = ifElseId ? escHtml(ifElseId) : "null";
  const containsVal = escHtml(node.contains || "");
  return `
    <div class="chain-ifelse-node" id="cnode-${nid}">
      <div class="cie-header">
        [IF/ELSE]
        <input type="text" class="cie-contains-input"
          placeholder="stdout contains..."
          value="${containsVal}"
          oninput="updateIfElseContains('${nid}', this.value)" />
        <button class="btn btn-danger btn-sm" style="margin-left:auto" onclick="removeChainNode('${nid}','${br}','${iid}')">Remove</button>
      </div>
      <div class="cie-hint">Branch taken when stdout of previous step CONTAINS the text above.</div>
    </div>
    <div class="chain-branches-row">
      <div class="chain-branch-col chain-branch-if">
        <div class="chain-vline"></div>
        <div class="chain-branch-label">IF TRUE</div>
        ${_buildFlowHTML(node.if_nodes || [], "if_nodes", node.id)}
      </div>
      <div class="chain-branch-col chain-branch-else">
        <div class="chain-vline"></div>
        <div class="chain-branch-label">ELSE</div>
        ${_buildFlowHTML(node.else_nodes || [], "else_nodes", node.id)}
      </div>
    </div>`;
}

function _addBtnHTML(branch, index, ifElseId) {
  const br  = escHtml(branch);
  const iid = ifElseId ? escHtml(ifElseId) : "null";
  return `<div class="chain-add-btn"
    onclick="openChainAddMenu(event,'${br}',${index},'${iid}')"
    title="Add node">+</div>`;
}

// ── Add-node popup menu ───────────────────────────────────────────────────────

function openChainAddMenu(event, branch, index, ifElseIdStr) {
  const ifElseId = (ifElseIdStr === "null") ? null : ifElseIdStr;
  _chainAddMenuCtx = { branch, index, ifElseId };

  const menu = document.getElementById("chainAddMenu");
  menu.classList.remove("hidden");
  menu.style.left = (event.clientX + 8) + "px";
  menu.style.top  = (event.clientY + 8) + "px";

  // Close on outside click
  setTimeout(() => {
    document.addEventListener("click", _closeChainAddMenuIfOutside, { once: true });
  }, 50);
}

function _closeChainAddMenuIfOutside(ev) {
  const menu = document.getElementById("chainAddMenu");
  if (!menu.contains(ev.target)) closeChainAddMenu();
}

function closeChainAddMenu() {
  document.getElementById("chainAddMenu").classList.add("hidden");
  _chainAddMenuCtx = null;
}

function chainMenuAddScript() {
  const ctx = _chainAddMenuCtx; // save BEFORE close (close nulls it)
  closeChainAddMenu();
  if (!ctx) return;
  _chainPickerCtx = { type: "insert", ...ctx };
  _openChainScriptPicker();
}

function chainMenuAddIfElse() {
  const ctx = _chainAddMenuCtx; // save BEFORE close (close nulls it)
  closeChainAddMenu();
  if (!ctx) return;
  const { branch, index, ifElseId } = ctx;
  const node = {
    id:         _genNodeId(),
    type:       "if_else",
    contains:   "",
    if_nodes:   [],
    else_nodes: [],
  };
  _insertNodeAt(_editingChain.nodes, node, branch, index, ifElseId);
  _chainDirty = true;
  renderChainFlow();
}

// ── Script picker (re-uses allScripts) ───────────────────────────────────────

function _openChainScriptPicker() {
  // Ensure scripts are loaded
  if (!allScripts.length) {
    apiFetch("/api/v2/scripts").then((scripts) => {
      allScripts = scripts;
      populateTacticDropdown();
      _populateCspTacticDropdown();
      _renderCspTable(allScripts);
    }).catch(() => _renderCspTable([]));
  } else {
    _populateCspTacticDropdown();
    _renderCspTable(allScripts);
  }
  document.getElementById("csp-search").value   = "";
  document.getElementById("csp-executor").value = "";
  document.getElementById("csp-platform").value = "";
  document.getElementById("chainScriptPickerModal").classList.remove("hidden");
}

function closeChainScriptPicker() {
  document.getElementById("chainScriptPickerModal").classList.add("hidden");
  _chainPickerCtx = null;
}

function _populateCspTacticDropdown() {
  const sel = document.getElementById("csp-tactic");
  if (!sel) return;
  const tactics = [...new Set(allScripts.map((s) => s.tactic).filter(Boolean))].sort();
  sel.innerHTML = `<option value="">All tactics</option>` +
    tactics.map((t) => `<option value="${escHtml(t)}">${escHtml(t)}</option>`).join("");
}

function filterCsp() {
  const q    = (document.getElementById("csp-search").value || "").toLowerCase();
  const tac  = document.getElementById("csp-tactic").value;
  const exec = document.getElementById("csp-executor").value;
  const plat = document.getElementById("csp-platform").value;
  const filtered = allScripts.filter((s) => {
    const mq = !q    || (s.tcode || "").toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q);
    const mt = !tac  || s.tactic   === tac;
    const me = !exec || s.executor === exec;
    const mp = !plat || (s.platform || "all").includes(plat) || s.platform === "all";
    return mq && mt && me && mp;
  });
  _renderCspTable(filtered);
}

function _renderCspTable(scripts) {
  const tbody = document.getElementById("cspTableBody");
  if (!tbody) return;
  if (!scripts.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No scripts match the filter.</td></tr>`;
    return;
  }
  tbody.innerHTML = scripts.slice(0, 400).map((s) => `
    <tr>
      <td><span class="tcode">${escHtml(s.tcode || "?")}</span></td>
      <td>${escHtml(s.name || "?")}</td>
      <td>${escHtml(s.tactic || "-")}</td>
      <td><code>${escHtml(s.executor || "?")}</code></td>
      <td>${escHtml(s.platform || "all")}</td>
      <td><button class="btn btn-primary btn-sm" onclick="chainPickScript('${escHtml(s.id)}')">Insert</button></td>
    </tr>`).join("");
}

function chainPickScript(scriptId) {
  const s = allScripts.find((x) => x.id === scriptId);
  if (!s || !_chainPickerCtx) return;
  const ctx = _chainPickerCtx; // save BEFORE closeChainScriptPicker nulls it
  closeChainScriptPicker();

  if (ctx.type === "replace") {
    // Replace the node already in the tree
    _walkAndReplace(_editingChain.nodes, ctx.nodeId, s);
  } else {
    // Insert new node at position
    const { branch, index, ifElseId } = ctx;
    const node = {
      id:          _genNodeId(),
      type:        "script",
      script_id:   s.id,
      script_name: s.name,
      tcode:       s.tcode,
      tactic:      s.tactic,
    };
    _insertNodeAt(_editingChain.nodes, node, branch, index, ifElseId);
  }
  _chainDirty = true;
  renderChainFlow();
}

function replaceChainScript(nodeId, branch, ifElseIdStr) {
  const ifElseId = (ifElseIdStr === "null") ? null : ifElseIdStr;
  _chainPickerCtx = { type: "replace", nodeId, branch, ifElseId };
  _openChainScriptPicker();
}

// ── Remove node ───────────────────────────────────────────────────────────────

function removeChainNode(nodeId, branch, ifElseIdStr) {
  if (!confirm("WARNING: This will remove the selected node AND all nodes that follow it in this branch.\nThis action cannot be undone.\n\nContinue?")) return;
  const ifElseId = (ifElseIdStr === "null") ? null : ifElseIdStr;
  _walkAndRemove(_editingChain.nodes, nodeId, branch, ifElseId);
  _chainDirty = true;
  renderChainFlow();
}

// ── If/Else contains field ────────────────────────────────────────────────────

function updateIfElseContains(nodeId, value) {
  _walkAndUpdateContains(_editingChain.nodes, nodeId, value);
}

// ── Internal tree helpers ─────────────────────────────────────────────────────

function _genNodeId() {
  return "n" + Math.random().toString(36).slice(2, 9);
}

/**
 * Insert a node into the right place in the tree.
 * - branch = "root"       -> top-level nodes array
 * - branch = "if_nodes"   -> if_nodes of the if/else with ifElseId
 * - branch = "else_nodes" -> else_nodes of the if/else with ifElseId
 */
function _insertNodeAt(nodes, newNode, branch, index, ifElseId) {
  if (!ifElseId || branch === "root") {
    nodes.splice(index, 0, newNode);
    return true;
  }
  for (const n of nodes) {
    if (n.type === "if_else") {
      if (n.id === ifElseId) {
        const arr = n[branch] || [];
        arr.splice(index, 0, newNode);
        n[branch] = arr;
        return true;
      }
      // recurse into sub-branches
      if (_insertNodeAt(n.if_nodes   || [], newNode, branch, index, ifElseId)) return true;
      if (_insertNodeAt(n.else_nodes || [], newNode, branch, index, ifElseId)) return true;
    }
  }
  return false;
}

/**
 * Remove node with nodeId and all nodes AFTER it in its branch (truncation),
 * from the given branch context.  Simple approach: find the node, truncate
 * the array from that index onwards.
 */
function _walkAndRemove(nodes, nodeId, branch, ifElseId) {
  // Try in root / current list
  const idx = nodes.findIndex((n) => n.id === nodeId);
  if (idx !== -1) {
    nodes.splice(idx); // remove node + all following in this branch
    return true;
  }
  // Recurse into if/else sub-branches
  for (const n of nodes) {
    if (n.type === "if_else") {
      if (_walkAndRemove(n.if_nodes   || [], nodeId, "if_nodes",   n.id)) return true;
      if (_walkAndRemove(n.else_nodes || [], nodeId, "else_nodes", n.id)) return true;
    }
  }
  return false;
}

/**
 * Replace the script details of an existing script node.
 */
function _walkAndReplace(nodes, nodeId, scriptObj) {
  for (const n of nodes) {
    if (n.id === nodeId && n.type === "script") {
      n.script_id   = scriptObj.id;
      n.script_name = scriptObj.name;
      n.tcode       = scriptObj.tcode;
      n.tactic      = scriptObj.tactic;
      return true;
    }
    if (n.type === "if_else") {
      if (_walkAndReplace(n.if_nodes   || [], nodeId, scriptObj)) return true;
      if (_walkAndReplace(n.else_nodes || [], nodeId, scriptObj)) return true;
    }
  }
  return false;
}

/**
 * Update the 'contains' field of an if/else node.
 */
function _walkAndUpdateContains(nodes, nodeId, value) {
  for (const n of nodes) {
    if (n.id === nodeId && n.type === "if_else") {
      n.contains = value;
      return true;
    }
    if (n.type === "if_else") {
      if (_walkAndUpdateContains(n.if_nodes   || [], nodeId, value)) return true;
      if (_walkAndUpdateContains(n.else_nodes || [], nodeId, value)) return true;
    }
  }
  return false;
}

// ═══════════════════════════════════════════════════════════════════════════════
// CAMPAIGNS
// ═══════════════════════════════════════════════════════════════════════════════

// ── List & CRUD ───────────────────────────────────────────────────────────────

async function loadCampaigns() {
  document.getElementById("campaign-list-view").style.display  = "";
  document.getElementById("campaign-editor-view").style.display = "none";

  const tbody = document.getElementById("campaignListBody");
  tbody.innerHTML = `<tr><td colspan="5" class="empty-row">Loading...</td></tr>`;
  try {
    const campaigns = await apiFetch("/api/v2/campaigns");
    _renderCampaignList(campaigns);
    loadCampaignExecutionsList();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">Error: ${escHtml(err.message)}</td></tr>`;
  }
}

function _renderCampaignList(campaigns) {
  _allCampaigns = campaigns;
  const tbody = document.getElementById("campaignListBody");
  if (!campaigns.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">No campaigns yet. Click "+ New Campaign" to build one.</td></tr>`;
    return;
  }
  tbody.innerHTML = campaigns.map((c) => {
    const updated = c.updated_at ? c.updated_at.slice(0, 16).replace("T", " ") : "-";
    return `<tr>
      <td><strong>${escHtml(c.name)}</strong></td>
      <td style="color:var(--text-secondary)">${escHtml(c.description || "-")}</td>
      <td>${c.node_count || 0}</td>
      <td style="font-size:12px;color:var(--text-muted)">${escHtml(updated)}</td>
      <td style="white-space:nowrap">
        <button class="btn-open" onclick="editCampaign('${escHtml(c.id)}')">Open</button>
        <button class="btn btn-primary btn-sm" style="margin-left:4px" onclick="quickExecuteCampaign('${escHtml(c.id)}')">Execute</button>
        <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="duplicateCampaign('${escHtml(c.id)}')">Duplicate</button>
        <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteCampaign('${escHtml(c.id)}')">Delete</button>
      </td>
    </tr>`;
  }).join("");
}

async function loadCampaignExecutionsList() {
  const tbody = document.getElementById("campaignExecsBody");
  try {
    const execs = await apiFetch("/api/v2/campaigns/executions");
    if (!execs.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No executions yet</td></tr>`;
      return;
    }
    tbody.innerHTML = execs.slice(0, 50).map((e) => {
      const started  = e.started_at  ? e.started_at.slice(0, 16).replace("T", " ")  : "-";
      const finished = e.finished_at ? e.finished_at.slice(0, 16).replace("T", " ") : "-";
      const stateCls = e.state === "completed" ? "var(--success)" : e.state === "failed" ? "var(--danger)" : "var(--warning)";
      return `<tr>
        <td>${escHtml(e.campaign_name || "-")}</td>
        <td style="font-size:12px">${escHtml(e.agent_paw || "-")} ${e.agent_hostname ? "(" + escHtml(e.agent_hostname) + ")" : ""}</td>
        <td><span style="color:${stateCls};font-weight:600">${escHtml(e.state)}</span></td>
        <td style="font-size:12px">${escHtml(started)}</td>
        <td style="font-size:12px">${escHtml(finished)}</td>
        <td><button class="btn-open" onclick="openCampExecLog('${escHtml(e.id)}')">Log</button></td>
      </tr>`;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">Error: ${escHtml(err.message)}</td></tr>`;
  }
}

async function openCampExecLog(execId) {
  try {
    const e = await apiFetch(`/api/v2/campaigns/executions/${execId}/log`);
    document.getElementById("campExecLogTitle").textContent = `Log: ${e.campaign_name || execId.slice(0, 8)}`;
    document.getElementById("campExecLogBody").innerHTML = _buildCampExecLogHTML(e.step_logs || []);
    document.getElementById("campExecLogModal").classList.remove("hidden");
  } catch (err) {
    alert("Could not load log: " + err.message);
  }
}

function closeCampExecLog() {
  document.getElementById("campExecLogModal").classList.add("hidden");
}

function _buildCampExecLogHTML(steps) {
  if (!steps.length) return `<div style="color:var(--text-muted)">No steps recorded.</div>`;
  let html = "";
  steps.forEach((s) => {
    if (s.type === "chain") {
      const cls = s.state === "completed" ? "step-finished" : "step-failed";
      html += `<div class="exec-step ${cls}">
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600">
          <span class="tcode">CHAIN</span>
          <span>${escHtml(s.chain_name || s.chain_id || "?")}</span>
          <span style="color:${s.state === "completed" ? "var(--success)" : "var(--danger)"}">${escHtml(s.state)}</span>
        </div>
        ${s.error ? `<div style="color:var(--danger);font-size:11px;margin-top:4px">${escHtml(s.error)}</div>` : ""}
        ${(s.steps || []).map((st) => `
          <div style="margin-top:6px;padding-left:12px;border-left:2px solid var(--border)">
            <div style="font-size:11px;color:var(--text-muted)">${escHtml(st.name || st.tcode || "step")}</div>
            <div style="font-size:11px">${escHtml(st.state || "")} ${st.exit_code != null ? "(exit " + st.exit_code + ")" : ""}</div>
          </div>`).join("")}
      </div>`;
    } else if (s.type === "parallel") {
      const cls = s.state === "completed" ? "step-finished" : s.state === "partial" ? "step-partial" : "step-failed";
      html += `<div class="exec-step ${cls}">
        <div style="font-size:12px;font-weight:600;color:var(--accent)">[PARALLEL] ${escHtml(s.state)}</div>
        ${(s.branches || []).map((b, i) => `
          <div style="margin-top:8px;padding-left:12px;border-left:2px solid var(--border)">
            <div style="font-size:11px;font-weight:600;color:var(--text-muted)">Branch ${i + 1}: ${escHtml(b.state || "")}</div>
            ${(b.steps || []).map((st) => `<div style="font-size:11px;padding-left:8px">${escHtml(st.chain_name || "chain")} &mdash; ${escHtml(st.state || "")}</div>`).join("")}
          </div>`).join("")}
      </div>`;
    }
  });
  return html;
}

function newCampaign() {
  _editingCampaign = { id: null, name: "New Campaign", description: "", agent_paw: "", nodes: [] };
  _campaignDirty = true;
  _openCampaignEditor();
}

async function editCampaign(id) {
  try {
    const c = await apiFetch(`/api/v2/campaigns/${id}`);
    _editingCampaign = {
      id:          c.id,
      name:        c.name,
      description: c.description || "",
      agent_paw:   c.agent_paw || "",
      nodes:       (c.flow && c.flow.nodes) ? c.flow.nodes : [],
    };
    _campaignDirty = false;
    _openCampaignEditor();
  } catch (err) {
    alert("Could not load campaign: " + err.message);
  }
}

async function _openCampaignEditor() {
  document.getElementById("campaign-list-view").style.display   = "none";
  document.getElementById("campaign-editor-view").style.display = "";
  document.getElementById("campaign-editor-title").textContent  = _editingCampaign.id ? _editingCampaign.name : "New Campaign";
  document.getElementById("camp-name-input").value  = _editingCampaign.name;
  document.getElementById("camp-desc-input").value  = _editingCampaign.description;
  const execBtn = document.getElementById("camp-exec-btn");
  if (execBtn) execBtn.disabled = !_editingCampaign.id;

  // Load agents for selector
  try {
    const agents = await apiFetch("/api/v2/agents");
    const sel = document.getElementById("camp-agent-sel");
    sel.innerHTML = `<option value="">-- select agent --</option>` +
      agents.map((a) => {
        const label = a.alias || a.host || a.hostname || a.paw;
        return `<option value="${escHtml(a.paw)}" ${a.paw === _editingCampaign.agent_paw ? "selected" : ""}>${escHtml(label)} [${escHtml(a.paw)}]</option>`;
      }).join("");
  } catch (e) { /* ignore */ }

  // Load chains for picker cache
  try {
    _campAllChains = await apiFetch("/api/v2/chains");
  } catch (e) { _campAllChains = []; }

  renderCampaignFlow();
}

async function saveCampaign() {
  const name    = document.getElementById("camp-name-input").value.trim();
  const desc    = document.getElementById("camp-desc-input").value.trim();
  const agePaw  = document.getElementById("camp-agent-sel").value;
  if (!name) { alert("Campaign name is required."); return; }

  _editingCampaign.name        = name;
  _editingCampaign.description = desc;
  _editingCampaign.agent_paw   = agePaw;

  const body = { name, description: desc, agent_paw: agePaw || null, flow_json: JSON.stringify({ nodes: _editingCampaign.nodes }) };
  try {
    let saved;
    if (_editingCampaign.id) {
      saved = await apiFetch(`/api/v2/campaigns/${_editingCampaign.id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      saved = await apiFetch("/api/v2/campaigns", { method: "POST", body: JSON.stringify(body) });
    }
    _editingCampaign.id = saved.id;
    document.getElementById("campaign-editor-title").textContent = saved.name;
    document.getElementById("camp-exec-btn").disabled = false;
    _campaignDirty = false;
    alert("Campaign saved.");
    loadCampaigns();
  } catch (err) {
    alert("Save failed: " + err.message);
  }
}

async function deleteCampaign(id) {
  if (!confirm("Delete this campaign? This cannot be undone.")) return;
  try {
    await apiFetch(`/api/v2/campaigns/${id}`, { method: "DELETE" });
    loadCampaigns();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function clearCampaignExecutions() {
  if (!confirm("Clear the entire campaign execution log? This cannot be undone.")) return;
  try {
    await apiFetch("/api/v2/campaigns/executions", { method: "DELETE" });
    loadCampaignExecutionsList();
  } catch (err) {
    alert("Clear failed: " + err.message);
  }
}

async function duplicateCampaign(id) {
  try {
    const [full, allCampaigns] = await Promise.all([
      apiFetch(`/api/v2/campaigns/${id}`),
      apiFetch("/api/v2/campaigns"),
    ]);
    const newName = _nextCopyName(full.name, allCampaigns.map((x) => x.name));
    await apiFetch("/api/v2/campaigns", {
      method: "POST",
      body: JSON.stringify({
        name: newName,
        description: full.description || "",
        agent_paw: full.agent_paw || null,
        flow_json: full.flow_json || '{"nodes":[]}',
      }),
    });
    loadCampaigns();
  } catch (err) {
    alert("Duplicate failed: " + err.message);
  }
}

function closeCampaignEditor() {
  loadCampaigns();
}

async function executeCampaignFromEditor() {
  if (_campaignDirty) {
    if (!confirm("Campaign has unsaved changes. Save now before executing?")) return;
    await saveCampaign();
    if (!_editingCampaign.id) return;
  }
  if (!_editingCampaign.id) { alert("Save the campaign first."); return; }
  const agentPaw = document.getElementById("camp-agent-sel").value;
  if (!agentPaw) { alert("Select an agent before executing."); return; }
  const c = _editingCampaign;
  if (!confirm(`Execute campaign "${escHtml(c.name)}" on agent ${escHtml(agentPaw)}?`)) return;
  try {
    const r = await apiFetch(`/api/v2/campaigns/${c.id}/execute`, {
      method: "POST",
      body: JSON.stringify({ agent_paw: agentPaw }),
    });
    alert(`Campaign execution started.\nExecution ID: ${r.execution_id}`);
  } catch (err) {
    alert("Execute failed: " + err.message);
  }
}

// ── Quick Execute from list (Scripts / Chains / Campaigns) ──────────────────

let _qeType = null;  // "script" | "chain" | "campaign"
let _qeId   = null;

async function _showQuickExecModal(type, id) {
  _qeType = type;
  _qeId   = id;
  const entry = type === "script"
    ? allScripts.find((s) => String(s.id) === String(id))
    : type === "chain"
      ? _allChains.find((x) => x.id === id)
      : _allCampaigns.find((x) => x.id === id);
  document.getElementById("qe-title").textContent = "Execute: " + ((entry || {}).name || id);
  const sel = document.getElementById("qe-agent-sel");
  sel.innerHTML = '<option value="">Loading agents...</option>';
  const btn = document.getElementById("qe-run-btn");
  btn.disabled    = false;
  btn.textContent = "Execute";
  document.getElementById("quickExecModal").classList.remove("hidden");
  try {
    const agents = await apiFetch("/api/v2/agents");
    const list = agents.agents || agents || [];
    if (!list.length) {
      sel.innerHTML = '<option value="">No agents registered</option>';
      return;
    }
    sel.innerHTML = '<option value="">Select agent...</option>' +
      list.map((a) => {
        const host  = a.host || a.hostname || "";
        const label = a.alias ? a.alias + "  (" + host + ")  [" + a.paw + "]" : host + "  [" + a.paw + "]";
        return '<option value="' + escHtml(a.paw) + '">' + escHtml(label) + '</option>';
      }).join("");
  } catch (err) {
    sel.innerHTML = '<option value="">Error loading agents</option>';
  }
}

function closeQuickExecModal() {
  document.getElementById("quickExecModal").classList.add("hidden");
  _qeType = null;
  _qeId   = null;
}

async function _quickExecRun() {
  const paw = document.getElementById("qe-agent-sel").value;
  if (!paw) { alert("Select an agent first."); return; }
  const btn = document.getElementById("qe-run-btn");
  btn.disabled    = true;
  btn.textContent = "Running...";
  try {
    const execType = _qeType;  // capture before closeQuickExecModal() nulls _qeType
    let endpoint, body;
    if (execType === "script") {
      endpoint = "/api/v2/scripts/" + _qeId + "/execute";
      body = { paw };
    } else if (execType === "chain") {
      endpoint = "/api/v2/chains/" + _qeId + "/execute";
      body = { agent_paw: paw };
    } else {
      endpoint = "/api/v2/campaigns/" + _qeId + "/execute";
      body = { agent_paw: paw };
    }
    const r = await apiFetch(endpoint, { method: "POST", body: JSON.stringify(body) });
    closeQuickExecModal();
    if (execType === "script") {
      alert("[OK] Job queued.\nJob ID: " + (r.job_id ? r.job_id.slice(0, 8) + "..." : "-"));
    } else if (execType === "chain") {
      alert("Chain execution started.\nExecution ID: " + r.execution_id + "\n\nCheck the Executions list on the Chains page.");
      loadChainExecutionsList();
    } else {
      alert("Campaign execution started.\nExecution ID: " + r.execution_id);
    }
  } catch (err) {
    alert("[ERROR] " + err.message);
  } finally {
    btn.disabled    = false;
    btn.textContent = "Execute";
  }
}

function quickExecuteScript(id)   { _showQuickExecModal("script",   id); }
function quickExecuteChain(id)    { _showQuickExecModal("chain",    id); }
function quickExecuteCampaign(id) { _showQuickExecModal("campaign", id); }

function exportCampaignJSON() {
  const data = {
    name:        _editingCampaign.name,
    description: _editingCampaign.description,
    flow_json:   JSON.stringify({ nodes: _editingCampaign.nodes }),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${_editingCampaign.name.replace(/\s+/g, "_")}.campaign.json`;
  a.click();
}

async function importCampaignJSON() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json";
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const flow = typeof data.flow_json === "string" ? JSON.parse(data.flow_json) : (data.flow || { nodes: [] });
      const body = {
        name:        data.name || "Imported Campaign",
        description: data.description || "",
        flow_json:   JSON.stringify(flow),
      };
      const saved = await apiFetch("/api/v2/campaigns", { method: "POST", body: JSON.stringify(body) });
      alert(`Imported: ${saved.name}`);
      loadCampaigns();
    } catch (err) {
      alert("Import failed: " + err.message);
    }
  };
  input.click();
}

// ── Campaign flow renderer ────────────────────────────────────────────────────

function renderCampaignFlow() {
  const container = document.getElementById("campaign-flow");
  if (!container) return;
  container.innerHTML = _buildCampFlowHTML(_editingCampaign.nodes, "root", null);
}

function _buildCampFlowHTML(nodes, branch, parallelId) {
  let html = "";
  if (branch === "root") {
    html += `<div class="chain-start-dot" title="Start"></div>`;
  }
  html += _campAddBtnHTML(branch, 0, parallelId);

  nodes.forEach((node, idx) => {
    html += `<div class="chain-vline"></div>`;
    if (node.type === "parallel") {
      html += _renderParallelNodeHTML(node);
    } else {
      html += _renderCampChainNodeHTML(node, branch, parallelId);
    }
    html += _campAddBtnHTML(branch, idx + 1, parallelId);
  });
  return html;
}

function _renderCampChainNodeHTML(node, branch, parallelId) {
  const nid = escHtml(node.id);
  const br  = escHtml(branch);
  const pid = parallelId ? escHtml(parallelId) : "null";
  return `
    <div class="chain-script-node" id="cpnode-${nid}">
      <div class="csn-tactic" style="color:var(--accent)">CHAIN</div>
      <div class="csn-name">${escHtml(node.chain_name || "Unknown Chain")}</div>
      <div class="csn-actions">
        <button class="btn btn-secondary btn-sm" onclick="replaceCampChain('${nid}','${br}','${pid}')">Open</button>
        <button class="btn btn-danger btn-sm"    onclick="removeCampNode('${nid}','${br}','${pid}')">Remove</button>
      </div>
    </div>`;
}

function _renderParallelNodeHTML(node) {
  const nid = escHtml(node.id);
  let branchesHTML = "";
  (node.branches || []).forEach((bNodes, i) => {
    branchesHTML += `
      <div class="camp-branch-col">
        <div class="camp-branch-header">
          <span style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px">Branch ${i + 1}</span>
          <button class="btn btn-danger btn-sm" style="margin-left:auto;font-size:10px" onclick="removeCampParallelBranch('${nid}',${i})">Remove branch</button>
        </div>
        ${_buildCampFlowHTML(bNodes, "branch", nid + "_" + i)}
        <button class="btn btn-secondary btn-sm" style="margin-top:6px;font-size:11px" onclick="campParallelAddChain('${nid}',${i})">+ chain</button>
      </div>`;
  });
  return `
    <div class="camp-parallel-node" id="cpnode-${nid}">
      <div class="cpar-header">
        [PARALLEL]
        <button class="btn btn-secondary btn-sm" style="margin-left:auto" onclick="addCampParallelBranch('${nid}')">+ Branch</button>
        <button class="btn btn-danger btn-sm" onclick="removeCampNode('${nid}','root','null')">Remove</button>
      </div>
      <div class="camp-parallel-branches">${branchesHTML || '<div style="color:var(--text-muted);padding:12px;font-size:12px">No branches yet. Click "+ Branch".</div>'}</div>
    </div>`;
}

function _campAddBtnHTML(branch, index, parallelId) {
  const br  = escHtml(branch);
  const pid = parallelId ? escHtml(parallelId) : "null";
  return `<div class="chain-add-btn"
    onclick="openCampAddMenu(event,'${br}',${index},'${pid}')"
    title="Add node">+</div>`;
}

// ── Add-node popup ────────────────────────────────────────────────────────────

function openCampAddMenu(event, branch, index, parallelIdStr) {
  const parallelId = (parallelIdStr === "null") ? null : parallelIdStr;
  _campAddMenuCtx = { branch, index, parallelId };

  const menu = document.getElementById("campAddMenu");
  menu.classList.remove("hidden");
  menu.style.left = (event.clientX + 8) + "px";
  menu.style.top  = (event.clientY + 8) + "px";

  setTimeout(() => {
    document.addEventListener("click", _closeCampAddMenuIfOutside, { once: true });
  }, 50);
}

function _closeCampAddMenuIfOutside(ev) {
  const menu = document.getElementById("campAddMenu");
  if (!menu.contains(ev.target)) closeCampAddMenu();
}

function closeCampAddMenu() {
  document.getElementById("campAddMenu").classList.add("hidden");
  _campAddMenuCtx = null;
}

function campMenuAddChain() {
  const ctx = _campAddMenuCtx;
  closeCampAddMenu();
  if (!ctx) return;
  _campPickerCtx = { type: "insert", ...ctx };
  _openCampChainPicker();
}

function campMenuAddParallel() {
  const ctx = _campAddMenuCtx;
  closeCampAddMenu();
  if (!ctx) return;
  const node = {
    id:       _genNodeId(),
    type:     "parallel",
    branches: [[], []],
  };
  _campInsertNodeAt(_editingCampaign.nodes, node, ctx.branch, ctx.index, ctx.parallelId);
  _campaignDirty = true;
  renderCampaignFlow();
}

function addCampParallelBranch(parallelNodeId) {
  _campWalkAndModifyParallel(_editingCampaign.nodes, parallelNodeId, (node) => {
    node.branches.push([]);
  });
  _campaignDirty = true;
  renderCampaignFlow();
}

function removeCampParallelBranch(parallelNodeId, branchIdx) {
  if (!confirm("Remove this branch and all its chains?")) return;
  _campWalkAndModifyParallel(_editingCampaign.nodes, parallelNodeId, (node) => {
    node.branches.splice(branchIdx, 1);
  });
  _campaignDirty = true;
  renderCampaignFlow();
}

function campParallelAddChain(parallelNodeId, branchIdx) {
  _campPickerCtx = { type: "parallel_branch", parallelNodeId, branchIdx };
  _openCampChainPicker();
}

// ── Chain picker ──────────────────────────────────────────────────────────────

function _openCampChainPicker() {
  if (!_campAllChains.length) {
    apiFetch("/api/v2/chains").then((chains) => {
      _campAllChains = chains;
      _renderCcpTable(_campAllChains);
    }).catch(() => _renderCcpTable([]));
  } else {
    _renderCcpTable(_campAllChains);
  }
  document.getElementById("ccp-search").value = "";
  document.getElementById("campChainPickerModal").classList.remove("hidden");
}

function closeCampChainPicker() {
  document.getElementById("campChainPickerModal").classList.add("hidden");
  _campPickerCtx = null;
}

function filterCcp() {
  const q = (document.getElementById("ccp-search").value || "").toLowerCase();
  const filtered = _campAllChains.filter((c) => !q || (c.name || "").toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q));
  _renderCcpTable(filtered);
}

function _renderCcpTable(chains) {
  const tbody = document.getElementById("ccpTableBody");
  if (!tbody) return;
  if (!chains.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-row">No chains match.</td></tr>`;
    return;
  }
  tbody.innerHTML = chains.map((c) => `
    <tr>
      <td><strong>${escHtml(c.name || "?")}</strong></td>
      <td style="color:var(--text-secondary)">${escHtml(c.description || "-")}</td>
      <td>${c.node_count || 0}</td>
      <td><button class="btn btn-primary btn-sm" onclick="campPickChain('${escHtml(c.id)}')">Insert</button></td>
    </tr>`).join("");
}

function campPickChain(chainId) {
  const c = _campAllChains.find((x) => x.id === chainId);
  if (!c || !_campPickerCtx) return;
  const ctx = _campPickerCtx;
  closeCampChainPicker();

  const node = {
    id:         _genNodeId(),
    type:       "chain",
    chain_id:   c.id,
    chain_name: c.name,
  };

  if (ctx.type === "replace") {
    _campWalkAndReplace(_editingCampaign.nodes, ctx.nodeId, c);
  } else if (ctx.type === "parallel_branch") {
    _campWalkAndModifyParallel(_editingCampaign.nodes, ctx.parallelNodeId, (pNode) => {
      if (pNode.branches[ctx.branchIdx]) {
        pNode.branches[ctx.branchIdx].push(node);
      }
    });
  } else {
    _campInsertNodeAt(_editingCampaign.nodes, node, ctx.branch, ctx.index, ctx.parallelId);
  }
  _campaignDirty = true;
  renderCampaignFlow();
}

function replaceCampChain(nodeId, branch, parallelIdStr) {
  const parallelId = (parallelIdStr === "null") ? null : parallelIdStr;
  _campPickerCtx = { type: "replace", nodeId, branch, parallelId };
  _openCampChainPicker();
}

// ── Remove node ───────────────────────────────────────────────────────────────

function removeCampNode(nodeId, branch, parallelIdStr) {
  if (!confirm("Remove this node and all nodes that follow it in this branch?")) return;
  const parallelId = (parallelIdStr === "null") ? null : parallelIdStr;
  _campWalkAndRemove(_editingCampaign.nodes, nodeId, branch, parallelId);
  _campaignDirty = true;
  renderCampaignFlow();
}

// ── Tree helpers ──────────────────────────────────────────────────────────────

function _campInsertNodeAt(nodes, newNode, branch, index, parallelId) {
  // If no parallelId context, insert into the root nodes array at index
  if (!parallelId || parallelId === "null") {
    _editingCampaign.nodes.splice(index, 0, newNode);
    return true;
  }
  // parallelId format: "parallelNodeId_branchIdx"
  const lastUs = parallelId.lastIndexOf("_");
  const pNodeId  = parallelId.slice(0, lastUs);
  const branchIdx = parseInt(parallelId.slice(lastUs + 1), 10);
  return _campWalkAndModifyParallel(_editingCampaign.nodes, pNodeId, (pNode) => {
    if (pNode.branches[branchIdx]) {
      pNode.branches[branchIdx].splice(index, 0, newNode);
    }
  });
}

function _campWalkAndRemove(nodes, nodeId) {
  const idx = nodes.findIndex((n) => n.id === nodeId);
  if (idx !== -1) {
    nodes.splice(idx);
    return true;
  }
  for (const n of nodes) {
    if (n.type === "parallel") {
      for (const branchNodes of (n.branches || [])) {
        if (_campWalkAndRemove(branchNodes, nodeId)) return true;
      }
    }
  }
  return false;
}

function _campWalkAndReplace(nodes, nodeId, chainObj) {
  for (const n of nodes) {
    if (n.id === nodeId && n.type === "chain") {
      n.chain_id   = chainObj.id;
      n.chain_name = chainObj.name;
      return true;
    }
    if (n.type === "parallel") {
      for (const branchNodes of (n.branches || [])) {
        if (_campWalkAndReplace(branchNodes, nodeId, chainObj)) return true;
      }
    }
  }
  return false;
}

function _campWalkAndModifyParallel(nodes, parallelNodeId, fn) {
  for (const n of nodes) {
    if (n.type === "parallel" && n.id === parallelNodeId) {
      fn(n);
      return true;
    }
    if (n.type === "parallel") {
      for (const branchNodes of (n.branches || [])) {
        if (_campWalkAndModifyParallel(branchNodes, parallelNodeId, fn)) return true;
      }
    }
  }
  return false;
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

  // Unsaved-changes tracking: mark dirty on any input/change in each editor
  const smModal = document.getElementById("scriptModal");
  if (smModal) smModal.addEventListener("input", () => { _scriptDirty = true; });
  const chainEditor = document.getElementById("chain-editor-view");
  if (chainEditor) chainEditor.addEventListener("input", () => { _chainDirty = true; });
  const campEditor = document.getElementById("campaign-editor-view");
  if (campEditor) campEditor.addEventListener("input", () => { _campaignDirty = true; });
})();
