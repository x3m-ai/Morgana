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
      label.innerHTML = `<span class="status-dot online"></span> Server v${data.version || "?"}`;
    } else {
      dot.className = "status-dot offline";
      label.innerHTML = `<span class="status-dot offline"></span> Server error`;
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
  grid.innerHTML = agents.map((a) => `
    <div class="agent-chip">
      <div class="agent-chip-hostname">${escHtml(a.host || a.hostname || "unknown")}</div>
      <div class="agent-chip-meta">${escHtml(a.platform || "?")} &bull; PAW: ${escHtml(a.paw)}</div>
      ${stateBadge(a.status)}
    </div>
  `).join("");
}

// ─── Agents ──────────────────────────────────────────────────────────────────

async function loadAgents() {
  try {
    const agents = await apiFetch("/api/v2/agents");
    const tbody = document.getElementById("agentsTableBody");
    if (!agents.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No agents registered</td></tr>`;
      return;
    }
    tbody.innerHTML = agents.map((a) => `
      <tr>
        <td><code>${escHtml(a.paw)}</code></td>
        <td>${escHtml(a.host || a.hostname || "?")}</td>
        <td>${escHtml(a.platform || "?")}</td>
        <td>${escHtml(a.os_version || "-")}</td>
        <td>${stateBadge(a.status)}</td>
        <td>${fmtDate(a.last_seen)}</td>
        <td>${a.beacon_interval || 30}s</td>
        <td>${a.tags ? escHtml(a.tags) : "-"}</td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("[AGENTS] Load failed:", err.message);
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
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No scripts loaded. Make sure the Atomic Red Team submodule is initialized.</td></tr>`;
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
    </tr>
  `).join("");
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
