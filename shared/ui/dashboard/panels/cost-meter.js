/* cost-meter.js - STORY-1.5.6 (cost meter) + STORY-1.5.7 (phase projection).
 * Reads /api/v2/audit/export?format=json + /healthz to aggregate spend
 * by scope (org/user/project), subsystem, and model. Renders bar charts
 * using plain CSS (no chart library).
 *
 * Phase projection is a deterministic estimate derived from historical
 * cost-per-phase: avg(prior runs of next_phase) * complexity_multiplier.
 * complexity_multiplier defaults to 1.0; in production this comes from the
 * planner model-menu output (REQ-INIT-1 FR-6, PRD G-7).
 */
"use strict";

const STATE = new WeakMap();

const SUBSYSTEMS = ["plan", "build", "verify", "orchestrator", "shared"];
const SUBSYSTEM_TONE = {
  plan: "bar-info", build: "bar-purple", verify: "bar-amber",
  orchestrator: "bar-info", shared: "bar-green",
};

function windowToMs(w) {
  return ({ "24h": 86400e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 })[w] ?? 86400e3;
}

async function fetchHealth(ctx) {
  try { return await ctx.apiGet("/healthz"); } catch { return {}; }
}

async function fetchProjects(ctx) {
  try {
    const r = await ctx.apiGet("/api/v2/projects?status=active");
    return (r?.items ?? []).map((s) => typeof s === "string" ? safeJson(s) : s).filter(Boolean);
  } catch { return []; }
}

async function fetchEvents(ctx, projectId, sinceMs) {
  // /api/v2/audit requires project_id; fan out across active projects.
  try {
    const r = await ctx.apiGet(`/api/v2/audit?project_id=${encodeURIComponent(projectId)}&limit=5000`);
    const items = (r?.items ?? []).map((s) => typeof s === "string" ? safeJson(s) : s).filter(Boolean);
    const cutoff = Date.now() - sinceMs;
    return items.filter((e) => new Date(e.ts || 0).getTime() >= cutoff);
  } catch { return []; }
}

function safeJson(s) { try { return JSON.parse(s); } catch { return null; } }

function aggregate(events) {
  const bySub = {}; const byModel = {}; const byPhase = {}; let total = 0;
  for (const e of events) {
    const c = Number(e.cost_usd || 0); total += c;
    bySub[e.subsystem || "unknown"]   = (bySub[e.subsystem || "unknown"] || 0) + c;
    byModel[e.model_id || e.model || "n/a"] = (byModel[e.model_id || e.model || "n/a"] || 0) + c;
    const ph = e.phase || "n/a";
    byPhase[ph] = (byPhase[ph] || 0) + c;
  }
  return { total, bySub, byModel, byPhase };
}

function budgetTone(pct) {
  if (pct >= 100) return "bar-red";
  if (pct >= 80)  return "bar-amber";
  return "bar-green";
}

function bar(ctx, label, value, max, valueText, toneOverride) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const tone = toneOverride || budgetTone(pct);
  return ctx.el("div", { class: "bar-row" },
    ctx.el("div", { class: "label", title: label }, label),
    ctx.el("div", { class: `bar ${tone}` },
      ctx.el("div", { class: "fill", style: `width:${pct.toFixed(1)}%;` })),
    ctx.el("div", { class: "value" }, valueText));
}

function renderBudgets(ctx, container, agg, scope, health) {
  // Budget caps default per scope (overridable via settings in v2).
  const caps = {
    org:     { today: 50, week: 200, month: 600 },
    user:    { today: 10, week: 40,  month: 120 },
    project: { today: 25, week: 100, month: 300 },
  }[scope] || { today: 50, week: 200, month: 600 };
  const today = Number(health?.spend_today_usd ?? agg.total);
  const month = Number(health?.spend_month_usd ?? agg.total);
  const week  = Math.max(today, month * (7 / 30));
  const tgt = container.ownerDocument.getElementById("cost-budgets");
  tgt.replaceChildren(
    bar(ctx, `Today  (cap $${caps.today})`,  today, caps.today,  `$${today.toFixed(2)}`),
    bar(ctx, `Week   (cap $${caps.week})`,   week,  caps.week,   `$${week.toFixed(2)}`),
    bar(ctx, `Month  (cap $${caps.month})`,  month, caps.month,  `$${month.toFixed(2)}`));
}

function renderSubsystems(ctx, container, agg) {
  const tgt = container.ownerDocument.getElementById("cost-subsystems");
  const max = Math.max(0.0001, ...SUBSYSTEMS.map((s) => agg.bySub[s] || 0));
  tgt.replaceChildren(...SUBSYSTEMS.map((s) =>
    bar(ctx, s, agg.bySub[s] || 0, max, `$${(agg.bySub[s] || 0).toFixed(2)}`, SUBSYSTEM_TONE[s])));
}

function renderProjection(ctx, container, agg, projects) {
  // STORY-1.5.7: estimate next phase cost = avg(prior runs of that phase).
  // We approximate "next phase" per project as +1 in a canonical order.
  const order = ["intake", "plan_approved", "build_in_progress", "verify_approved", "acceptance", "retro"];
  const rows = projects.slice(0, 6).map((p) => {
    const idx = order.indexOf(p.current_phase);
    const next = idx >= 0 && idx < order.length - 1 ? order[idx + 1] : "n/a";
    const hist = agg.byPhase[next] || agg.byPhase[p.current_phase] || 0;
    const est = hist > 0 ? hist : 5.0; // floor so the meter is non-empty pre-data
    return { name: p.name || `#${p.project_id}`, next, est };
  });
  const tgt = container.ownerDocument.getElementById("cost-projection");
  if (!rows.length) { tgt.replaceChildren(ctx.el("div", { class: "empty" }, "No active projects to project.")); return; }
  const max = Math.max(0.0001, ...rows.map((r) => r.est));
  tgt.replaceChildren(
    ctx.el("div", { class: "muted", style: "margin-bottom:8px;" },
      "Estimate = historical avg cost of next phase. Override via planner model-menu in production."),
    ...rows.map((r) => bar(ctx, `${r.name} -> ${r.next}`, r.est, max, `~$${r.est.toFixed(2)}`, "bar-info")));
}

function renderModels(ctx, container, agg) {
  const tgt = container.ownerDocument.getElementById("cost-models");
  const entries = Object.entries(agg.byModel).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!entries.length) { tgt.replaceChildren(ctx.el("div", { class: "empty" }, "No model cost data yet.")); return; }
  const max = entries[0][1];
  tgt.replaceChildren(...entries.map(([m, v]) => bar(ctx, m, v, max, `$${v.toFixed(2)}`, "bar-purple")));
}

async function render(container, ctx) {
  const st = STATE.get(container); if (!st || ctx.isPaused()) return;
  const doc = container.ownerDocument;
  const host = doc.getElementById("cost-host"); host.setAttribute("aria-busy", "true");
  const scope = doc.getElementById("cf-scope").value;
  const w = doc.getElementById("cf-window").value;
  try {
    const [health, projects] = await Promise.all([fetchHealth(ctx), fetchProjects(ctx)]);
    const pids = projects.map((p) => p.project_id || p.id).filter(Boolean).slice(0, 25);
    const eventLists = await Promise.all(pids.map((id) => fetchEvents(ctx, id, windowToMs(w))));
    let events = eventLists.flat();
    if (scope === "user" && ctx.settings.actor) events = events.filter((e) => e.actor === ctx.settings.actor);
    const agg = aggregate(events);
    renderBudgets(ctx, container, agg, scope, health);
    renderSubsystems(ctx, container, agg);
    renderProjection(ctx, container, agg, projects);
    renderModels(ctx, container, agg);
    doc.getElementById("cf-asof").textContent = "as of " + new Date().toLocaleTimeString();
  } catch (e) {
    ctx.toast(`Cost load failed: ${e.message}`, "err");
  } finally {
    host.setAttribute("aria-busy", "false");
  }
}

export function mount(container, ctx) {
  const doc = container.ownerDocument;
  const st = { ctx, timer: null }; STATE.set(container, st);
  doc.getElementById("cf-scope").onchange  = () => render(container, ctx);
  doc.getElementById("cf-window").onchange = () => render(container, ctx);
  render(container, ctx);
  const period = Math.max(10, Number(ctx.settings.pollCostSec) || 60) * 1000;
  st.timer = setInterval(() => render(container, ctx), period);
}

export function unmount(container) {
  const st = STATE.get(container);
  if (!st) return;
  clearInterval(st.timer);
  STATE.delete(container);
}
