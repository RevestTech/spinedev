<!--
  AuditorVerdictCard (Path A T17).

  Surfaces the most recent auditor envelope for the active project.
  Explicit citation list. "Why was this denied?" expansion showing
  the PromotionGate.reasons list (when a denial is recorded — wired
  alongside the auditor's ledger_append publish).
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    connect,
    disconnect,
    projectEventsOf,
  } from '$lib/stores/projectEvents';

  export let projectId: string;

  onMount(() => {
    if (projectId) {
      connect(projectId);
    }
  });

  onDestroy(() => {
    disconnect();
  });

  const verdicts = projectEventsOf('auditor_verdict');
  const refusals = projectEventsOf('auditor_refusal');
  const ledger = projectEventsOf('ledger_append');

  $: combined = [...$verdicts, ...$refusals].sort(
    (a, b) =>
      new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
  );

  let expanded = false;

  $: latest = combined[0] ?? null;
  $: isRefusal = latest?.event_type === 'auditor_refusal';

  // Find the matching ledger entry by audit_id; carries the gate reasons.
  $: ledgerMatch =
    latest && $ledger.find(
      (e) =>
        e.payload?.run_id ===
        (latest?.payload?.audit_id as string | undefined),
    );
  $: reasons = (ledgerMatch?.payload?.promotion_reasons as string[] | undefined) ?? [];

  function tone(): string {
    if (!latest) return 'bg-slate-50 border-slate-200';
    if (isRefusal) return 'bg-red-50 border-red-300';
    return 'bg-emerald-50 border-emerald-300';
  }
</script>

<section
  class="auditor-verdict-card border rounded-md p-3 flex flex-col gap-2 {tone()}"
  aria-label="Auditor verdict"
>
  <header class="flex items-center gap-2">
    <span class="text-xs uppercase tracking-wide font-semibold">
      {latest?.event_type === 'auditor_refusal' ? 'refusal' : latest ? 'verdict' : 'auditor'}
    </span>
    <span class="flex-1 truncate text-sm font-medium" data-testid="title">
      {latest?.summary ?? 'No auditor activity yet for this project.'}
    </span>
    {#if latest}
      <span class="text-xs text-slate-600">{latest.actor}</span>
    {/if}
  </header>

  {#if latest && (latest.citation_count ?? 0) > 0}
    <div class="text-xs text-slate-700" data-testid="citation-count">
      {latest.citation_count} {latest.citation_count === 1 ? 'citation' : 'citations'}
    </div>
  {/if}

  {#if isRefusal}
    <button
      type="button"
      class="self-start text-xs text-red-700 underline"
      on:click={() => (expanded = !expanded)}
      data-testid="why-denied-toggle"
    >
      {expanded ? 'Hide' : 'Why was this denied?'}
    </button>
    {#if expanded}
      <div class="text-xs bg-white/60 border border-red-200 rounded p-2" data-testid="why-denied">
        {#if latest?.payload?.refusal_reason}
          <div class="mb-1">
            <span class="font-mono">refusal_reason:</span>
            {latest.payload.refusal_reason}
          </div>
        {/if}
        {#if reasons.length}
          <div>
            <span class="font-mono">promotion_gate.reasons:</span>
            <ul class="list-disc list-inside">
              {#each reasons as r}
                <li>{r}</li>
              {/each}
            </ul>
          </div>
        {:else}
          <div class="italic text-slate-500">
            no matching ledger entry — gate reasons unavailable
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</section>
