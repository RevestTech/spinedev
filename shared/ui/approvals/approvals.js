/* approvals.js — Spine Approval Queue client (STORY-1.4.2 + STORY-1.4.3)
 * Talks to the dev proxy in serve.sh which wraps orchestrator/lib/gate.sh.
 * Vanilla ES2020+. No frameworks, no external CDNs.
 * Endpoints: GET /api/v2/approvals?status=pending|approved&since=24h ;
 *  POST /api/v2/approvals {project_id,phase,action,notes,approver} ;
 *  GET /api/v2/artifacts?path=<rel> .
 */
"use strict";
const LS_KEY = "spine.approvals.settings.v1";
const DEFAULTS = { apiBase: "http://127.0.0.1:8081", pollSec: 10, approver: "" };
const $ = (id) => document.getElementById(id);
const state = {
  settings: { ...DEFAULTS }, pending: [], recent: [],
  filters: { phase: "", project: "", age: "" }, pollTimer: null, current: null,
};
function loadSettings() {
  try { const raw = localStorage.getItem(LS_KEY); if (raw) state.settings = { ...DEFAULTS, ...JSON.parse(raw) }; }
  catch { /* ignore */ }
}
function saveSettings() {
  localStorage.setItem(LS_KEY, JSON.stringify(state.settings));
  $("foot-api").textContent = state.settings.apiBase;
}
async function apiGet(path) {
  const r = await fetch(`${state.settings.apiBase}${path}`, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(`${state.settings.apiBase}${path}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const text = await r.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { /* not json */ }
  if (!r.ok || data?.ok === false) throw new Error(data?.error || data?.message || `POST ${path} → ${r.status}`);
  return data;
}
const fetchPendingApprovals = async () =>
  (await apiGet("/api/v2/approvals?status=pending"))?.pending ?? [];
const fetchRecentApprovals = async () => {
  try { return (await apiGet("/api/v2/approvals?status=approved&since=24h"))?.recent ?? []; }
  catch { return []; }
};
function ageString(iso) {
  if (!iso) return "unknown";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "unknown";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
function ageBucket(iso) {
  if (!iso) return "";
  const h = (Date.now() - new Date(iso).getTime()) / 3600000;
  return h < 1 ? "1h" : h < 24 ? "24h" : h < 168 ? "7d" : "stale";
}
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else if (v != null && v !== false) n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
}
function passesFilters(a) {
  const { phase, project, age } = state.filters;
  if (phase && a.phase !== phase) return false;
  if (project && String(a.project_id) !== project) return false;
  if (age) {
    const buckets = { "1h": ["1h"], "24h": ["1h", "24h"], "7d": ["1h", "24h", "7d"], "stale": ["stale"] };
    if (!buckets[age]?.includes(ageBucket(a.last_decided_at))) return false;
  }
  return true;
}
function renderProjectFilter() {
  const sel = $("f-project"); const seen = new Set();
  const opts = [el("option", { value: "" }, "All")];
  for (const a of state.pending) {
    const k = String(a.project_id);
    if (seen.has(k)) continue; seen.add(k);
    opts.push(el("option", { value: k, ...(k === state.filters.project ? { selected: true } : {}) },
      `${a.name || k} (#${k})`));
  }
  sel.replaceChildren(...opts);
}
function renderCard(a) {
  const approvers = a.required_approvers?.length ? a.required_approvers.join(", ") : "user";
  return el("article", { class: "card pending", "data-pid": a.project_id, tabindex: "0" },
    el("div", { class: "card-head" },
      el("div", { class: "card-title" },
        el("span", { class: "role-name" }, a.name || `project #${a.project_id}`),
        el("span", { class: "mini-pill" }, a.phase || "?")),
      el("div", { class: "card-tags" }, el("span", { class: "badge state-pending" }, "pending"))),
    el("dl", { class: "kv" },
      el("dt", {}, "Project ID"), el("dd", {}, el("code", {}, String(a.project_id))),
      el("dt", {}, "Phase"),      el("dd", {}, a.phase || "—"),
      el("dt", {}, "Artifact"),   el("dd", {}, el("code", {}, a.artifact_ref || "—")),
      el("dt", {}, "Status"),     el("dd", {}, a.status || "active"),
      el("dt", {}, "Age"),        el("dd", {}, ageString(a.last_decided_at)),
      el("dt", {}, "Required"),   el("dd", {}, approvers)),
    el("div", { class: "card-actions" },
      el("button", { type: "button", class: "primary", onclick: () => openReviewModal(a) }, "Review Artifact"),
      el("button", { type: "button", class: "ok",      onclick: () => quickAction(a, "approve") }, "Approve"),
      el("button", { type: "button", class: "danger",  onclick: () => quickAction(a, "reject") }, "Reject"),
      el("button", { type: "button", class: "warn",    onclick: () => quickAction(a, "request_changes") }, "Request Changes")));
}
function renderQueue() {
  const items = state.pending.filter(passesFilters);
  $("pending-count").textContent = items.length;
  $("queue-empty").hidden = items.length !== 0;
  $("queue-list").replaceChildren(...items.map(renderCard));
  renderProjectFilter();
}
function renderRecent() {
  $("recent-count").textContent = state.recent.length;
  const has = state.recent.length > 0;
  $("recent-table").hidden = !has; $("recent-empty").hidden = has;
  $("recent-rows").replaceChildren(...state.recent.map((r) => el("tr", {},
    el("td", {}, el("code", {}, r.name || String(r.project_id))),
    el("td", {}, r.phase || "—"),
    el("td", {}, ageString(r.granted_at || r.last_decided_at)),
    el("td", {}, r.approver || "—"))));
}
async function quickAction(a, action) {
  if (action === "approve") return doAction(a, "approve", "");
  state.current = a; openReviewModal(a, action);
}
async function doAction(a, action, notes) {
  if (!state.settings.approver) {
    toast("Set your approver identity in Settings first.", "warn");
    $("settings-modal").showModal(); return;
  }
  const snapshot = state.pending.slice(); // optimistic remove
  state.pending = state.pending.filter((x) => !(x.project_id === a.project_id && x.phase === a.phase));
  renderQueue();
  try {
    const res = await apiPost("/api/v2/approvals", {
      project_id: a.project_id, phase: a.phase, action,
      approver: state.settings.approver, notes: notes || "",
    });
    toast(`${action.replace("_", " ")} ok${res?.new_phase ? ` → ${res.new_phase}` : ""}`, "ok");
    closeReviewModal();
    await refresh();
  } catch (e) {
    state.pending = snapshot; renderQueue(); // revert
    toast(`Action failed: ${e.message}`, "err");
  }
}
const approveAction        = (pid, phase, notes)  => doAction({ project_id: pid, phase }, "approve", notes);
const rejectAction         = (pid, phase, reason) => doAction({ project_id: pid, phase }, "reject", reason);
const requestChangesAction = (pid, phase, notes)  => doAction({ project_id: pid, phase }, "request_changes", notes);
async function openReviewModal(a, preset = "") {
  state.current = a;
  $("rm-title").textContent = `${a.name || "project #" + a.project_id} — ${a.phase}`;
  $("rm-sub").textContent = a.artifact_ref || "";
  $("rm-meta").textContent = `Project #${a.project_id} - Status ${a.status || "active"} - Age ${ageString(a.last_decided_at)}`;
  $("rm-doc").textContent = "Loading artifact…";
  $("rm-notes").value = "";
  $("rm-notes-wrap").hidden = !(preset === "reject" || preset === "request_changes");
  const m = $("review-modal"); m.showModal?.() ?? m.setAttribute("open", "");
  try {
    const ref = a.artifact_ref || "";
    if (!ref || ref.startsWith("phase:")) { $("rm-doc").textContent = `(no artifact bound; phase=${a.phase})`; return; }
    const r = await fetch(`${state.settings.apiBase}/api/v2/artifacts?path=${encodeURIComponent(ref)}`);
    $("rm-doc").textContent = r.ok ? await r.text() : `(artifact unavailable: ${r.status})`;
  } catch (e) {
    $("rm-doc").textContent = `(failed to load artifact: ${e.message})`;
  }
}
function closeReviewModal() {
  const m = $("review-modal"); m.close?.() ?? m.removeAttribute("open"); state.current = null;
}
let toastTimer = null;
function toast(msg, kind = "ok") {
  const t = $("toast"); t.textContent = msg; t.className = `toast show kind-${kind}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}
async function refresh() {
  $("queue-body").setAttribute("aria-busy", "true");
  try {
    const [p, r] = await Promise.all([fetchPendingApprovals(), fetchRecentApprovals()]);
    state.pending = p; state.recent = r;
    renderQueue(); renderRecent();
    $("last-sync").textContent = "synced " + new Date().toLocaleTimeString();
  } catch (e) {
    toast(`Refresh failed: ${e.message}`, "err");
  } finally {
    $("queue-body").setAttribute("aria-busy", "false");
  }
}
function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refresh, Math.max(2, Number(state.settings.pollSec) || 10) * 1000);
}
function modalAction(action) {
  if (!state.current) return;
  const notes = $("rm-notes").value.trim();
  if (action !== "approve" && !notes) {
    $("rm-notes-wrap").hidden = false;
    toast(`${action === "reject" ? "Reason" : "Notes"} required`, "warn");
    return;
  }
  doAction(state.current, action, notes);
}
function wire() {
  $("btn-refresh").onclick = refresh;
  $("btn-settings").onclick = () => {
    $("opt-approver").value = state.settings.approver;
    $("opt-poll").value     = state.settings.pollSec;
    $("opt-api").value      = state.settings.apiBase;
    $("settings-modal").showModal();
  };
  $("sm-close").onclick = () => $("settings-modal").close();
  $("sm-save").onclick = () => {
    state.settings.approver = $("opt-approver").value.trim();
    state.settings.pollSec  = Number($("opt-poll").value) || 10;
    state.settings.apiBase  = $("opt-api").value.trim() || DEFAULTS.apiBase;
    saveSettings(); startPolling(); $("settings-modal").close();
    toast("Settings saved", "ok");
  };
  for (const id of ["f-phase", "f-project", "f-age"]) {
    $(id).addEventListener("change", (e) => { state.filters[id.slice(2)] = e.target.value; renderQueue(); });
  }
  $("rm-close").onclick = closeReviewModal;
  $("rm-cancel").onclick = closeReviewModal;
  $("rm-approve").onclick = () => modalAction("approve");
  $("rm-reject").onclick  = () => modalAction("reject");
  $("rm-changes").onclick = () => modalAction("request_changes");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeReviewModal();
    if (e.key === "r" && !e.target.matches("input,textarea,select")) refresh();
  });
}

loadSettings();
$("foot-api").textContent = state.settings.apiBase;
wire(); refresh(); startPolling();
window.SpineApprovals = { // exported for debugging / future tests
  refresh, approveAction, rejectAction, requestChangesAction,
  fetchPendingApprovals, fetchRecentApprovals, state,
};
