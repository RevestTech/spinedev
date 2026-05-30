<!--
  LedgerTimeline (Path A T15).

  Dedicated decision-ledger view for the active project. Renders the
  live tail of `ledger_append` events as a timeline with one row per
  rollout — verdict colour, candidate marks, chain integrity badge,
  promotion-gate reason chips.

  Pairs with B1 (shared/audit/decision_ledger.py) and is fed by the
  same projectEvents store the Live tab uses, so it stays in sync
  without an independent fetch.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    connect,
    disconnect,
    projectEventsOf,
  } from '$lib/stores/projectEvents';
  import type { ProjectEvent } from '$lib/stores/projectEvents';

  export let projectId: string;

  type Tier =
    | 'paper'
    | 'preview'
    | 'internal'
    | 'production'
    | 'destructive'
    | 'all';

  let tierFilter: Tier = 'all';
  let csvBlob: string | null = null;

  onMount(() => {
    if (projectId) {
      connect(projectId);
    }
  });

  onDestroy(() => {
    disconnect();
  });

  const ledger = projectEventsOf('ledger_append');

  $: filtered = $ledger.filter((e) => {
    if (tierFilter === 'all') return true;
    const tier = (e.payload?.promotion_tier as string | undefined) ?? '';
    return tier === tierFilter;
  });

  $: chainOk = !filtered.some(
    (e) => (e.payload?.prev_hash ?? null) === undefined,
  );

  function reasonsOf(evt: ProjectEvent): string[] {
    const r = evt.payload?.promotion_reasons;
    return Array.isArray(r) ? (r as string[]) : [];
  }

  function candidateIds(evt: ProjectEvent): string[] {
    const c = evt.payload?.candidate_ids;
    return Array.isArray(c) ? (c as string[]) : [];
  }

  function verdictTone(v: string | null): string {
    if (v === 'allowed') return 'text-emerald-700 bg-emerald-50 border-emerald-300';
    if (v === 'denied') return 'text-red-700 bg-red-50 border-red-300';
    return 'text-slate-700 bg-slate-50 border-slate-300';
  }

  function toCsv(): string {
    const header =
      'occurred_at,actor,verdict,tier,reasons,content_hash,prev_hash,candidate_ids';
    const rows = filtered.map((e) => {
      const tier = (e.payload?.promotion_tier as string | undefined) ?? '';
      const ch = (e.payload?.content_hash as string | undefined) ?? '';
      const ph = (e.payload?.prev_hash as string | undefined) ?? '';
      const cand = candidateIds(e).join('|');
      const reasons = reasonsOf(e).join('|');
      return [
        e.occurred_at,
        e.actor,
        e.verdict ?? '',
        tier,
        reasons,
        ch,
        ph,
        cand,
      ]
        .map((v) => `"${String(v).replace(/"/g, '""')}"`)
        .join(',');
    });
    return [header, ...rows].join('\n');
  }

  function exportCsv() {
    csvBlob = toCsv();
    if (typeof window === 'undefined') return;
    const blob = new Blob([csvBlob], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ledger-${projectId}-${new Date()
      .toISOString()
      .replace(/[:.]/g, '-')}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
</script>

<section class="ledger-timeline flex flex-col gap-3" aria-label="Decision ledger">
  <header class="flex flex-wrap items-center gap-2 justify-between">
    <div class="flex items-center gap-2 text-sm font-medium text-slate-700">
      Decision ledger
      <span
        class="text-xs px-2 py-0.5 rounded-full border {chainOk
          ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
          : 'bg-red-50 text-red-700 border-red-300'}"
        data-testid="chain-badge"
      >
        chain {chainOk ? 'ok' : 'broken'}
      </span>
    </div>
    <div class="flex items-center gap-2">
      <label class="text-xs text-slate-600 flex items-center gap-1">
        Tier
        <select
          class="text-xs border rounded px-1 py-0.5"
          bind:value={tierFilter}
          data-testid="tier-filter"
        >
          <option value="all">all</option>
          <option value="paper">paper</option>
          <option value="preview">preview</option>
          <option value="internal">internal</option>
          <option value="production">production</option>
          <option value="destructive">destructive</option>
        </select>
      </label>
      <button
        type="button"
        class="text-xs px-2 py-1 border rounded hover:bg-slate-50"
        on:click={exportCsv}
        data-testid="export-csv"
        disabled={filtered.length === 0}
      >
        Export CSV
      </button>
    </div>
  </header>

  {#if filtered.length === 0}
    <p class="text-sm text-slate-500 italic" data-testid="empty">
      No ledger entries yet for this filter.
    </p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each filtered as evt (evt.event_id)}
        <li
          class="border rounded-md px-3 py-2 text-sm {verdictTone(evt.verdict)}"
          data-testid="ledger-row"
          data-verdict={evt.verdict ?? ''}
        >
          <div class="flex items-center gap-2">
            <span class="font-mono text-xs">{evt.payload?.promotion_tier ?? '—'}</span>
            <span class="font-medium uppercase tracking-wide text-xs">
              {evt.verdict}
            </span>
            <span class="flex-1 truncate font-medium">{evt.summary ?? ''}</span>
            <span class="text-xs">{evt.actor}</span>
          </div>
          {#if reasonsOf(evt).length}
            <div class="mt-1 flex flex-wrap gap-1">
              {#each reasonsOf(evt) as r}
                <span
                  class="text-[0.65rem] px-1.5 py-0.5 rounded-full bg-white/60 border border-current"
                  >{r}</span
                >
              {/each}
            </div>
          {/if}
          {#if candidateIds(evt).length}
            <div class="mt-1 text-[0.7rem] text-slate-600">
              candidates: {candidateIds(evt).join(', ')}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>
