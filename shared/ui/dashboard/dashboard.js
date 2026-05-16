/* dashboard.js - Spine Dashboard SPA host
 * STORY-9.9.4 + STORY-1.5.6 + STORY-1.5.7 + STORY-1.6.2 + STORY-1.6.3.
 * Vanilla ES2020 modules. No router, just tab show/hide with per-panel
 * mount/unmount so polling timers and DOM are reclaimed cleanly.
 *
 * Per-panel modules each export { mount(container, ctx), unmount(container) }.
 * Tab switching unmounts the outgoing panel and mounts the incoming one,
 * keeping at most one panel polling at a time (cost-meter excepted; its
 * 60s cadence is cheap enough to leave warm via the header health chip).
 *
 * Endpoints used (proxied by serve.sh -> proxy.py / FastAPI):
 *   GET  /api/v2/projects?status=active            -> portfolio
 *   POST /api/v2/projects                          -> create
 *   GET  /api/v2/projects/{id}                     -> drill detail
 *   GET  /api/v2/audit?project_id=...&since=...    -> activity + cost ledger
 *   GET  /api/v2/audit/export?format=json&...      -> bulk cost rollup
 *   POST /api/v2/kg/hybrid_search                  -> KG search proxy
 *   GET  /healthz                                  -> sanity ping
 */
"use strict";

import { mount as mountProjects, unmount as unmountProjects } from "./panels/projects-grid.js";
import { mount as mountCost,     unmount as unmountCost     } from "./panels/cost-meter.js";
import { mount as mountActivity, unmount as unmountActivity } from "./panels/activity-stream.js";
import { mount as mountKg,       unmount as unmountKg       } from "./panels/kg-search.js";

const LS_KEY = "spine.dashboard.settings.v1";
const DEFAULTS = {
  apiBase: "http://127.0.0.1:8081",
  actor: "",
  pollActivitySec: 5,
  pollProjectsSec: 10,
  pollCostSec: 60,
  defaultTab: "projects",
  defaultProjectFilter: "",
};

const $ = (id) => document.getElementById(id);

const state = {
  settings: { ...DEFAULTS },
  activeTab: "projects",
  paused: false,
  toastTimer: null,
  health: null,
  wsScaffold: null,
};

const PANELS = {
  projects:  { mount: mountProjects, unmount: unmountProjects, host: "panel-projects",  pollKey: "pollProjectsSec" },
  cost:      { mount: mountCost,     unmount: unmountCost,     host: "panel-cost",      pollKey: "pollCostSec" },
  activity:  { mount: mountActivity, unmount: unmountActivity, host: "panel-activity",  pollKey: "pollActivitySec" },
  knowledge: { mount: mountKg,       unmount: unmountKg,       host: "panel-knowledge", pollKey: null },
};

// ───────────────────────────── settings ─────────────────────────────
function loadSettings() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) state.settings = { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore corrupt blob */ }
}
function saveSettings() {
  localStorage.setItem(LS_KEY, JSON.stringify(state.settings));
  $("foot-api").textContent = state.settings.apiBase;
}

// ───────────────────────────── api ──────────────────────────────────
async function apiGet(path) {
  const r = await fetch(`${state.settings.apiBase}${path}`, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
async function apiPost(path, body) {
  const r = await fetch(`${state.settings.apiBase}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not json */ }
  if (!r.ok || data?.ok === false) {
    throw new Error(data?.error || data?.message || data?.detail?.message || `POST ${path} -> ${r.status}`);
  }
  return data;
}

// ───────────────────────────── toast ────────────────────────────────
function toast(msg, kind = "ok") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast show kind-${kind}`;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}

// ───────────────────────────── el helper ────────────────────────────
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else if (v != null && v !== false) n.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k == null || k === false) continue;
    n.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
  return n;
}

// ───────────────────────────── ctx for panels ───────────────────────
function buildCtx() {
  return {
    apiGet, apiPost, el, toast,
    settings: state.settings,
    isPaused: () => state.paused,
    openProjectDetail,
  };
}

// ───────────────────────────── tabs ─────────────────────────────────
function switchTab(name) {
  if (!PANELS[name] || name === state.activeTab) return;
  const prev = state.activeTab;
  const prevPanel = PANELS[prev];
  const nextPanel = PANELS[name];
  try { prevPanel.unmount($(prevPanel.host)); }
  catch (e) { console.warn("unmount failed", prev, e); }
  $(prevPanel.host).hidden = true;
  document.querySelectorAll(".tab[data-tab]").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  $(nextPanel.host).hidden = false;
  state.activeTab = name;
  try { nextPanel.mount($(nextPanel.host), buildCtx()); }
  catch (e) { console.error("mount failed", name, e); toast(`Panel ${name} failed: ${e.message}`, "err"); }
}

function refreshActive() {
  // Mount/unmount cycle is the simplest way to force a panel-local refresh.
  const name = state.activeTab;
  const p = PANELS[name];
  if (!p) return;
  try { p.unmount($(p.host)); p.mount($(p.host), buildCtx()); }
  catch (e) { toast(`Refresh failed: ${e.message}`, "err"); }
}

function togglePause() {
  state.paused = !state.paused;
  $("btn-pause").textContent = state.paused ? "Resume" : "Pause";
  toast(state.paused ? "Polling paused" : "Polling resumed", state.paused ? "warn" : "ok");
}

// ───────────────────────────── header health (always-on) ────────────
async function pingHealth() {
  try {
    const h = await apiGet("/healthz");
    state.health = h;
    $("health-chip").textContent =
      `${h.active_projects ?? "-"} active / ${h.in_flight_directives ?? "-"} in-flight / $${Number(h.spend_today_usd ?? 0).toFixed(2)}`;
    $("last-sync").textContent = "synced " + new Date().toLocaleTimeString();
  } catch (e) {
    $("health-chip").textContent = "health: offline";
    $("last-sync").textContent = "sync failed";
  }
}

// ───────────────────────────── project drill modal ──────────────────
async function openProjectDetail(projectId) {
  const m = $("pd-modal");
  $("pd-title").textContent = `Project #${projectId}`;
  $("pd-meta").textContent = "";
  $("pd-body").textContent = "Loading...";
  m.showModal?.() ?? m.setAttribute("open", "");
  try {
    const detail = await apiGet(`/api/v2/projects/${encodeURIComponent(projectId)}`);
    const snap = detail.status_snapshot || {};
    $("pd-meta").textContent =
      `total cost: $${Number(detail.total_cost_usd ?? 0).toFixed(2)} - phase: ${snap.current_phase || "?"}`;
    $("pd-body").replaceChildren(
      el("h3", {}, snap.name || `Project ${projectId}`),
      el("dl", { class: "kv" },
        el("dt", {}, "Phase"),     el("dd", {}, snap.current_phase || "-"),
        el("dt", {}, "Status"),    el("dd", {}, snap.status || "-"),
        el("dt", {}, "Owner"),     el("dd", {}, snap.owner || snap.owner_user || "-"),
        el("dt", {}, "Pipeline"),  el("dd", {}, snap.pipeline_version || "-"),
        el("dt", {}, "Created"),   el("dd", {}, snap.created_at || "-"),
        el("dt", {}, "Updated"),   el("dd", {}, snap.updated_at || "-"),
        el("dt", {}, "Total cost"),el("dd", {}, `$${Number(detail.total_cost_usd ?? 0).toFixed(2)}`)),
      el("p", { class: "muted" }, "Open the Activity tab and filter by this project for the full audit trail."));
  } catch (e) {
    $("pd-body").textContent = `Failed: ${e.message}`;
  }
}
function closeProjectDetail() {
  const m = $("pd-modal");
  m.close?.() ?? m.removeAttribute("open");
}

// ───────────────────────────── new-project modal ────────────────────
function openNewProject() {
  $("np-name").value  = "";
  $("np-owner").value = state.settings.actor || "";
  $("np-status").textContent = "";
  const m = $("np-modal");
  m.showModal?.() ?? m.setAttribute("open", "");
}
function closeNewProject() {
  const m = $("np-modal");
  m.close?.() ?? m.removeAttribute("open");
}
async function createProject() {
  const name = $("np-name").value.trim();
  const project_type = $("np-type").value;
  const owner = $("np-owner").value.trim() || undefined;
  if (!name) { $("np-status").textContent = "Name is required."; return; }
  $("np-status").textContent = "Creating...";
  try {
    const res = await apiPost("/api/v2/projects", { name, project_type, owner });
    toast(`Created project ${res.project_id ?? res.id ?? name}`, "ok");
    closeNewProject();
    if (state.activeTab === "projects") refreshActive();
  } catch (e) {
    $("np-status").textContent = `Failed: ${e.message}`;
  }
}

// ───────────────────────────── WebSocket scaffold (v2 follow-on) ────
function initWsScaffold() {
  // Polling is the v1 transport. This stub records intent so the v2 swap-in
  // is a one-liner: connect, attach handler dispatching to PANELS[*].onEvent().
  state.wsScaffold = {
    enabled: false,
    connect: (url) => { console.info("[ws] v2 scaffold; would connect to", url); },
    onEvent: (_ev) => { /* per-panel handlers will subscribe in v2 */ },
  };
}

// ───────────────────────────── settings modal ───────────────────────
function openSettings() {
  $("opt-api").value             = state.settings.apiBase;
  $("opt-actor").value           = state.settings.actor;
  $("opt-poll-activity").value   = state.settings.pollActivitySec;
  $("opt-poll-projects").value   = state.settings.pollProjectsSec;
  $("opt-poll-cost").value       = state.settings.pollCostSec;
  $("opt-default-tab").value     = state.settings.defaultTab;
  $("settings-modal").showModal();
}
function saveSettingsFromForm() {
  state.settings.apiBase           = $("opt-api").value.trim() || DEFAULTS.apiBase;
  state.settings.actor             = $("opt-actor").value.trim();
  state.settings.pollActivitySec   = Number($("opt-poll-activity").value) || DEFAULTS.pollActivitySec;
  state.settings.pollProjectsSec   = Number($("opt-poll-projects").value) || DEFAULTS.pollProjectsSec;
  state.settings.pollCostSec       = Number($("opt-poll-cost").value) || DEFAULTS.pollCostSec;
  state.settings.defaultTab        = $("opt-default-tab").value || DEFAULTS.defaultTab;
  saveSettings();
  $("settings-modal").close();
  toast("Settings saved", "ok");
  refreshActive();
}

// ───────────────────────────── wire ─────────────────────────────────
function wire() {
  $("btn-refresh").onclick = () => { refreshActive(); pingHealth(); };
  $("btn-pause").onclick   = togglePause;
  $("btn-settings").onclick = openSettings;
  $("sm-close").onclick    = () => $("settings-modal").close();
  $("sm-save").onclick     = saveSettingsFromForm;

  $("btn-new-project").onclick = openNewProject;
  $("np-close").onclick   = closeNewProject;
  $("np-cancel").onclick  = closeNewProject;
  $("np-create").onclick  = createProject;

  $("pd-close").onclick = closeProjectDetail;
  $("pd-done").onclick  = closeProjectDetail;

  document.querySelectorAll(".tab[data-tab]").forEach((t) => {
    t.onclick = () => switchTab(t.dataset.tab);
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,textarea,select")) return;
    if (e.key === "Escape") { closeProjectDetail(); closeNewProject(); }
    if (e.key === "r") refreshActive();
    if (e.key === " ") { e.preventDefault(); togglePause(); }
    if (["1","2","3","4"].includes(e.key)) {
      const order = ["projects","cost","activity","knowledge"];
      switchTab(order[Number(e.key) - 1]);
    }
  });
}

// ───────────────────────────── boot ─────────────────────────────────
loadSettings();
$("foot-api").textContent = state.settings.apiBase;
wire();
initWsScaffold();

// Open default tab (mount only the chosen panel).
const first = state.settings.defaultTab in PANELS ? state.settings.defaultTab : "projects";
if (first !== "projects") {
  // Hide the projects panel that index.html started with and mount the chosen one.
  $("panel-projects").hidden = true;
  document.querySelectorAll(".tab[data-tab]").forEach((t) => {
    const on = t.dataset.tab === first;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  const p = PANELS[first];
  $(p.host).hidden = false;
  state.activeTab = first;
  try { p.mount($(p.host), buildCtx()); }
  catch (e) { toast(`Mount failed: ${e.message}`, "err"); }
} else {
  try { PANELS.projects.mount($("panel-projects"), buildCtx()); }
  catch (e) { toast(`Mount failed: ${e.message}`, "err"); }
}

pingHealth();
setInterval(() => { if (!state.paused) pingHealth(); }, 30000);

window.SpineDashboard = { state, apiGet, apiPost, switchTab, refreshActive, pingHealth };
