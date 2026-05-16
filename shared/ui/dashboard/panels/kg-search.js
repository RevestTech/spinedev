/* kg-search.js - Knowledge Graph hybrid_search panel.
 * Submits to /api/v2/kg/hybrid_search (REST proxy in front of the MCP server).
 * Renders results as a sortable table with quick-action buttons (Find callers,
 * Impact radius) per row. Tracks query analytics in localStorage so the "Top
 * Queried Nodes" sidebar shows what the operator looks at most.
 */
"use strict";

const STATE = new WeakMap();
const ANALYTICS_KEY = "spine.dashboard.kg.analytics.v1";
const MAX_ANALYTICS = 25;

function loadAnalytics() {
  try { return JSON.parse(localStorage.getItem(ANALYTICS_KEY) || "{}"); } catch { return {}; }
}
function saveAnalytics(a) {
  try { localStorage.setItem(ANALYTICS_KEY, JSON.stringify(a)); } catch { /* ignore quota */ }
}
function bumpAnalytics(node) {
  const a = loadAnalytics();
  const k = node.path || node.name || node.id;
  if (!k) return;
  a[k] = (a[k] || 0) + 1;
  saveAnalytics(a);
}

function renderTopQueried(container) {
  const a = loadAnalytics();
  const entries = Object.entries(a).sort((x, y) => y[1] - x[1]).slice(0, 10);
  const doc = container.ownerDocument;
  const host = doc.getElementById("kg-top");
  if (!entries.length) {
    host.innerHTML = "<div class='empty'>No queries yet.</div>";
    return;
  }
  const ol = doc.createElement("ol");
  for (const [k, v] of entries) {
    const li = doc.createElement("li");
    const code = doc.createElement("code"); code.textContent = k;
    li.append(code, ` x${v}`);
    ol.append(li);
  }
  host.replaceChildren(ol);
}

function sortBy(rows, col, dir) {
  const mult = dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const av = a[col] ?? ""; const bv = b[col] ?? "";
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
    return String(av).localeCompare(String(bv)) * mult;
  });
}

function renderResults(ctx, container, st) {
  const doc = container.ownerDocument;
  const host = doc.getElementById("kg-results");
  if (!st.results.length) {
    host.innerHTML = "<div class='empty'>No matches.</div>";
    return;
  }
  const rows = sortBy(st.results, st.sortCol, st.sortDir);
  const table = doc.createElement("table");
  const thead = doc.createElement("thead");
  const trh = doc.createElement("tr");
  const COLS = [
    ["name", "Name"], ["type", "Type"], ["path", "Path"],
    ["semantic_score", "Semantic"], ["structural_score", "Structural"],
    ["rationale", "Rationale"], ["_actions", "Actions"],
  ];
  for (const [k, label] of COLS) {
    const th = doc.createElement("th");
    th.textContent = label + (k === st.sortCol ? (st.sortDir === "desc" ? " v" : " ^") : "");
    th.onclick = () => {
      if (k.startsWith("_")) return;
      if (st.sortCol === k) st.sortDir = st.sortDir === "desc" ? "asc" : "desc";
      else { st.sortCol = k; st.sortDir = "desc"; }
      renderResults(ctx, container, st);
    };
    trh.append(th);
  }
  thead.append(trh); table.append(thead);
  const tbody = doc.createElement("tbody");
  for (const r of rows) {
    const tr = doc.createElement("tr");
    const cells = [
      r.name || "-",
      r.type || "-",
      r.path ? ctx.el("code", {}, r.path) : "-",
      Number(r.semantic_score ?? 0).toFixed(3),
      Number(r.structural_score ?? 0).toFixed(3),
      (r.rationale || "").slice(0, 140),
    ];
    for (const c of cells) {
      const td = doc.createElement("td");
      td.append(c.nodeType ? c : doc.createTextNode(String(c)));
      tr.append(td);
    }
    const actTd = doc.createElement("td");
    actTd.append(
      ctx.el("div", { class: "kg-actions" },
        ctx.el("button", { class: "ghost",
          onclick: () => runQuickAction(ctx, container, st, "find_callers", r) }, "Find callers"),
        ctx.el("button", { class: "ghost",
          onclick: () => runQuickAction(ctx, container, st, "impact_radius", r) }, "Impact radius")));
    tr.append(actTd);
    tr.onclick = (ev) => { if (ev.target.tagName === "BUTTON") return; bumpAnalytics(r); renderTopQueried(container); };
    tbody.append(tr);
  }
  table.append(tbody);
  host.replaceChildren(table);
}

async function runQuickAction(ctx, container, st, action, node) {
  bumpAnalytics(node);
  renderTopQueried(container);
  try {
    const res = await ctx.apiPost("/api/v2/kg/hybrid_search", {
      query: `${action} ${node.path || node.name}`, type: "", limit: 25, action,
    });
    st.results = Array.isArray(res?.results) ? res.results : (res?.items ?? []);
    renderResults(ctx, container, st);
    ctx.toast(`${action} returned ${st.results.length} nodes`, "ok");
  } catch (e) {
    ctx.toast(`${action} failed: ${e.message}`, "err");
  }
}

async function doSearch(ctx, container, st) {
  const doc = container.ownerDocument;
  const q = doc.getElementById("kg-query").value.trim();
  const type = doc.getElementById("kg-type").value;
  const limit = Number(doc.getElementById("kg-limit").value) || 25;
  if (!q) { ctx.toast("Enter a query first", "warn"); return; }
  doc.getElementById("kg-results").innerHTML = "<div class='empty'>Searching...</div>";
  try {
    const res = await ctx.apiPost("/api/v2/kg/hybrid_search", { query: q, type, limit });
    st.results = Array.isArray(res?.results) ? res.results : (res?.items ?? []);
    renderResults(ctx, container, st);
  } catch (e) {
    doc.getElementById("kg-results").innerHTML = "";
    ctx.toast(`KG search failed: ${e.message}`, "err");
  }
}

export function mount(container, ctx) {
  const doc = container.ownerDocument;
  const st = { ctx, results: [], sortCol: "semantic_score", sortDir: "desc" };
  STATE.set(container, st);
  doc.getElementById("kg-form").onsubmit = (e) => { e.preventDefault(); doSearch(ctx, container, st); };
  doc.getElementById("kg-go").onclick = () => doSearch(ctx, container, st);
  renderTopQueried(container);
}

export function unmount(container) { STATE.delete(container); }
