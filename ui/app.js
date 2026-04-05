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

// Auth state
let _currentUser = null;
let _cachedUsers  = [];
let _morganaJWT  = localStorage.getItem("morgana_jwt") || null;
let _editingUserId   = null;
let _editingUserTagIds = [];

// Verify JWT on startup; redirect to login if missing / expired
async function initAuth() {
  if (sessionStorage.getItem("morgana_pw_warning")) {
    sessionStorage.removeItem("morgana_pw_warning");
    setTimeout(() => {
      const el = document.getElementById("breakGlassBanner");
      if (el) el.style.display = "block";
    }, 500);
  }
  if (!_morganaJWT) { window.location.replace("/ui/login.html"); return; }
  try {
    const resp = await fetch(API_BASE + "/api/v2/auth/me", {
      headers: { "Authorization": "Bearer " + _morganaJWT },
    });
    if (!resp.ok) throw new Error("Unauthorized");
    _currentUser = await resp.json();
    if (_currentUser.default_password_warning) {
      const el = document.getElementById("breakGlassBanner");
      if (el) el.style.display = "block";
    }
  } catch (_) {
    localStorage.removeItem("morgana_jwt");
    window.location.replace("/ui/login.html");
  }
}

function logOut() {
  if (!confirm('Log out?')) return;
  localStorage.removeItem('morgana_jwt');
  localStorage.removeItem('morgana_api_key');
  _morganaJWT = null;
  _currentUser = null;
  window.location.replace('/ui/login.html');
}

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
    case "users":     loadUsers();           break;
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
      ...(_morganaJWT ? { "Authorization": "Bearer " + _morganaJWT } : {}),
      ...(options.headers || {}),
    },
  });
  if (resp.status === 401) {
    localStorage.removeItem("morgana_jwt");
    window.location.replace("/ui/login.html");
    throw new Error("Session expired");
  }
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
        <td style="white-space:nowrap"><span id="tags-agent-${escHtml(a.paw)}" style="display:inline-flex;flex-wrap:wrap;gap:2px;vertical-align:middle"></span> <button class="btn btn-secondary btn-sm" style="font-size:10px;padding:1px 5px;vertical-align:middle" onclick="openTagPicker('agent','${escHtml(a.paw)}')" title="Assign tags">+</button></td>
        <td><span class="version-badge" title="Agent version">${escHtml(a.agent_version || "?")}</span></td>
        <td style="white-space:nowrap">
          <button class="btn btn-secondary btn-sm" onclick="openNativeConsole('${escHtml(a.paw)}')" title="Open native terminal window connected to this agent">Console</button>
          <button class="console-reset-btn" onclick="resetAndRelaunchConsole('${escHtml(a.paw)}')" title="Kill current session and open a fresh console">Reset</button>
        </td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteAgent('${escHtml(a.paw)}')" title="Remove agent">x</button></td>
      </tr>`;
    }).join("");
    agents.forEach((a) => loadEntityTagsInline("agent", a.paw, `tags-agent-${a.paw}`));
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

// Cache last-known server info (populated by loadAdminStatus / showDeployToken)
let _serverInfo = { ip_address: null, dns_name: "", server_port: 8888 };

async function showDeployToken() {
  // Fetch fresh server info to get the correct IP/DNS for agent one-liners
  try {
    const info = await apiFetch("/api/v2/admin/server-info");
    _serverInfo = info;
  } catch (err) {
    console.warn("[DEPLOY] Could not fetch server-info:", err.message);
  }

  let deployToken;
  try {
    const resp = await apiFetch("/api/v2/admin/deploy-token", { method: "POST" });
    deployToken = resp.deploy_token;
  } catch (err) {
    alert("[ERROR] Could not generate deploy token: " + err.message);
    return;
  }

  // Use DNS if configured, otherwise fall back to server IP, then browser hostname
  const host = (_serverInfo.dns_name && _serverInfo.dns_name.trim())
    ? _serverInfo.dns_name.trim()
    : (_serverInfo.ip_address || window.location.hostname);
  const port = _serverInfo.server_port || 8888;
  const origin = `http://${host}:${port}`;

  const d = "C:\\ProgramData\\Morgana\\agent";

  // Windows: true one-liner -- download binary then install NT service (run as Administrator)
  const winCmd =
    `$d='${d}';New-Item $d -Force -ItemType Directory|Out-Null;` +
    `(New-Object Net.WebClient).DownloadFile('${origin}/download/morgana-agent.exe',"$d\\morgana-agent.exe");` +
    `&"$d\\morgana-agent.exe" install --server ${origin} --token ${deployToken}`;

  // Linux: true one-liner -- download binary then install systemd service (run as root)
  const linCmd =
    `curl -sSL '${origin}/download/morgana-agent' -o /tmp/morgana-agent` +
    ` && chmod +x /tmp/morgana-agent` +
    ` && sudo /tmp/morgana-agent install --server ${origin} --token ${deployToken}`;

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
        source: "morgana",
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
    setVal("admin-custom-db", data.morgana_scripts_in_db ?? "-");
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

    // Load API keys table
    loadApiKeys();

    // Load server info (hostname, IP, DNS, memory, disk)
    loadServerInfo();

  } catch (err) {
    console.error("[ADMIN] Status load failed:", err.message);
  }
}

async function loadServerInfo() {
  try {
    const info = await apiFetch("/api/v2/admin/server-info");
    _serverInfo = info;
    setVal("sinfo-ip", info.ip_address || "-");
    setVal("sinfo-hostname", info.hostname || "-");
    setVal("sinfo-platform", (info.platform || "-") + (info.python_version ? " / Py " + info.python_version : ""));
    setVal("sinfo-port", info.server_port || "-");
    if (info.memory && info.memory.used_pct != null) {
      setVal("sinfo-mem-used", info.memory.used_pct + "%");
      setVal("sinfo-mem-avail", (info.memory.available_gb ?? "-") + " GB");
    } else {
      setVal("sinfo-mem-used", info.memory?.note || "-");
      setVal("sinfo-mem-avail", "-");
    }
    if (info.disk && info.disk.used_pct != null) {
      setVal("sinfo-disk-used", info.disk.used_pct + "%");
      setVal("sinfo-disk-free", (info.disk.free_gb ?? "-") + " GB");
    } else {
      setVal("sinfo-disk-used", info.disk?.error || "-");
      setVal("sinfo-disk-free", "-");
    }
    const dnsInput = document.getElementById("sinfodns");
    if (dnsInput) dnsInput.value = info.dns_name || "";
  } catch (err) {
    console.warn("[ADMIN] Server info load failed:", err.message);
  }
}

async function saveServerDns() {
  const val = (document.getElementById("sinfodns")?.value || "").trim();
  try {
    const updated = await apiFetch("/api/v2/admin/settings", {
      method: "PUT",
      body: JSON.stringify({ dns_name: val }),
    });
    _serverInfo.dns_name = updated.dns_name ?? val;
    const saved = document.getElementById("sinfoSaved");
    if (saved) { saved.style.display = "inline"; setTimeout(() => { saved.style.display = "none"; }, 2000); }
  } catch (err) {
    alert("Failed to save DNS: " + err.message);
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

// ─── API Key management ───────────────────────────────────────────────────────

let _revealedKey = "";

async function loadApiKeys() {
  const tbody = document.getElementById("apiKeysTableBody");
  if (!tbody) return;
  try {
    const rows = await apiFetch("/api/v2/api-keys");
    if (!rows || rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No keys yet. Click [+ New Key] to create one.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(k => `
      <tr>
        <td>${k.name}</td>
        <td><code style="font-size:.8rem;color:var(--accent-color)">${k.key_prefix}...</code></td>
        <td style="color:var(--text-muted);font-size:.82rem">${k.created_at}</td>
        <td><button class="btn btn-danger" style="padding:2px 10px;font-size:.78rem" onclick="deleteApiKey('${k.id}','${k.name.replace(/'/g,'&apos;')}')">Revoke</button></td>
      </tr>`).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-row">[ERROR] ${err.message}</td></tr>`;
  }
}

function _showNewKeyModal() {
  const inp = document.getElementById("newKeyNameInput");
  if (inp) inp.value = "";
  const btn = document.getElementById("newKeyCreateBtn");
  if (btn) { btn.disabled = false; btn.textContent = "Create"; }
  document.getElementById("newKeyModal").classList.remove("hidden");
  setTimeout(() => { if (inp) inp.focus(); }, 80);
}

function _closeNewKeyModal() {
  document.getElementById("newKeyModal").classList.add("hidden");
}

async function _createApiKeySubmit() {
  const name = (document.getElementById("newKeyNameInput").value || "").trim();
  if (!name) { alert("Enter a name for the key."); return; }
  const btn = document.getElementById("newKeyCreateBtn");
  btn.disabled = true; btn.textContent = "Creating...";
  try {
    const r = await apiFetch("/api/v2/api-keys", {
      method: "POST",
      body: JSON.stringify({ name })
    });
    _closeNewKeyModal();
    _showKeyRevealModal(r.key, r.name);
    loadApiKeys();
  } catch (err) {
    alert("[ERROR] " + err.message);
    btn.disabled = false; btn.textContent = "Create";
  }
}

function _showKeyRevealModal(key, name) {
  _revealedKey = key;
  const el = document.getElementById("revealKeyValue");
  if (el) el.textContent = key;
  document.getElementById("keyRevealModal").classList.remove("hidden");
}

function _closeKeyRevealModal() {
  _revealedKey = "";
  document.getElementById("keyRevealModal").classList.add("hidden");
}

function _copyRevealedKey() {
  if (!_revealedKey) return;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(_revealedKey).then(() => alert("[OK] Key copied to clipboard.")).catch(() => _copyFallback(_revealedKey));
  } else {
    _copyFallback(_revealedKey);
  }
}

function _useBrowserKey() {
  if (!_revealedKey) return;
  localStorage.setItem("morgana_api_key", _revealedKey);
  const inp = document.getElementById("apiKeyInput");
  if (inp) inp.value = _revealedKey;
  _closeKeyRevealModal();
  alert("[OK] Key saved as browser session key.\nReload the page to activate it for API calls.");
}

async function deleteApiKey(id, name) {
  if (!confirm(`Revoke key "${name}"?\n\nAny agent or tool using this key will stop working.`)) return;
  try {
    await apiFetch(`/api/v2/api-keys/${id}`, { method: "DELETE" });
    loadApiKeys();
  } catch (err) {
    alert("[ERROR] " + err.message);
  }
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
  setVal("sm-source", "morgana");
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
  _currentScriptIsAtomic = (s.source || "") === "atomic-red-team";

  document.getElementById("scriptModalTitle").textContent = escHtml(s.name || "Script");
  document.getElementById("sm-name").value = s.name || "";
  document.getElementById("sm-tcode").value = s.tcode || "";
  document.getElementById("sm-tactic").value = s.tactic || "";
  document.getElementById("sm-description").value = s.description || "";
  document.getElementById("sm-command").value = s.command || "";
  document.getElementById("sm-cleanup").value = s.cleanup_command || "";
  document.getElementById("sm-source").value = s.source || "morgana";
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
  _loadAgentOptions(s.target_agent_paw || "");
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
    target_agent_paw: document.getElementById("sm-agent-select").value || null,
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

async function _loadAgentOptions(selectedPaw) {
  const sel = document.getElementById("sm-agent-select");
  // Set special options immediately so combo shows correct value without waiting for agents
  sel.innerHTML =
    '<option value="">-- select target --</option>' +
    '<option value="__ALL__">Broadcast: all agents</option>' +
    '<option value="__TAGS__">Agents with this script\'s tags</option>';
  if (selectedPaw === "__ALL__" || selectedPaw === "__TAGS__") {
    sel.value = selectedPaw; // restore special value immediately
  }
  try {
    const agents = await apiFetch("/api/v2/agents");
    const list = agents.agents || agents || [];
    list.forEach((a) => {
      const host = a.host || a.hostname || "";
      let label = a.alias ? `${a.alias}  (${host})` : host;
      label += `  [${a.paw}]`;
      const opt = document.createElement("option");
      opt.value       = escHtml(a.paw);
      opt.textContent = label;
      sel.appendChild(opt);
    });
    if (selectedPaw) sel.value = selectedPaw; // restore real paw after agents load
  } catch (err) {
    // special options remain visible even if agent fetch fails
  }
}

async function executeScriptFromModal() {
  const paw = document.getElementById("sm-agent-select").value;
  if (!paw) { alert("Select a target first."); return; }
  const command = (document.getElementById("sm-command").value || "").trim();
  if (!command) { alert("Enter a command first."); return; }

  const resultEl = document.getElementById("sm-execute-result");
  const outputSec = document.getElementById("sm-output-section");
  const outputPre = document.getElementById("sm-output-pre");
  const outputStatus = document.getElementById("sm-output-status");

  // Broadcast path: __ALL__ or __TAGS__ — no single-job output polling
  if (paw === "__ALL__" || paw === "__TAGS__") {
    resultEl.textContent = paw === "__TAGS__" ? "Targeting agents matching this script's tags..." : "Targeting all registered agents...";
    resultEl.style.display = "inline";
    outputSec.style.display = "none";
    try {
      // Save first — tag lookup needs a valid script ID
      if (_currentScriptId && _scriptDirty) {
        if (!confirm("Script has unsaved changes. Save now before executing?")) return;
        await saveScriptFromModal();
        if (!_currentScriptId) return;
      }
      if (!_currentScriptId) { resultEl.textContent = "[INFO] Save the script first before using tag-based targeting."; return; }
      let paws;
      try { paws = await _resolvePaws(paw, "script", String(_currentScriptId)); } catch(e) {
        resultEl.textContent = "[INFO] " + e.message;
        return;
      }
      resultEl.textContent = `Queuing on ${paws.length} agent(s)...`;
      const jobs = [];
      for (const p of paws) {
        const r = await apiFetch(`/api/v2/scripts/${_currentScriptId}/execute`, {
          method: "POST", body: JSON.stringify({ paw: p }),
        });
        jobs.push(r.job_id ? r.job_id.slice(0, 8) : "?");
      }
      resultEl.textContent = `[OK] Queued on ${paws.length} agent(s). IDs: ${jobs.join(", ")}`;
    } catch (err) {
      resultEl.textContent = "[ERROR] " + err.message;
    }
    return;
  }

  // Single-agent path (with output polling)
  resultEl.textContent = "Queuing...";
  resultEl.style.display = "inline";
  outputSec.style.display = "none";
  outputPre.textContent = "";

  try {
    let result;
    if (_currentScriptId && _scriptDirty) {
      if (!confirm("Script has unsaved changes. Save now before executing?")) return;
      await saveScriptFromModal();
      if (!_currentScriptId) return;
    }
    if (_currentScriptId) {
      result = await apiFetch(`/api/v2/scripts/${_currentScriptId}/execute`, {
        method: "POST",
        body: JSON.stringify({ paw }),
      });
    } else {
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
    renderTagsTable(_allTags);
    loadWorkspaces();
  } catch (err) {
    console.error("[TAGS] Load failed:", err.message);
  }
}

function applyTagFilters() {
  const q = (document.getElementById("tagFilterText")?.value || "").toLowerCase();
  const ns = (document.getElementById("tagFilterNs")?.value || "").toLowerCase();
  const tp = (document.getElementById("tagFilterType")?.value || "");
  const meta = (document.getElementById("tagFilterMeta")?.value || "");
  let filtered = _allTags;
  if (q) filtered = filtered.filter((t) =>
    (t.label || t.name || "").toLowerCase().includes(q) ||
    (t.key || "").toLowerCase().includes(q)
  );
  if (ns) filtered = filtered.filter((t) => (t.namespace || t.group_name || "").toLowerCase().includes(ns));
  if (tp) filtered = filtered.filter((t) => (t.tag_type || "") === tp);
  if (meta === "runtime") filtered = filtered.filter((t) => t.is_runtime_param);
  if (meta === "filterable") filtered = filtered.filter((t) => t.is_filterable);
  renderTagsTable(filtered);
}

function renderTagsTable(tags) {
  const tbody = document.getElementById("tagsTableBody");
  if (!tbody) return;
  if (!tags.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No tags defined yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = tags.map((t) => {
    const label = escHtml(t.label || t.name || "");
    const key = escHtml(t.key || "");
    const val = t.value ? `=${escHtml(t.value)}` : "";
    const ns = escHtml(t.namespace || t.group_name || "general");
    const tp = escHtml(t.tag_type || "flag");
    const scope = Array.isArray(t.scope) ? t.scope.join(", ") : escHtml(t.scope || "all");
    const flags = [];
    if (t.is_runtime_param) flags.push('<span title="runtime param" style="font-size:10px;background:#3b82f6;padding:1px 5px;border-radius:3px">RT</span>');
    if (t.is_filterable) flags.push('<span title="filterable" style="font-size:10px;background:#10b981;padding:1px 5px;border-radius:3px">F</span>');
    if (t.is_system) flags.push('<span title="system" style="font-size:10px;background:#f59e0b;padding:1px 5px;border-radius:3px">SYS</span>');
    return `<tr>
      <td><span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}">${label}</span></td>
      <td style="font-family:monospace;font-size:12px">${key}${val}</td>
      <td><span style="opacity:.7;font-size:12px">${ns}</span></td>
      <td><code style="font-size:11px">${tp}</code></td>
      <td style="font-size:11px;opacity:.7">${scope}</td>
      <td style="display:flex;gap:3px;flex-wrap:wrap">${flags.join("")}</td>
      <td>${t.usage_count != null ? t.usage_count : "-"}</td>
      <td>${t.is_system ? "" : `<button class="btn btn-danger btn-sm" onclick="deleteTag('${escHtml(String(t.id))}')">Delete</button>`}</td>
    </tr>`;
  }).join("");
}

function showCreateTagForm() {
  const form = document.getElementById("createTagForm");
  if (form) form.classList.remove("hidden");
}

function hideCreateTagForm() {
  const form = document.getElementById("createTagForm");
  if (form) form.classList.add("hidden");
  ["tagLabel","tagKey","tagValue","tagNamespace","tagDescription"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const typeEl = document.getElementById("tagType");
  if (typeEl) typeEl.value = "string";
  const colorEl = document.getElementById("tagColor");
  if (colorEl) colorEl.value = "#667eea";
  const rtEl = document.getElementById("tagIsRuntimeParam");
  if (rtEl) rtEl.checked = false;
  const filtEl = document.getElementById("tagIsFilterable");
  if (filtEl) filtEl.checked = true;
}

async function createTag() {
  const label = (document.getElementById("tagLabel")?.value || "").trim();
  const key = (document.getElementById("tagKey")?.value || "").trim();
  const value = (document.getElementById("tagValue")?.value || "").trim();
  const namespace = (document.getElementById("tagNamespace")?.value || "").trim() || "general";
  const tag_type = document.getElementById("tagType")?.value || "string";
  const color = document.getElementById("tagColor")?.value || "#667eea";
  const description = (document.getElementById("tagDescription")?.value || "").trim();
  const is_runtime_param = document.getElementById("tagIsRuntimeParam")?.checked || false;
  const is_filterable = document.getElementById("tagIsFilterable")?.checked ?? true;
  if (!label) { alert("Label is required."); return; }
  if (!key) { alert("Key is required."); return; }
  try {
    await apiFetch("/api/v2/tags", {
      method: "POST",
      body: JSON.stringify({ label, key, value: value || null, namespace, tag_type, color, description, is_runtime_param, is_filterable, is_assignable: true }),
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

// ── Workspaces ────────────────────────────────────────────────────────────────

let _allWorkspaces = [];

async function loadWorkspaces() {
  try {
    const data = await apiFetch("/api/v2/tags/workspaces");
    _allWorkspaces = data.workspaces || data || [];
    renderWorkspacesList(_allWorkspaces);
  } catch (err) {
    const el = document.getElementById("workspacesListBody");
    if (el) el.innerHTML = `<p class="admin-hint">[ERROR] ${escHtml(err.message)}</p>`;
  }
}

function renderWorkspacesList(list) {
  const el = document.getElementById("workspacesListBody");
  if (!el) return;
  if (!list.length) {
    el.innerHTML = `<p class="admin-hint">No workspaces yet. Create one to filter agents by tag expression.</p>`;
    return;
  }
  el.innerHTML = list.map((ws) => `
    <div style="display:flex;align-items:center;gap:.8rem;padding:.55rem .7rem;border-radius:6px;background:${ws.is_active ? "#1f2540" : "#151520"};border:1px solid ${ws.is_active ? "#5b4ecf" : "#2a2a3e"};margin-bottom:.5rem">
      <div style="flex:1">
        <strong style="color:${ws.is_active ? "#a78bfa" : "#ccc"}">${escHtml(ws.name)}</strong>
        ${ws.description ? `<span style="opacity:.5;margin-left:.4rem;font-size:12px">${escHtml(ws.description)}</span>` : ""}
        <br/>
        <code style="font-size:11px;opacity:.65">${escHtml(ws.selector_expr || "")}</code>
        ${ws.is_active && ws.matched_agents != null ? `<span style="font-size:11px;margin-left:.6rem;color:#10b981">${ws.matched_agents} agent(s) matched</span>` : ""}
      </div>
      <div style="display:flex;gap:.4rem">
        ${ws.is_active
          ? `<button class="btn btn-secondary btn-sm" onclick="clearActiveWorkspace()">Deactivate</button>`
          : `<button class="btn btn-primary btn-sm" onclick="activateWorkspace('${escHtml(String(ws.id))}')">Activate</button>`
        }
        <button class="btn btn-danger btn-sm" onclick="deleteWorkspace('${escHtml(String(ws.id))}')">Delete</button>
      </div>
    </div>
  `).join("");
}

function showCreateWorkspaceForm() {
  const f = document.getElementById("createWorkspaceForm");
  if (f) f.classList.remove("hidden");
}

function hideCreateWorkspaceForm() {
  const f = document.getElementById("createWorkspaceForm");
  if (f) f.classList.add("hidden");
  ["wsName","wsExpr","wsDesc"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

async function createWorkspace() {
  const name = (document.getElementById("wsName")?.value || "").trim();
  const selector_expr = (document.getElementById("wsExpr")?.value || "").trim();
  const description = (document.getElementById("wsDesc")?.value || "").trim();
  if (!name) { alert("Workspace name is required."); return; }
  if (!selector_expr) { alert("Selector expression is required."); return; }
  try {
    await apiFetch("/api/v2/tags/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, selector_expr, description }),
    });
    hideCreateWorkspaceForm();
    await loadWorkspaces();
  } catch (err) {
    alert("Create workspace failed: " + err.message);
  }
}

async function activateWorkspace(id) {
  try {
    await apiFetch(`/api/v2/tags/workspaces/${id}/activate`, { method: "POST" });
    await loadWorkspaces();
    await checkActiveWorkspace();
  } catch (err) {
    alert("Activate failed: " + err.message);
  }
}

async function deleteWorkspace(id) {
  if (!confirm("Delete this workspace?")) return;
  try {
    await apiFetch(`/api/v2/tags/workspaces/${id}`, { method: "DELETE" });
    await loadWorkspaces();
    await checkActiveWorkspace();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function clearActiveWorkspace() {
  try {
    await apiFetch("/api/v2/tags/workspaces/active", { method: "DELETE" });
    await checkActiveWorkspace();
    await loadWorkspaces();
  } catch (err) {
    alert("Clear failed: " + err.message);
  }
}

async function checkActiveWorkspace() {
  const bar = document.getElementById("workspace-bar");
  try {
    const ws = await apiFetch("/api/v2/tags/workspaces/active");
    if (ws && ws.id) {
      if (bar) { bar.style.display = "flex"; bar.classList.remove("hidden"); }
      const nEl = document.getElementById("ws-bar-name");
      const eEl = document.getElementById("ws-bar-expr");
      const aEl = document.getElementById("ws-bar-agents");
      if (nEl) nEl.textContent = ws.name;
      if (eEl) eEl.textContent = ws.selector_expr || "";
      if (aEl) aEl.textContent = ws.matched_agents != null ? `(${ws.matched_agents} agents)` : "";
    } else {
      if (bar) { bar.style.display = "none"; bar.classList.add("hidden"); }
    }
  } catch {
    if (bar) { bar.style.display = "none"; bar.classList.add("hidden"); }
  }
}

// ── Users ─────────────────────────────────────────────────────────────────────

// -- Users ------------------------------------------------------------------

async function loadUsers() {
  const tbody = document.getElementById("usersTableBody");
  if (tbody) tbody.innerHTML = `<tr><td colspan="9" class="empty-row">Loading...</td></tr>`;
  try {
    const data = await apiFetch("/api/v2/users");
    const users = Array.isArray(data) ? data : (data.users || []);
    renderUsersTable(users);
    // Show break glass warning if flagged
    const bg = users.find((u) => u.is_break_glass);
    if (bg && bg.default_password_warning) {
      const el = document.getElementById("breakGlassBanner");
      if (el) el.style.display = "block";
    }
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" class="empty-row">[ERROR] ${escHtml(err.message)}</td></tr>`;
  }
}

function _wsLabel(workspaces) {
  try {
    const arr = Array.isArray(workspaces) ? workspaces : JSON.parse(workspaces || "[]");
    if (!arr.length || arr[0] === "__ALL__") return "<span style=\"color:var(--text-secondary)\">All</span>";
    return escHtml(arr.join(", "));
  } catch (_) { return "?"; }
}

function renderUsersTable(users) {
  const tbody = document.getElementById("usersTableBody");
  _cachedUsers = users;
  if (!tbody) return;
  if (!users.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-row">No users yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = users.map((u) => {
    const isBreakGlass = u.is_break_glass || false;
    const roleColor = u.role === "admin" ? "#f59e0b" : u.role === "reader" ? "#aaa" : "var(--text-primary)";
    const tagBadges = (u.tags || []).map((t) =>
      `<span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}">${escHtml(t.label || "")}</span>`
    ).join("");
    const actions = `<button class="btn btn-secondary btn-sm" onclick="openUserModal('${escHtml(String(u.id))}')">Open</button>`;
    return `<tr>
      <td>${escHtml(u.name || "")}${isBreakGlass ? " <span title=\"Break Glass\" style=\"color:#f59e0b;font-size:11px\">[BG]</span>" : ""}</td>
      <td style="font-size:12px">${escHtml(u.email || "")}</td>
      <td style="opacity:.7">${escHtml(u.aka || "")}</td>
      <td><span style="color:${roleColor}">${escHtml(u.role || "?")}</span></td>
      <td style="font-size:12px;opacity:.8">${escHtml(u.auth_provider || "local")}</td>
      <td>${u.is_enabled ? "<span style=\"color:#10b981\">Yes</span>" : "<span style=\"color:#ef4444\">No</span>"}</td>
      <td style="font-size:11px">${_wsLabel(u.workspaces || "[]")}</td>
      <td>${tagBadges || "<span style=\"opacity:.4\">-</span>"}</td>
      <td style="white-space:nowrap">${actions}</td>
    </tr>`;
  }).join("");
}


// -- User edit modal --------------------------------------------------------

// -- User edit modal --------------------------------------------------------

async function openUserModal(userId) {
  _editingUserId   = userId;
  _editingUserTagIds = [];
  const u = _cachedUsers.find((x) => String(x.id) === String(userId));
  if (!u) return;
  const isBreakGlass = u.is_break_glass || false;
  const roleColor = u.role === "admin" ? "#f59e0b" : u.role === "reader" ? "#aaa" : "var(--text-primary)";

  document.getElementById("uem-title").textContent = u.name + (isBreakGlass ? " [BG]" : "");

  document.getElementById("uem-static").innerHTML =
    `<span style="color:var(--text-muted)">Email</span><span>${escHtml(u.email || "-")}</span>` +
    `<span style="color:var(--text-muted)">Provider</span><span>${escHtml(u.auth_provider || "local")}</span>`;

  document.getElementById("uem-aka").value = u.aka || "";

  const roleEl = document.getElementById("uem-role");
  roleEl.value    = u.role || "contributor";
  roleEl.disabled = isBreakGlass;

  const enabledCb = document.getElementById("uem-enabled");
  enabledCb.checked  = !!u.is_enabled;
  enabledCb.disabled = isBreakGlass;

  const delBtn = document.getElementById("uem-delete-btn");
  if (delBtn) delBtn.style.display = isBreakGlass ? "none" : "";

  const chpw = document.getElementById("uem-chpw");
  if (isBreakGlass) {
    ["uemCpCurrentPw","uemCpNewPw","uemCpConfirmPw"].forEach((id) => { const e = document.getElementById(id); if (e) e.value = ""; });
    const err = document.getElementById("uemCpError"); if (err) err.style.display = "none";
    chpw.style.display = "";
  } else {
    chpw.style.display = "none";
  }

  const wsDiv  = document.getElementById("uem-workspaces");
  const tagDiv = document.getElementById("uem-tags");
  wsDiv.innerHTML  = `<span style="color:var(--text-muted);font-size:12px">Loading...</span>`;
  tagDiv.innerHTML = `<span style="color:var(--text-muted);font-size:12px">Loading...</span>`;

  document.getElementById("userEditModal").style.display = "flex";

  try {
    const [allWsData, allTagsData, userTagsData] = await Promise.all([
      apiFetch("/api/v2/tags/workspaces"),
      apiFetch("/api/v2/tags"),
      apiFetch(`/api/v2/tags/entity/user/${userId}`),
    ]);

    const userWsList = (() => {
      try { return Array.isArray(u.workspaces) ? u.workspaces : JSON.parse(u.workspaces || '["__ALL__"]'); }
      catch (_) { return ["__ALL__"]; }
    })();
    const isAllWs = userWsList.includes("__ALL__");
    const wsArr   = Array.isArray(allWsData) ? allWsData : (allWsData.workspaces || []);

    let wsHtml = `<label style="display:flex;gap:6px;align-items:center;margin-bottom:8px;font-size:13px">` +
      `<input type="checkbox" id="uem-ws-all" onchange="uemToggleAllWorkspaces(this.checked)" ${isAllWs ? "checked" : ""}> All workspaces</label>` +
      `<div id="uem-ws-list" style="${isAllWs ? "opacity:.4;pointer-events:none" : ""}">`;
    wsArr.forEach((ws) => {
      const checked = !isAllWs && userWsList.includes(ws.id) ? "checked" : "";
      wsHtml += `<label style="display:flex;gap:6px;align-items:center;font-size:12px;margin-bottom:4px">` +
        `<input type="checkbox" class="uem-ws-cb" value="${escHtml(ws.id)}" ${checked}> ${escHtml(ws.name || ws.id)}</label>`;
    });
    wsHtml += `</div>`;
    wsDiv.innerHTML = wsArr.length ? wsHtml : `<label style="display:flex;gap:6px;align-items:center;font-size:13px">` +
      `<input type="checkbox" id="uem-ws-all" checked onchange="uemToggleAllWorkspaces(this.checked)"> All workspaces</label>`;

    const assignedTags = Array.isArray(userTagsData) ? userTagsData : (userTagsData.tags || []);
    _editingUserTagIds = assignedTags.map((t) => String(t.id || t.tag_id));

    const tagsArr = Array.isArray(allTagsData) ? allTagsData : (allTagsData.tags || []);
    if (!tagsArr.length) {
      tagDiv.innerHTML = `<span style="color:var(--text-muted);font-size:12px">No tags defined</span>`;
    } else {
      let tagsHtml = "";
      tagsArr.forEach((t) => {
        const checked = _editingUserTagIds.includes(String(t.id)) ? "checked" : "";
        tagsHtml +=
          `<label style="display:flex;gap:6px;align-items:center;font-size:12px;margin-bottom:5px">` +
          `<input type="checkbox" class="uem-tag-cb" value="${escHtml(String(t.id))}" ${checked}>` +
          `<span class="tag-badge" style="background:${escHtml(t.color || "#667eea")}">${escHtml(t.label || t.name || "")}</span></label>`;
      });
      tagDiv.innerHTML = tagsHtml;
    }
  } catch (err) {
    wsDiv.innerHTML  = `<span style="color:var(--danger);font-size:12px">[ERROR] ${escHtml(err.message)}</span>`;
    tagDiv.innerHTML = "";
  }
}

function closeUserModal() {
  const m = document.getElementById("userEditModal");
  if (m) m.style.display = "none";
}

function uemToggleAllWorkspaces(checked) {
  const list = document.getElementById("uem-ws-list");
  if (list) { list.style.opacity = checked ? ".4" : "1"; list.style.pointerEvents = checked ? "none" : ""; }
}

async function saveUserEdits() {
  const userId = _editingUserId;
  if (!userId) return;
  const u = _cachedUsers.find((x) => String(x.id) === String(userId));
  if (!u) return;

  const aka     = (document.getElementById("uem-aka")?.value || "").trim() || null;
  const role    = document.getElementById("uem-role")?.value || u.role;
  const enabled = !!document.getElementById("uem-enabled")?.checked;

  const allWsCb = document.getElementById("uem-ws-all");
  const workspaces = allWsCb?.checked
    ? ["__ALL__"]
    : [...document.querySelectorAll(".uem-ws-cb:checked")].map((cb) => cb.value).filter(Boolean);

  const newTagIds = [...document.querySelectorAll(".uem-tag-cb:checked")].map((cb) => cb.value);
  const toAdd    = newTagIds.filter((id) => !_editingUserTagIds.includes(id));
  const toRemove = _editingUserTagIds.filter((id) => !newTagIds.includes(id));

  try {
    await apiFetch(`/api/v2/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ aka: aka || null, role, workspaces: workspaces.length ? workspaces : ["__ALL__"] }),
    });

    if (!u.is_break_glass) {
      if (enabled && !u.is_enabled)  await apiFetch(`/api/v2/users/${userId}/enable`,  { method: "POST" });
      if (!enabled && u.is_enabled)  await apiFetch(`/api/v2/users/${userId}/disable`, { method: "POST" });
    }

    await Promise.all([
      ...toAdd.map((tid)    => apiFetch(`/api/v2/users/${userId}/tags`,        { method: "POST",   body: JSON.stringify({ tag_id: tid }) })),
      ...toRemove.map((tid) => apiFetch(`/api/v2/users/${userId}/tags/${tid}`, { method: "DELETE" })),
    ]);

    closeUserModal();
    await loadUsers();
  } catch (err) {
    alert("[ERROR] Save failed: " + err.message);
  }
}

async function uemSubmitChangePassword() {
  const current  = document.getElementById("uemCpCurrentPw")?.value || "";
  const newPw    = document.getElementById("uemCpNewPw")?.value || "";
  const confirm2 = document.getElementById("uemCpConfirmPw")?.value || "";
  const errEl    = document.getElementById("uemCpError");
  function showErr(msg) { if (errEl) { errEl.textContent = msg; errEl.style.display = "block"; } else alert(msg); }
  if (newPw.length < 12) { showErr("New password must be at least 12 characters."); return; }
  if (newPw !== confirm2) { showErr("Passwords do not match."); return; }
  try {
    await apiFetch("/api/v2/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: newPw }),
    });
    closeUserModal();
    const banner = document.getElementById("breakGlassBanner");
    if (banner) banner.style.display = "none";
    alert("Password updated successfully.");
  } catch (err) { showErr("[ERROR] " + err.message); }
}

function showCreateUserForm() {
  const el = document.getElementById("userCreateCard");
  if (el) el.style.display = "";
}

function hideCreateUserForm() {
  const el = document.getElementById("userCreateCard");
  if (el) el.style.display = "none";
  ["userName","userEmail","userAka","userPassword","userWorkspaces"].forEach((id) => {
    const e = document.getElementById(id); if (e) e.value = "";
  });
  const roleEl = document.getElementById("userRole"); if (roleEl) roleEl.value = "contributor";
  const provEl = document.getElementById("userAuthProvider"); if (provEl) provEl.value = "local";
}

async function createUser() {
  const name     = (document.getElementById("userName")?.value || "").trim();
  const email    = (document.getElementById("userEmail")?.value || "").trim();
  const aka      = (document.getElementById("userAka")?.value || "").trim();
  const password = (document.getElementById("userPassword")?.value || "");
  const role     = document.getElementById("userRole")?.value || "contributor";
  const auth_provider = document.getElementById("userAuthProvider")?.value || "local";
  const wsRaw    = (document.getElementById("userWorkspaces")?.value || "").trim();
  const workspaces = wsRaw ? wsRaw.split(",").map((s) => s.trim()).filter(Boolean) : ["__ALL__"];
  if (!name)  { alert("Name is required."); return; }
  if (!email) { alert("Email is required."); return; }
  if (auth_provider === "local" && password && password.length < 8) {
    alert("Password must be at least 8 characters."); return;
  }
  try {
    await apiFetch("/api/v2/users", {
      method: "POST",
      body: JSON.stringify({ name, email, aka: aka || null, password: password || undefined, role, auth_provider, workspaces }),
    });
    hideCreateUserForm();
    await loadUsers();
  } catch (err) {
    alert("Create user failed: " + err.message);
  }
}

async function enableUser(userId) {
  try {
    await apiFetch(`/api/v2/users/${userId}/enable`, { method: "POST" });
    await loadUsers();
  } catch (err) { alert("Enable failed: " + err.message); }
}

async function disableUser(userId) {
  if (!confirm("Disable this user?")) return;
  try {
    await apiFetch(`/api/v2/users/${userId}/disable`, { method: "POST" });
    await loadUsers();
  } catch (err) { alert("Disable failed: " + err.message); }
}

async function deleteUser(userId) {
  if (!confirm("Delete this user?")) return;
  try {
    await apiFetch(`/api/v2/users/${userId}`, { method: "DELETE" });
    await loadUsers();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

// -- Break glass password change ---------------------------------------------

function showChangePasswordModal() {
  const m = document.getElementById("changePwModal");
  if (!m) return;
  m.style.display = "flex";
  ["cpCurrentPw","cpNewPw","cpConfirmPw"].forEach((id) => { const e = document.getElementById(id); if (e) e.value = ""; });
  const err = document.getElementById("cpError"); if (err) err.style.display = "none";
}

function hideChangePasswordModal() {
  const m = document.getElementById("changePwModal"); if (m) m.style.display = "none";
}

async function submitChangePassword() {
  const current  = document.getElementById("cpCurrentPw")?.value || "";
  const newPw    = document.getElementById("cpNewPw")?.value || "";
  const confirm2 = document.getElementById("cpConfirmPw")?.value || "";
  const errEl    = document.getElementById("cpError");
  function showCpError(msg) { if (errEl) { errEl.textContent = msg; errEl.style.display = "block"; } else alert(msg); }
  if (newPw.length < 12) { showCpError("New password must be at least 12 characters."); return; }
  if (newPw !== confirm2) { showCpError("Passwords do not match."); return; }
  try {
    await apiFetch("/api/v2/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: newPw }),
    });
    hideChangePasswordModal();
    const banner = document.getElementById("breakGlassBanner");
    if (banner) banner.style.display = "none";
    alert("Password updated successfully.");
  } catch (err) { showCpError("Failed: " + err.message); }
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
  const { entityType, entityId } = _tagPickerContext;
  // Refresh inline row for any entity
  if (entityId) {
    loadEntityTagsInline(entityType, entityId, `tags-${entityType}-${entityId}`);
  }
  // Refresh script modal if open
  if (_currentScriptId) {
    loadEntityTagsInModal("script", _currentScriptId, "sm-tags-container");
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
    const _savedChainPaw = _editingChain.agent_paw || "";
    sel.innerHTML =
      '<option value="">-- select target --</option>' +
      '<option value="__ALL__">Broadcast: all agents</option>' +
      '<option value="__TAGS__">Agents with this chain\'s tags</option>';
    // Restore special targets immediately (without waiting for agent list)
    if (_savedChainPaw === "__ALL__" || _savedChainPaw === "__TAGS__") {
      sel.value = _savedChainPaw;
    }
    apiFetch("/api/v2/agents").then((agents) => {
      (agents || []).forEach((a) => {
        const label = a.alias || a.host || a.hostname || a.paw;
        const status = a.status || "unknown";
        const opt = document.createElement("option");
        opt.value       = a.paw;
        opt.textContent = `${label} [${a.paw}] - ${status}`;
        sel.appendChild(opt);
      });
      if (_savedChainPaw) sel.value = _savedChainPaw; // restore after agents loaded
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

  const body = { name, description: desc, agent_paw: agentPaw, flow: { nodes: _editingChain.nodes } };
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
    // Update _allChains inline so Execute-from-list immediately uses the new target
    const _ciIdx = _allChains.findIndex((x) => x.id === saved.id);
    const _ciPatch = { id: saved.id, name: saved.name, description: saved.description, agent_paw: agentPaw, flow: { nodes: _editingChain.nodes } };
    if (_ciIdx >= 0) _allChains[_ciIdx] = Object.assign({}, _allChains[_ciIdx], _ciPatch);
    else _allChains.unshift(_ciPatch);
    loadChains(); // refresh in background
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
  if (!paw) { alert("Select a target before executing."); return; }
  // Auto-save agent_paw if it changed without other dirty changes
  if (paw !== (_editingChain.agent_paw || "")) {
    _editingChain.agent_paw = paw;
    await saveChain();
    if (!_editingChain.id) return;
  }
  const targetLabel = paw === "__ALL__" ? "all registered agents" : paw === "__TAGS__" ? "agents matching this chain's tags" : `agent ${paw}`;
  if (!confirm(`Execute chain "${_editingChain.name}" on ${targetLabel}?`)) return;
  try {
    await _execWithTarget("chain", _editingChain.id, paw);
    closeChainEditor(); // navigate to list where chain executions are visible
  } catch (err) {
    alert("[INFO] " + err.message);
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
        <button class="btn btn-secondary btn-sm" onclick="openChainNodeScript('${nid}')">Open</button>
        <button class="btn btn-secondary btn-sm" onclick="replaceChainScript('${nid}','${br}','${iid}')">Change</button>
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

// ── Open script detail from chain node ──────────────────────────────────────────

function _findNodeInTree(nodes, nodeId) {
  for (const n of nodes) {
    if (n.id === nodeId) return n;
    if (n.type === "if_else") {
      const r = _findNodeInTree(n.if_nodes || [], nodeId)
             || _findNodeInTree(n.else_nodes || [], nodeId);
      if (r) return r;
    }
  }
  return null;
}

async function openChainNodeScript(nodeId) {
  const node = _findNodeInTree(_editingChain.nodes, nodeId);
  if (!node || !node.script_id) { alert("Script not found in chain."); return; }
  if (!allScripts.length) {
    try {
      const data = await apiFetch("/api/v2/scripts?limit=5000");
      allScripts = data.scripts || data || [];
    } catch (e) {
      alert("Could not load scripts: " + e.message);
      return;
    }
  }
  openScriptModal(node.script_id);
}

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
    const _savedCampPaw = _editingCampaign.agent_paw || "";
    sel.innerHTML =
      '<option value="">-- select target --</option>' +
      '<option value="__ALL__">Broadcast: all agents</option>' +
      '<option value="__TAGS__">Agents with this campaign\'s tags</option>';
    // Restore special targets before adding real agents
    if (_savedCampPaw === "__ALL__" || _savedCampPaw === "__TAGS__") {
      sel.value = _savedCampPaw;
    }
    agents.forEach((a) => {
      const label = a.alias || a.host || a.hostname || a.paw;
      const opt = document.createElement("option");
      opt.value       = escHtml(a.paw);
      opt.textContent = `${label} [${a.paw}]`;
      sel.appendChild(opt);
    });
    if (_savedCampPaw) sel.value = _savedCampPaw;
  } catch (e) { /* ignore */ }

  // Load chains for picker cache
  try {
    _campAllChains = await apiFetch("/api/v2/chains");
  } catch (e) { _campAllChains = []; }

  // Load tags for this campaign
  const campAddTagBtn = document.getElementById("camp-add-tag-btn");
  if (_editingCampaign.id) {
    if (campAddTagBtn) campAddTagBtn.disabled = false;
    loadEntityTagsInModal("campaign", _editingCampaign.id, "camp-tags-container");
  } else {
    if (campAddTagBtn) campAddTagBtn.disabled = true;
    const tc = document.getElementById("camp-tags-container");
    if (tc) tc.innerHTML = "<span class='admin-hint'>Save campaign first to assign tags.</span>";
  }

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

  const body = { name, description: desc, agent_paw: agePaw, flow_json: JSON.stringify({ nodes: _editingCampaign.nodes }) };
  try {
    let saved;
    if (_editingCampaign.id) {
      saved = await apiFetch(`/api/v2/campaigns/${_editingCampaign.id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      saved = await apiFetch("/api/v2/campaigns", { method: "POST", body: JSON.stringify(body) });
    }
    _editingCampaign.id = saved.id;
    document.getElementById("campaign-editor-title").textContent = saved.name;
    // Enable tags section now that we have an id
    const _campTagBtn = document.getElementById("camp-add-tag-btn");
    if (_campTagBtn) _campTagBtn.disabled = false;
    loadEntityTagsInModal("campaign", saved.id, "camp-tags-container");
    document.getElementById("camp-exec-btn").disabled = false;
    _campaignDirty = false;
    alert("Campaign saved.");
    // Update _allCampaigns inline so Execute-from-list immediately uses the new target
    const _cmpIdx = _allCampaigns.findIndex((x) => x.id === saved.id);
    const _cmpPatch = { id: saved.id, name: saved.name, description: saved.description, agent_paw: agePaw };
    if (_cmpIdx >= 0) _allCampaigns[_cmpIdx] = Object.assign({}, _allCampaigns[_cmpIdx], _cmpPatch);
    else _allCampaigns.unshift(_cmpPatch);
    loadCampaigns(); // refresh in background
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
  if (!agentPaw) { alert("Select a target before executing."); return; }
  const cmp = _editingCampaign;
  // Auto-save agent_paw if it changed without other dirty changes
  if (agentPaw !== (cmp.agent_paw || "")) {
    cmp.agent_paw = agentPaw;
    await saveCampaign();
    if (!_editingCampaign.id) return;
  }
  const targetLabel = agentPaw === "__ALL__" ? "all registered agents" : agentPaw === "__TAGS__" ? "agents matching this campaign's tags" : `agent ${agentPaw}`;
  if (!confirm(`Execute campaign "${cmp.name}" on ${targetLabel}?`)) return;
  try {
    await _execWithTarget("campaign", cmp.id, agentPaw);
    closeCampaignEditor(); // navigate to list where campaign executions are visible
  } catch (err) {
    alert("[INFO] " + err.message);
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
  const _savedExecPaw = (entry || {}).agent_paw || (entry || {}).target_agent_paw || "";
  try {
    const agents = await apiFetch("/api/v2/agents");
    const list = agents.agents || agents || [];
    sel.innerHTML =
      '<option value="">-- select target --</option>' +
      '<option value="__ALL__">Broadcast: all agents</option>' +
      `<option value="__TAGS__">${"Agents with this " + type + "'s tags"}</option>` +
      list.map((a) => {
        const host  = a.host || a.hostname || "";
        const label = a.alias ? a.alias + "  (" + host + ")  [" + a.paw + "]" : host + "  [" + a.paw + "]";
        return '<option value="' + escHtml(a.paw) + '">' + escHtml(label) + '</option>';
      }).join("");
    const livePaws2 = list.map((a) => a.paw);
    const pawValid  = _savedExecPaw === "__ALL__" || _savedExecPaw === "__TAGS__" || livePaws2.includes(_savedExecPaw);
    if (_savedExecPaw && pawValid) {
      sel.value = _savedExecPaw;
    } else {
      // Stale/missing paw — pre-select __ALL__ so user just clicks Execute
      sel.value = "__ALL__";
    }
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
  if (!paw) { alert("Select a target first."); return; }
  const btn = document.getElementById("qe-run-btn");
  btn.disabled    = true;
  btn.textContent = "Running...";
  try {
    const execType = _qeType;
    const execId   = _qeId;
    closeQuickExecModal();
    // Persist selected target so next Execute from list fires directly
    if (execType === "chain") {
      apiFetch(`/api/v2/chains/${execId}`, { method: "PUT", body: JSON.stringify({ agent_paw: paw }) }).then((updated) => {
        const idx = _allChains.findIndex((x) => x.id === execId);
        if (idx >= 0) _allChains[idx] = Object.assign({}, _allChains[idx], { agent_paw: updated.agent_paw || paw });
      }).catch(() => {});
    } else if (execType === "campaign") {
      apiFetch(`/api/v2/campaigns/${execId}`, { method: "PUT", body: JSON.stringify({ agent_paw: paw }) }).then((updated) => {
        const idx = _allCampaigns.findIndex((x) => x.id === execId);
        if (idx >= 0) _allCampaigns[idx] = Object.assign({}, _allCampaigns[idx], { agent_paw: updated.agent_paw || paw });
      }).catch(() => {});
    } else if (execType === "script") {
      apiFetch(`/api/v2/scripts/${execId}`, { method: "PUT", body: JSON.stringify({ target_agent_paw: paw }) }).catch(() => {});
    }
    await _execWithTarget(execType, execId, paw);
  } catch (err) {
    alert("[ERROR] " + err.message);
  } finally {
    btn.disabled    = false;
    btn.textContent = "Execute";
  }
}

// Resolve paw -> list of agent paws (handles __ALL__ / __TAGS__)
async function _resolvePaws(paw, entityType, entityId) {
  if (paw !== "__ALL__" && paw !== "__TAGS__") return [paw];
  if (paw === "__ALL__") {
    const data = await apiFetch("/api/v2/agents");
    const list = data.agents || data || [];
    if (!list.length) throw new Error("No agents registered.");
    return list.map((a) => a.paw);
  }
  // __TAGS__: find agents sharing at least one tag with this entity
  if (!entityType || !entityId) {
    throw new Error("Save this item first — tags are checked after saving.");
  }
  const resolved = await apiFetch(
    `/api/v2/tags/resolve-agents-by-entity?entity_type=${entityType}&entity_id=${entityId}`
  );
  const paws = (resolved.agents || []).map((a) => a.paw);
  if (!paws.length) {
    throw new Error(
      `No agents share tags with this ${entityType}. ` +
      "Assign the same tag(s) to at least one agent first."
    );
  }
  return paws;
}

// Execute type/id against a target paw (or __ALL__ / __TAGS__) — no modal
async function _execWithTarget(execType, execId, paw) {
  const paws = await _resolvePaws(paw, execType, String(execId));
  const isBroadcast = (paw === "__ALL__" || paw === "__TAGS__");
  const results = [];
  const errors  = [];
  for (const p of paws) {
    let endpoint, body;
    if (execType === "script") {
      endpoint = "/api/v2/scripts/" + execId + "/execute";
      body = { paw: p };
    } else if (execType === "chain") {
      endpoint = "/api/v2/chains/" + execId + "/execute";
      body = { agent_paw: p };
    } else {
      endpoint = "/api/v2/campaigns/" + execId + "/execute";
      body = { agent_paw: p };
    }
    try {
      const r = await apiFetch(endpoint, { method: "POST", body: JSON.stringify(body) });
      results.push({ paw: p, r });
    } catch (e) {
      errors.push({ paw: p, msg: e.message });
    }
  }
  if (!results.length && errors.length) {
    throw new Error("All agents failed. Details:\n" + errors.map((x) => x.paw + ": " + x.msg).join("\n"));
  }
  const errNote = errors.length
    ? "\n[WARN] Skipped " + errors.length + " agent(s): " + errors.map((x) => x.paw + " (" + x.msg + ")").join(", ")
    : "";
  if (execType === "script") {
    const ids = results.map((x) => (x.r.job_id || "?").slice(0, 8)).join(", ");
    alert("[OK] Script queued on " + results.length + " agent(s).\nJob ID(s): " + ids + errNote);
  } else if (execType === "chain") {
    const ids = results.map((x) => (x.r.execution_id || "?").slice(0, 8)).join(", ");
    alert("Chain started on " + results.length + " agent(s).\nExecution ID(s): " + ids + errNote);
    loadChainExecutionsList();
  } else {
    const ids = results.map((x) => (x.r.execution_id || "?").slice(0, 8)).join(", ");
    alert("Campaign started on " + results.length + " agent(s).\nExecution ID(s): " + ids + errNote);
  }
}

// Smart execute: use saved target if present, otherwise show modal
function quickExecuteScript(id) {
  const s = allScripts.find((x) => String(x.id) === String(id));
  const saved = (s || {}).target_agent_paw;
  if (saved) { _execWithTarget("script", id, saved).catch((e) => alert("[ERROR] " + e.message)); return; }
  _showQuickExecModal("script", id);
}
function quickExecuteChain(id) {
  // Fetch fresh chain + live agents
  Promise.all([apiFetch("/api/v2/chains/" + id), apiFetch("/api/v2/agents")])
    .then(([chain, agentData]) => {
      const paw = (chain.agent_paw || "").trim();
      if (!paw) { _showQuickExecModal("chain", id); return; }
      // Has a saved target — validate; if stale real paw, fall back to __ALL__ silently
      const livePaws = (agentData.agents || agentData || []).map((a) => a.paw);
      const isSpecial = paw === "__ALL__" || paw === "__TAGS__";
      const effectivePaw = (isSpecial || livePaws.includes(paw)) ? paw : "__ALL__";
      const idx = _allChains.findIndex((x) => x.id === id);
      if (idx >= 0) _allChains[idx] = Object.assign({}, _allChains[idx], { agent_paw: effectivePaw });
      _execWithTarget("chain", id, effectivePaw).catch((e) => alert("[ERROR] " + e.message));
    }).catch(() => _showQuickExecModal("chain", id));
}
function quickExecuteCampaign(id) {
  Promise.all([apiFetch("/api/v2/campaigns/" + id), apiFetch("/api/v2/agents")])
    .then(([camp, agentData]) => {
      const paw = (camp.agent_paw || "").trim();
      if (!paw) { _showQuickExecModal("campaign", id); return; }
      const livePaws = (agentData.agents || agentData || []).map((a) => a.paw);
      const isSpecial = paw === "__ALL__" || paw === "__TAGS__";
      const effectivePaw = (isSpecial || livePaws.includes(paw)) ? paw : "__ALL__";
      const idx = _allCampaigns.findIndex((x) => x.id === id);
      if (idx >= 0) _allCampaigns[idx] = Object.assign({}, _allCampaigns[idx], { agent_paw: effectivePaw });
      _execWithTarget("campaign", id, effectivePaw).catch((e) => alert("[ERROR] " + e.message));
    }).catch(() => _showQuickExecModal("campaign", id));
}

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
        <button class="btn btn-secondary btn-sm" onclick="openCampNodeChain('${nid}')">Open</button>
        <button class="btn btn-secondary btn-sm" onclick="replaceCampChain('${nid}','${br}','${pid}')">Change</button>
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

// ── Open chain detail from campaign node ────────────────────────────────────────

function _findCampNodeInTree(nodes, nodeId) {
  for (const n of nodes) {
    if (n.id === nodeId) return n;
    if (n.type === "parallel") {
      for (const branch of (n.branches || [])) {
        const r = _findCampNodeInTree(branch, nodeId);
        if (r) return r;
      }
    }
  }
  return null;
}

async function openCampNodeChain(nodeId) {
  const node = _findCampNodeInTree(_editingCampaign.nodes, nodeId);
  if (!node || !node.chain_id) { alert("Chain not found in campaign."); return; }
  let chain = (_allChains || []).find((c) => String(c.id) === String(node.chain_id));
  if (!chain) {
    try {
      chain = await apiFetch("/api/v2/chains/" + node.chain_id);
    } catch (e) {
      alert("Could not load chain: " + e.message);
      return;
    }
  }
  document.getElementById("cdm-title").textContent = chain.name || "Chain Detail";
  const descEl = document.getElementById("cdm-desc");
  if (descEl) descEl.textContent = chain.description || "";
  const scriptNodes = (chain.flow && chain.flow.nodes ? chain.flow.nodes : [])
    .filter((n) => n.type === "script" || !n.type);
  const tbody = document.getElementById("cdm-tbody");
  if (!scriptNodes.length) {
    tbody.innerHTML = "<tr><td colspan=\"4\" class=\"empty-row\">No scripts in this chain</td></tr>";
  } else {
    tbody.innerHTML = scriptNodes.map((n, i) =>
      "<tr>" +
      "<td>" + (i + 1) + "</td>" +
      "<td>" + escHtml(n.tactic || "-") + "</td>" +
      "<td>" + escHtml(n.tcode  || "-") + "</td>" +
      "<td>" + escHtml(n.script_name || "-") + "</td>" +
      "</tr>"
    ).join("");
  }
  document.getElementById("chainDetailModal").classList.remove("hidden");
}

function closeChainDetailModal() {
  document.getElementById("chainDetailModal").classList.add("hidden");
}

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
  initAuth();
  checkHealth();
  refreshDashboard();
  checkActiveWorkspace();
  setInterval(checkHealth, 30000);
  setInterval(() => {
    const activePage = document.querySelector(".page.active");
    if (!activePage) return;
    if (activePage.id === "page-dashboard") refreshDashboard();
    if (activePage.id === "page-agents") loadAgents();
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
