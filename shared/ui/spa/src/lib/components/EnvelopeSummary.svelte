<!--
  EnvelopeSummary (Path A T16).

  Renders the V3 #30a observation contract for a single tool
  response: `summary` as the title, `next_actions` as clickable
  dispatching chips, `artifacts` as a typed ref-list. Used inline
  wherever a `ToolResponse` envelope is shown (audit log rows,
  recovery dispatch surfaces, build_artifact ingestion).

  Decoupled from the realtime store: callers pass the envelope
  directly via props. Path B's Live tab uses this same shape via
  the `auditor_verdict` / `auditor_refusal` payloads.
-->
<script lang="ts">
  export interface Artifact {
    type: string;
    ref: string;
    label?: string | null;
  }

  export interface EnvelopeLike {
    status: string;
    summary?: string | null;
    next_actions?: string[];
    artifacts?: Artifact[];
  }

  export let envelope: EnvelopeLike;
  /**
   * Optional handler invoked when an operator clicks a next_action chip.
   * The chip text is dispatched verbatim (the conventional values are
   * tool names or commands — `engineer.read_minimal_brief`,
   * `approve_decision 42`, etc.).
   */
  export let onNextAction: ((action: string) => void) | null = null;

  $: nextActions = envelope.next_actions ?? [];
  $: artifacts = envelope.artifacts ?? [];

  function statusTone(status: string): string {
    if (status === 'ok' || status === 'passed' || status === 'allowed') {
      return 'bg-emerald-50 border-emerald-300 text-emerald-800';
    }
    if (status === 'warning') {
      return 'bg-amber-50 border-amber-300 text-amber-800';
    }
    if (
      status === 'error' ||
      status === 'failed' ||
      status === 'denied' ||
      status === 'refusal'
    ) {
      return 'bg-red-50 border-red-300 text-red-800';
    }
    return 'bg-slate-50 border-slate-300 text-slate-700';
  }
</script>

<article class="envelope-summary border rounded-md {statusTone(envelope.status)}">
  <header class="px-3 py-2 flex items-center gap-2">
    <span class="text-[0.7rem] uppercase tracking-wide font-semibold" data-testid="status">
      {envelope.status}
    </span>
    <span class="flex-1 truncate text-sm font-medium" data-testid="summary">
      {envelope.summary ?? '(no summary)'}
    </span>
  </header>

  {#if nextActions.length}
    <ul
      class="flex flex-wrap gap-1 px-3 pb-2"
      data-testid="next-actions"
      aria-label="Next actions"
    >
      {#each nextActions as action}
        <li>
          {#if onNextAction}
            <button
              type="button"
              class="text-[0.7rem] px-2 py-0.5 border rounded-full bg-white/70 hover:bg-white"
              on:click={() => onNextAction?.(action)}
              data-testid="next-action-chip"
            >
              {action}
            </button>
          {:else}
            <span
              class="text-[0.7rem] px-2 py-0.5 border rounded-full bg-white/70"
              data-testid="next-action-chip"
            >
              {action}
            </span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if artifacts.length}
    <ul
      class="flex flex-wrap gap-1 px-3 pb-2"
      data-testid="artifacts"
      aria-label="Artifacts"
    >
      {#each artifacts as art}
        <li
          class="text-[0.7rem] px-2 py-0.5 border rounded-full bg-white/70 inline-flex items-center gap-1"
          data-testid="artifact"
          data-artifact-type={art.type}
        >
          <span class="font-mono uppercase tracking-wide opacity-60">{art.type}</span>
          <span class="truncate max-w-[16rem]">{art.label ?? art.ref}</span>
        </li>
      {/each}
    </ul>
  {/if}
</article>
