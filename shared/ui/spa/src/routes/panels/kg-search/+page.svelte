<!--
  Spine Hub SPA — KG Search panel (V3 Wave 3 part 2, Squad SPA3).

  Consumes the NEW backend at shared/api/routes/kg.py (shipped by this same squad):
    GET /api/v2/kg/search?q=...&project_id=...&repo=...      → KgSearchResponse
    GET /api/v2/kg/node/{node_id}?project_id=...&repo=...    → KgNodeDetail
    GET /api/v2/kg/callers/{symbol}?project_id=...&repo=...  → KgCallersResponse
    GET /api/v2/kg/impact/{file}?project_id=...&repo=...     → KgImpactResponse
    GET /api/v2/kg/owners/{path}?project_id=...&repo=...     → KgOwnersResponse

  Per design decisions:
    - #12 Cite-or-Refuse: the KG node IS the citation. Every result row
          renders a CitationChip; the side-panel actions (impact / callers /
          owners) all return citations[] too which we surface inline.
    - #27 "Smart Spine" / KG-anchored UX: this panel is the primary surface
          for navigating the structural KG without dropping to psql.
    - #28 Mobile-responsive: < md the side panel becomes a full-screen
          drawer; results stack single-column.

  Graph viz tradeoff: the side-panel neighborhood renders as a simple
  list-of-edges table — no d3 / cytoscape / sigma. Justified because (a)
  no npm install allowed in this squad, (b) we're typically working with
  < 50 neighbours per node, (c) accessibility is free (semantic HTML, tab
  order). A real graph viz is a Wave 4+ enhancement.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/stores';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { api } from '$lib/api/client';
  import type { Citation } from '$lib/api/types';

  // Mirror shared/api/routes/kg.py shapes (until codegen lands).
  interface KgResult {
    node_id: string;
    name: string;
    node_type: string;
    path: string;
    score: number;
    rationale?: string | null;
  }
  interface KgSearchResponse {
    ok: boolean;
    query: string;
    results: KgResult[];
    total: number;
    query_latency_ms: number;
    citations: Citation[];
  }
  interface KgEdge {
    from_node_id: string;
    to_node_id: string;
    edge_type: string;
  }
  interface KgNodeDetail {
    ok: boolean;
    node_id: string;
    node: KgResult | null;
    neighbors: KgResult[];
    edges: KgEdge[];
    citations: Citation[];
  }
  interface KgCaller {
    node_id: string;
    name: string;
    node_type: string;
    path: string;
    depth: number;
  }
  interface KgImpactNode {
    node_id: string;
    node_type: string;
    path: string;
    impact_distance: number;
    impact_kind: string;
  }
  interface KgOwner {
    owner_type: string;
    owner_id: string;
    confidence: number;
    via: string;
  }

  // Wave 4 will surface project/repo via a global picker store; for now we
  // read from query params with sane defaults that match the smoke test.
  let projectId = 'demo';
  let repo = 'spine';
  let query = '';

  let searching = false;
  let searchError: string | null = null;
  let lastResult: KgSearchResponse | null = null;

  let selected: KgResult | null = null;
  let detail: KgNodeDetail | null = null;
  let detailLoading = false;

  let actionLoading: 'callers' | 'impact' | 'owners' | null = null;
  let actionError: string | null = null;
  let callers: KgCaller[] = [];
  let impacts: KgImpactNode[] = [];
  let owners: KgOwner[] = [];
  let actionCitations: Citation[] = [];

  onMount(() => {
    const params = $page.url.searchParams;
    const seedQ = params.get('q');
    const seedNode = params.get('node');
    const p = params.get('project_id');
    const r = params.get('repo');
    if (p) projectId = p;
    if (r) repo = r;
    if (seedQ) {
      query = seedQ;
      void runSearch();
    }
    if (seedNode) {
      void loadNode({ node_id: seedNode, name: seedNode, node_type: '', path: '', score: 0 });
    }
  });

  async function runSearch() {
    const q = query.trim();
    if (!q) return;
    searching = true;
    searchError = null;
    try {
      const url = `/api/v2/kg/search?q=${encodeURIComponent(q)}&project_id=${encodeURIComponent(projectId)}&repo=${encodeURIComponent(repo)}`;
      lastResult = await api.get<KgSearchResponse>(url);
    } catch (err) {
      searchError = (err as Error).message || 'KG search failed';
      lastResult = null;
    } finally {
      searching = false;
    }
  }

  async function loadNode(r: KgResult) {
    selected = r;
    detailLoading = true;
    detail = null;
    callers = [];
    impacts = [];
    owners = [];
    actionCitations = [];
    actionError = null;
    try {
      const url = `/api/v2/kg/node/${encodeURIComponent(r.node_id)}?project_id=${encodeURIComponent(projectId)}&repo=${encodeURIComponent(repo)}`;
      detail = await api.get<KgNodeDetail>(url);
    } catch (err) {
      actionError = (err as Error).message || 'node detail failed';
    } finally {
      detailLoading = false;
      await tick();
    }
  }

  async function runCallers() {
    if (!selected) return;
    actionLoading = 'callers';
    actionError = null;
    try {
      const url = `/api/v2/kg/callers/${encodeURIComponent(selected.name || selected.node_id)}?project_id=${encodeURIComponent(projectId)}&repo=${encodeURIComponent(repo)}`;
      const resp = await api.get<{ callers: KgCaller[]; citations: Citation[] }>(url);
      callers = resp.callers ?? [];
      impacts = [];
      owners = [];
      actionCitations = resp.citations ?? [];
    } catch (err) {
      actionError = (err as Error).message || 'callers query failed';
    } finally {
      actionLoading = null;
    }
  }

  async function runImpact() {
    if (!selected) return;
    actionLoading = 'impact';
    actionError = null;
    try {
      const target = selected.path || selected.node_id;
      const url = `/api/v2/kg/impact/${encodeURIComponent(target)}?project_id=${encodeURIComponent(projectId)}&repo=${encodeURIComponent(repo)}&target_type=file`;
      const resp = await api.get<{ impacted: KgImpactNode[]; citations: Citation[] }>(url);
      impacts = resp.impacted ?? [];
      callers = [];
      owners = [];
      actionCitations = resp.citations ?? [];
    } catch (err) {
      actionError = (err as Error).message || 'impact query failed';
    } finally {
      actionLoading = null;
    }
  }

  async function runOwners() {
    if (!selected) return;
    actionLoading = 'owners';
    actionError = null;
    try {
      const target = selected.path || selected.name || selected.node_id;
      const url = `/api/v2/kg/owners/${encodeURIComponent(target)}?project_id=${encodeURIComponent(projectId)}&repo=${encodeURIComponent(repo)}`;
      const resp = await api.get<{ owners: KgOwner[]; citations: Citation[] }>(url);
      owners = resp.owners ?? [];
      callers = [];
      impacts = [];
      actionCitations = resp.citations ?? [];
    } catch (err) {
      actionError = (err as Error).message || 'owners query failed';
    } finally {
      actionLoading = null;
    }
  }

  function clearSelection() {
    selected = null;
    detail = null;
    callers = [];
    impacts = [];
    owners = [];
    actionCitations = [];
  }
</script>

<PanelHeader
  title="Knowledge graph search"
  subtitle="Search structural + semantic KG; per #12 every result IS a citation"
>
  <input
    class="rounded border border-surface-200 bg-white px-2 py-1 text-xs dark:border-surface-700 dark:bg-surface-800"
    placeholder="project_id"
    bind:value={projectId}
    aria-label="Project ID"
    data-testid="project-id"
  />
  <input
    class="rounded border border-surface-200 bg-white px-2 py-1 text-xs dark:border-surface-700 dark:bg-surface-800"
    placeholder="repo"
    bind:value={repo}
    aria-label="Repo"
    data-testid="repo"
  />
</PanelHeader>

<form
  class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center"
  on:submit|preventDefault={runSearch}
  data-testid="search-form"
>
  <input
    class="flex-1 rounded border border-surface-200 bg-white px-3 py-2 text-sm dark:border-surface-700 dark:bg-surface-800"
    type="search"
    placeholder="Search nodes by name, doc, or natural language…"
    bind:value={query}
    data-testid="search-input"
  />
  <button type="submit" class="btn-primary" disabled={searching || !query.trim()}
          data-testid="search-submit">
    {searching ? 'Searching…' : 'Search'}
  </button>
</form>

{#if searchError}
  <div class="mb-3"><ErrorBanner kind="error" message={searchError} onDismiss={() => (searchError = null)} /></div>
{/if}

<section class="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="kg-layout">
  <!-- Result list -->
  <div>
    {#if searching && !lastResult}
      <div class="flex items-center justify-center py-10"><LoadingSpinner label="Searching KG" /></div>
    {:else if !lastResult}
      <EmptyState
        title="Start searching"
        message="Enter a query above. Results are graph nodes; every node IS its own citation per #12."
      />
    {:else if lastResult.results.length === 0}
      <EmptyState title="No matches" message={`Nothing matched "${lastResult.query}".`} />
    {:else}
      <p class="mb-2 text-[0.65rem] text-surface-700 dark:text-surface-200">
        {lastResult.total} results in {lastResult.query_latency_ms}ms
      </p>
      <ul class="flex flex-col gap-2" data-testid="result-list">
        {#each lastResult.results as r (r.node_id)}
          <li>
            <button
              type="button"
              class="panel-card flex w-full flex-col items-start gap-1 text-left transition hover:ring-2 hover:ring-accent"
              class:ring-2={selected?.node_id === r.node_id}
              class:ring-accent={selected?.node_id === r.node_id}
              on:click={() => loadNode(r)}
              data-testid="result-row"
              data-node-id={r.node_id}
            >
              <div class="flex w-full items-center justify-between gap-2">
                <span class="truncate font-mono text-sm">{r.name || r.node_id}</span>
                <span class="rounded bg-surface-100 px-1.5 py-0.5 text-[0.6rem] uppercase text-surface-700 dark:bg-surface-700 dark:text-surface-200">
                  {r.node_type || '—'}
                </span>
              </div>
              {#if r.path}
                <span class="truncate font-mono text-[0.65rem] text-surface-700 dark:text-surface-200">
                  {r.path}
                </span>
              {/if}
              <div class="flex w-full items-center justify-between gap-2">
                <span class="text-[0.6rem] text-surface-700 dark:text-surface-200">
                  score: <b>{r.score.toFixed(2)}</b>{r.rationale ? ` · ${r.rationale}` : ''}
                </span>
                <CitationChip citation={{ type: 'kg_node', ref: r.node_id }} />
              </div>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <!-- Side panel: node detail + KG actions -->
  {#if selected}
    <aside class="panel-card flex flex-col gap-3" data-testid="node-detail">
      <header class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <h2 class="truncate text-sm font-semibold">{selected.name || selected.node_id}</h2>
          <p class="truncate font-mono text-[0.65rem] text-surface-700 dark:text-surface-200">
            {selected.path || selected.node_id}
          </p>
        </div>
        <button class="btn-ghost text-xs" on:click={clearSelection} aria-label="Close detail"
                data-testid="close-detail">×</button>
      </header>

      <div class="flex flex-wrap gap-1">
        <button class="btn-ghost text-xs" on:click={runCallers}
                disabled={actionLoading !== null} data-testid="action-callers">
          {actionLoading === 'callers' ? '…' : 'find_callers'}
        </button>
        <button class="btn-ghost text-xs" on:click={runImpact}
                disabled={actionLoading !== null} data-testid="action-impact">
          {actionLoading === 'impact' ? '…' : 'impact_radius'}
        </button>
        <button class="btn-ghost text-xs" on:click={runOwners}
                disabled={actionLoading !== null} data-testid="action-owners">
          {actionLoading === 'owners' ? '…' : 'who_owns'}
        </button>
      </div>

      {#if actionError}
        <ErrorBanner kind="error" message={actionError} onDismiss={() => (actionError = null)} />
      {/if}

      {#if detailLoading}
        <LoadingSpinner size="sm" label="Loading neighborhood" />
      {:else if detail}
        <details open class="text-xs">
          <summary class="cursor-pointer font-semibold">Neighborhood ({detail.neighbors.length} nodes / {detail.edges.length} edges)</summary>
          {#if detail.neighbors.length > 0}
            <ul class="mt-1 max-h-40 overflow-y-auto pl-4" data-testid="neighbor-list">
              {#each detail.neighbors as n (n.node_id)}
                <li class="truncate"><span class="font-mono">{n.name || n.node_id}</span> <span class="text-surface-700 dark:text-surface-200">({n.node_type})</span></li>
              {/each}
            </ul>
          {/if}
          {#if detail.edges.length > 0}
            <ul class="mt-1 max-h-40 overflow-y-auto pl-4 font-mono text-[0.65rem]" data-testid="edge-list">
              {#each detail.edges as e, i (i)}
                <li class="truncate">{e.from_node_id} —[{e.edge_type}]→ {e.to_node_id}</li>
              {/each}
            </ul>
          {/if}
        </details>
      {/if}

      {#if callers.length > 0}
        <div data-testid="callers-result">
          <h3 class="text-xs font-semibold">Callers</h3>
          <ul class="text-xs">
            {#each callers as c (c.node_id)}
              <li class="truncate">{c.name} <span class="text-surface-700 dark:text-surface-200">depth={c.depth}</span></li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if impacts.length > 0}
        <div data-testid="impact-result">
          <h3 class="text-xs font-semibold">Impact radius</h3>
          <ul class="text-xs">
            {#each impacts as i (i.node_id)}
              <li class="truncate">{i.path} <span class="text-surface-700 dark:text-surface-200">({i.impact_kind} d={i.impact_distance})</span></li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if owners.length > 0}
        <div data-testid="owners-result">
          <h3 class="text-xs font-semibold">Owners</h3>
          <ul class="text-xs">
            {#each owners as o (`${o.owner_type}:${o.owner_id}`)}
              <li class="truncate">{o.owner_type}:{o.owner_id} <span class="text-surface-700 dark:text-surface-200">conf={o.confidence.toFixed(2)} via {o.via}</span></li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if actionCitations.length > 0}
        <div class="flex flex-wrap gap-1" data-testid="action-citations">
          {#each actionCitations as cite, i (i)}
            <CitationChip citation={cite} />
          {/each}
        </div>
      {/if}
    </aside>
  {/if}
</section>
