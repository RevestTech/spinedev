<!--
  AgentAuditOverview (Path A T20).

  Displays the 12-layer audit (V3 B10 — verify/agent_audit/twelve_layer.py)
  as a status grid with drill-down. Status per layer is coloured;
  click expands the finding's evidence + next_actions.

  The audit itself is read on demand from
  `/api/v2/audit/agent_audit_scan` (a thin route that wraps
  `scan_agent_stack`). The component holds the latest report in
  local state; pinging the route re-fetches.

  This is the only Path A surface that pings the server directly
  rather than reading from projectEvents — the audit is repo-wide,
  not project-scoped, so there's no realtime event channel for it.
-->
<script lang="ts">
  export interface LayerFinding {
    layer: string;
    status: 'clean' | 'warning' | 'regressed' | 'instrumentation_pending';
    summary: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    evidence?: string[];
    next_actions?: string[];
  }

  export interface AgentAuditReport {
    findings: LayerFinding[];
    overall_status: 'clean' | 'warning' | 'regressed' | 'instrumentation_pending';
  }

  /**
   * Either pass `report` directly (tests / parent already fetched)
   * or supply `loader` and the component calls it on mount.
   */
  export let report: AgentAuditReport | null = null;
  export let loader: (() => Promise<AgentAuditReport>) | null = null;

  let loading = false;
  let error: string | null = null;
  let expanded = new Set<string>();

  async function load(): Promise<void> {
    if (!loader) return;
    loading = true;
    error = null;
    try {
      report = await loader();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function toggle(layer: string): void {
    if (expanded.has(layer)) {
      expanded.delete(layer);
    } else {
      expanded.add(layer);
    }
    expanded = new Set(expanded);
  }

  function tone(status: LayerFinding['status']): string {
    if (status === 'clean') return 'bg-emerald-50 border-emerald-300 text-emerald-800';
    if (status === 'warning') return 'bg-amber-50 border-amber-300 text-amber-800';
    if (status === 'regressed') return 'bg-red-50 border-red-300 text-red-800';
    return 'bg-slate-50 border-slate-300 text-slate-700';
  }

  if (loader && !report) {
    void load();
  }
</script>

<section class="agent-audit-overview flex flex-col gap-2" aria-label="12-layer agent audit">
  <header class="flex items-center gap-2">
    <span class="text-sm font-semibold text-slate-800">12-layer agent audit</span>
    {#if report}
      <span class="text-xs px-2 py-0.5 rounded-full border {tone(report.overall_status)}" data-testid="overall">
        overall {report.overall_status}
      </span>
    {/if}
    {#if loader}
      <button
        type="button"
        class="ml-auto text-xs px-2 py-0.5 border rounded hover:bg-slate-50"
        on:click={load}
        disabled={loading}
        data-testid="refresh"
      >
        {loading ? 'scanning…' : 'Refresh'}
      </button>
    {/if}
  </header>

  {#if error}
    <p class="text-sm text-red-700" data-testid="error">{error}</p>
  {/if}

  {#if !report}
    <p class="text-sm text-slate-500 italic" data-testid="empty">
      No audit report loaded yet.
    </p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each report.findings as f (f.layer)}
        <li
          class="border rounded-md px-2 py-1 text-xs cursor-pointer {tone(f.status)}"
          data-testid="finding-row"
          data-status={f.status}
          on:click={() => toggle(f.layer)}
          on:keypress={(e) => e.key === 'Enter' && toggle(f.layer)}
          role="button"
          tabindex="0"
        >
          <div class="flex items-center gap-2">
            <span class="font-mono text-[0.7rem] uppercase tracking-wide opacity-70">
              {f.layer}
            </span>
            <span class="font-semibold uppercase tracking-wide text-[0.65rem]">
              {f.status}
            </span>
            <span class="flex-1 truncate">{f.summary}</span>
            <span class="text-[0.65rem] opacity-70">{f.severity}</span>
          </div>
          {#if expanded.has(f.layer)}
            <div class="mt-1 text-[0.7rem]" data-testid="finding-expanded">
              {#if f.evidence && f.evidence.length}
                <div>
                  <span class="font-mono">evidence:</span>
                  <ul class="list-disc list-inside">
                    {#each f.evidence as ev}<li>{ev}</li>{/each}
                  </ul>
                </div>
              {/if}
              {#if f.next_actions && f.next_actions.length}
                <div>
                  <span class="font-mono">next_actions:</span>
                  <ul class="list-disc list-inside">
                    {#each f.next_actions as na}<li>{na}</li>{/each}
                  </ul>
                </div>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>
