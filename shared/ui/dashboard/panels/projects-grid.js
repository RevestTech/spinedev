/* projects-grid.js - STORY-9.9.4 dashboard tile grid.
 * Fetches /api/v2/projects?status=active and renders a tile per project.
 * Tiles surface name, current phase (color coded), pending approvals badge,
 * today's cost, age, owner. Click drills into the detail modal hosted in
 * dashboard.js. Supports filter by status/phase/owner and sort by age/cost.
 *
 * Lifecycle: mount(container, ctx) starts polling at ctx.settings.pollProjectsSec;
 * unmount(container) clears the timer.
 */
"use strict";

const STATE = new WeakMap(); // container -> { timer, ctx, all, filters, sort }

const PHASE_CLASS = {
  intake: "phase-intake",
  plan: "phase-plan", plan_approved: "phase-plan", plan_in_progress: "phase-plan",
  build: "phase-build", build_in_progress: "phase-build", build_complete: "phase-build",
  verify: "phase-verify", verify_in_progress: "phase-verify", verify_approved: "phase-verify",
  acceptance: "phase-acceptance",
  retro: "phase-retro",
};

function phaseClass(phase) {
  if (!phase) return "phase-intake";
  for (const [k, v] of Object.entries(PHASE_CLASS)) if (phase.includes(k)) return v;
  return "phase-intake";
}

function ageString(iso) {
  if (!iso) return "unknown";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "unknown";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function readFilters(container) {
  const $ = (id) => container.ownerDocument.getElementById(id);
  return {
    status: $("pf-status").value,
    phase:  $("pf-phase").value,
    owner:  $("pf-owner").value,
    sort:   $("pf-sort").value,
  };
}

function applyFilters(projects, f) {
  let out = projects.filter((p) => {
    if (f.phase && p.current_phase !== f.phase) return false;
    if (f.owner && (p.owner || p.owner_user || "") !== f.owner) return false;
    return true;
  });
  if (f.sort === "age") out.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
  else if (f.sort === "cost") out.sort((a, b) => (b._cost_today ?? 0) - (a._cost_today ?? 0));
  else if (f.sort === "name") out.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  else out.sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
  return out;
}

function renderTile(ctx, p) {
  const phase = p.current_phase || "intake";
  const pending = p._pending_approvals ?? 0;
  const cost = Number(p._cost_today ?? 0).toFixed(2);
  return ctx.el("article", {
      class: "tile",
      "data-pid": p.project_id || p.id,
      tabindex: "0",
      role: "button",
      onclick: () => ctx.openProjectDetail(p.project_id || p.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") ctx.openProjectDetail(p.project_id || p.id); },
    },
    ctx.el("div", { class: "tile-head" },
      ctx.el("div", { class: "tile-name" }, p.name || `Project ${p.project_id}`),
      ctx.el("div", { class: "tile-badges" },
        ctx.el("span", { class: `badge badge-phase ${phaseClass(phase)}` }, phase),
        pending > 0 ? ctx.el("span", { class: "badge badge-pending" }, `${pending} pending`) : null)),
    ctx.el("dl", { class: "tile-meta" },
      ctx.el("div", {}, "Status"),  ctx.el("b", {}, p.status || "active"),
      ctx.el("div", {}, "Owner"),   ctx.el("b", {}, p.owner || p.owner_user || "-"),
      ctx.el("div", {}, "Today"),   ctx.el("b", {}, `$${cost}`),
      ctx.el("div", {}, "Age"),     ctx.el("b", {}, ageString(p.created_at)),
      ctx.el("div", {}, "Updated"), ctx.el("b", {}, ageString(p.updated_at) + " ago")));
}

function refreshDropdowns(container, projects) {
  const doc = container.ownerDocument;
  const phaseSel = doc.getElementById("pf-phase");
  const ownerSel = doc.getElementById("pf-owner");
  const seedSelect = (sel, values) => {
    const cur = sel.value;
    const seen = new Set([""]);
    const opts = [doc.createElement("option")];
    opts[0].value = ""; opts[0].textContent = "All";
    for (const v of values) {
      if (!v || seen.has(v)) continue; seen.add(v);
      const o = doc.createElement("option"); o.value = v; o.textContent = v;
      if (v === cur) o.selected = true;
      opts.push(o);
    }
    sel.replaceChildren(...opts);
  };
  seedSelect(phaseSel, projects.map((p) => p.current_phase).sort());
  seedSelect(ownerSel, projects.map((p) => p.owner || p.owner_user).filter(Boolean).sort());
}

async function fetchProjects(ctx, statusFilter) {
  const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
  const resp = await ctx.apiGet(`/api/v2/projects${qs}`);
  const items = Array.isArray(resp?.items) ? resp.items.map((s) => {
    // /api/v2/projects returns rows as JSON strings (json_build_object::text).
    return typeof s === "string" ? safeJson(s) : s;
  }).filter(Boolean) : [];
  // Best-effort enrichment for today's cost + pending approvals via /healthz +
  // /api/v2/approvals fan-out. Production swap: server-side join.
  try {
    const pend = await ctx.apiGet("/api/v2/approvals?status=pending");
    const counts = {};
    for (const a of pend?.pending ?? []) {
      const k = String(a.project_id);
      counts[k] = (counts[k] || 0) + 1;
    }
    for (const p of items) p._pending_approvals = counts[String(p.project_id || p.id)] || 0;
  } catch { /* approvals proxy may be unwired */ }
  return items;
}

function safeJson(s) { try { return JSON.parse(s); } catch { return null; } }

async function render(container, ctx) {
  const st = STATE.get(container);
  if (!st || ctx.isPaused()) return;
  const f = readFilters(container);
  st.filters = f;
  const doc = container.ownerDocument;
  const host = doc.getElementById("projects-host");
  host.setAttribute("aria-busy", "true");
  try {
    const items = await fetchProjects(ctx, f.status);
    st.all = items;
    refreshDropdowns(container, items);
    const filtered = applyFilters(items, readFilters(container));
    doc.getElementById("projects-empty").hidden = filtered.length !== 0;
    doc.getElementById("projects-tiles").replaceChildren(...filtered.map((p) => renderTile(ctx, p)));
  } catch (e) {
    ctx.toast(`Projects load failed: ${e.message}`, "err");
  } finally {
    host.setAttribute("aria-busy", "false");
  }
}

export function mount(container, ctx) {
  const doc = container.ownerDocument;
  const st = { ctx, all: [], filters: null, timer: null };
  STATE.set(container, st);
  ["pf-status", "pf-phase", "pf-owner", "pf-sort"].forEach((id) => {
    const sel = doc.getElementById(id);
    sel.onchange = () => {
      if (id === "pf-status") render(container, ctx);
      else {
        const filtered = applyFilters(st.all, readFilters(container));
        doc.getElementById("projects-empty").hidden = filtered.length !== 0;
        doc.getElementById("projects-tiles").replaceChildren(...filtered.map((p) => renderTile(ctx, p)));
      }
    };
  });
  render(container, ctx);
  const period = Math.max(2, Number(ctx.settings.pollProjectsSec) || 10) * 1000;
  st.timer = setInterval(() => render(container, ctx), period);
}

export function unmount(container) {
  const st = STATE.get(container);
  if (!st) return;
  clearInterval(st.timer);
  STATE.delete(container);
}
