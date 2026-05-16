/* activity-stream.js - STORY-1.6.2 (live phase indicator) + STORY-1.6.3 (role activity stream).
 * Polls /api/v2/audit per active project and merges into a single newest-first
 * stream. Deduplicates by event_id (or composite ts+actor+action key). Color
 * coded by subsystem. Click an event -> dashboard.js will surface the full
 * audit record (TODO once /api/v2/audit/{id} lands; today shows JSON inline).
 */
"use strict";

const STATE = new WeakMap();
const MAX_ITEMS = 200;

const WINDOWS = { "1h": 3600e3, "6h": 6 * 3600e3, "24h": 86400e3 };

function fmtTs(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function safeJson(s) { try { return JSON.parse(s); } catch { return null; } }

function eventKey(e) {
  return e.event_id ? `id:${e.event_id}` : `${e.ts || ""}|${e.actor || ""}|${e.action || ""}|${e.subject_id || ""}`;
}

async function fetchActiveProjectIds(ctx) {
  try {
    const r = await ctx.apiGet("/api/v2/projects?status=active");
    return (r?.items ?? [])
      .map((s) => (typeof s === "string" ? safeJson(s) : s))
      .filter(Boolean)
      .map((p) => ({ id: p.project_id || p.id, name: p.name }))
      .filter((x) => x.id != null);
  } catch { return []; }
}

async function fetchAudit(ctx, projectId, sinceMs) {
  try {
    const r = await ctx.apiGet(`/api/v2/audit?project_id=${encodeURIComponent(projectId)}&limit=200`);
    const items = (r?.items ?? []).map((s) => (typeof s === "string" ? safeJson(s) : s)).filter(Boolean);
    const cutoff = Date.now() - sinceMs;
    return items.filter((e) => new Date(e.ts || 0).getTime() >= cutoff);
  } catch { return []; }
}

function renderItem(ctx, st, e) {
  const sub = (e.subsystem || "shared").toLowerCase();
  const role = e.role || "-";
  const summary = `${e.action || "?"}${e.subject_type ? ` ${e.subject_type}` : ""}${e.subject_id ? ` #${e.subject_id}` : ""}`;
  const phaseChip = e.phase ? ` (${e.phase})` : "";
  const li = ctx.el("li", { class: "stream-item", "data-key": eventKey(e), title: "Click to inspect" },
    ctx.el("span", { class: "ts" }, fmtTs(e.ts)),
    ctx.el("span", { class: `subsystem sub-${sub}` }, sub),
    ctx.el("span", { class: "summary" },
      ctx.el("b", {}, role), " ",
      summary,
      phaseChip,
      e.rationale ? ctx.el("div", { class: "muted", style: "margin-top:2px;" }, e.rationale) : null),
    ctx.el("span", { class: "actor" }, e.actor || "-"));
  li.onclick = () => showDetail(ctx, st, e);
  return li;
}

function showDetail(ctx, st, e) {
  // Lightweight inline detail via alert-style toast; full detail modal can land
  // when /api/v2/audit/{id} ships. For now expose the JSON for debugging.
  ctx.toast(`${e.subsystem || "?"} :: ${e.action || "?"} :: ${e.actor || "?"}`, "ok");
  console.info("[activity] event detail", e);
}

function passesFilters(e, f) {
  if (f.project && String(e.project_id) !== String(f.project)) return false;
  if (f.role && e.role !== f.role) return false;
  return true;
}

function refreshDropdowns(container, st) {
  const doc = container.ownerDocument;
  const ps = doc.getElementById("af-project");
  const rs = doc.getElementById("af-role");
  const seed = (sel, vals) => {
    const cur = sel.value;
    const seen = new Set([""]); const opts = [];
    const all = doc.createElement("option"); all.value = ""; all.textContent = "All"; opts.push(all);
    for (const v of vals) {
      if (!v || seen.has(String(v))) continue; seen.add(String(v));
      const o = doc.createElement("option"); o.value = String(v); o.textContent = String(v);
      if (String(v) === cur) o.selected = true;
      opts.push(o);
    }
    sel.replaceChildren(...opts);
  };
  seed(ps, [...new Set(st.events.map((e) => e.project_id))].sort());
  seed(rs, [...new Set(st.events.map((e) => e.role).filter(Boolean))].sort());
}

async function render(container, ctx) {
  const st = STATE.get(container); if (!st) return;
  if (st.paused || ctx.isPaused()) return;
  const doc = container.ownerDocument;
  const host = doc.getElementById("activity-host"); host.setAttribute("aria-busy", "true");
  const sinceMs = WINDOWS[doc.getElementById("af-window").value] ?? WINDOWS["1h"];
  try {
    const projects = await fetchActiveProjectIds(ctx);
    const lists = await Promise.all(projects.slice(0, 25).map((p) => fetchAudit(ctx, p.id, sinceMs)));
    const incoming = lists.flat();
    // merge with prior, dedup
    const byKey = new Map(st.events.map((e) => [eventKey(e), e]));
    for (const e of incoming) byKey.set(eventKey(e), e);
    st.events = [...byKey.values()]
      .sort((a, b) => new Date(b.ts || 0) - new Date(a.ts || 0))
      .slice(0, MAX_ITEMS);
    refreshDropdowns(container, st);
    const f = { project: doc.getElementById("af-project").value, role: doc.getElementById("af-role").value };
    const view = st.events.filter((e) => passesFilters(e, f));
    doc.getElementById("activity-empty").hidden = view.length !== 0;
    doc.getElementById("activity-list").replaceChildren(...view.map((e) => renderItem(ctx, st, e)));
  } catch (e) {
    ctx.toast(`Activity load failed: ${e.message}`, "err");
  } finally {
    host.setAttribute("aria-busy", "false");
  }
}

export function mount(container, ctx) {
  const doc = container.ownerDocument;
  const st = { ctx, events: [], paused: false, timer: null };
  STATE.set(container, st);
  doc.getElementById("af-window").onchange = () => render(container, ctx);
  doc.getElementById("af-project").onchange = () => render(container, ctx);
  doc.getElementById("af-role").onchange    = () => render(container, ctx);
  const pauseBtn = doc.getElementById("af-pause");
  pauseBtn.onclick = () => {
    st.paused = !st.paused;
    pauseBtn.textContent = st.paused ? "Resume stream" : "Pause stream";
    ctx.toast(st.paused ? "Stream paused" : "Stream resumed", st.paused ? "warn" : "ok");
  };
  render(container, ctx);
  const period = Math.max(2, Number(ctx.settings.pollActivitySec) || 5) * 1000;
  st.timer = setInterval(() => render(container, ctx), period);
}

export function unmount(container) {
  const st = STATE.get(container);
  if (!st) return;
  clearInterval(st.timer);
  STATE.delete(container);
}
