<script lang="ts">
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import { PIPELINE_COPY } from '$lib/projectPipelineCopy';
  import { decisions } from '$lib/stores/decisions';
  import { toasts } from '$lib/stores/toasts';
  import type { DecisionCard } from '$lib/api/types';

  export let projectDecisions: DecisionCard[] = [];
  export let isPipelineStuck = false;
  export let onSelectPipelineTab: () => void = () => {};
  export let onAfterAction: () => void | Promise<void> = () => {};

  const DECISION_BODY_PREVIEW = 4000;

  let decisionBodyExpanded = false;
  let selectedProjectDecisionId: string | null = null;
  let lastSelectedDecisionId: string | null = null;
  let decisionBodyText = '';
  let decisionBodyLoading = false;
  let decisionBusyId: string | null = null;

  $: {
    const cards = projectDecisions ?? [];
    if (cards.length === 0) {
      selectedProjectDecisionId = null;
    } else if (
      !selectedProjectDecisionId ||
      !cards.some((c) => c.decision_id === selectedProjectDecisionId)
    ) {
      selectedProjectDecisionId = cards[0].decision_id;
    }
  }

  $: selectedProjectDecision =
    (projectDecisions ?? []).find((c) => c.decision_id === selectedProjectDecisionId) ?? null;

  $: if (selectedProjectDecisionId !== lastSelectedDecisionId) {
    lastSelectedDecisionId = selectedProjectDecisionId;
    decisionBodyExpanded = false;
    void loadSelectedDecisionBody(selectedProjectDecisionId);
  }

  function decisionBodyPreview(body: string): { text: string; truncated: boolean } {
    if (decisionBodyExpanded || body.length <= DECISION_BODY_PREVIEW) {
      return { text: body, truncated: false };
    }
    return { text: `${body.slice(0, DECISION_BODY_PREVIEW)}…`, truncated: true };
  }

  async function loadSelectedDecisionBody(id: string | null) {
    if (!id) {
      decisionBodyText = '';
      decisionBodyLoading = false;
      return;
    }
    const card = projectDecisions.find((c) => c.decision_id === id);
    if (card?.body) {
      decisionBodyText = card.body;
      decisionBodyLoading = false;
      return;
    }
    decisionBodyLoading = true;
    decisionBodyText = '';
    try {
      decisionBodyText = await decisions.fetchBody(id);
    } catch {
      decisionBodyText = 'Failed to load decision details.';
    } finally {
      decisionBodyLoading = false;
    }
  }

  async function ackProjectDecision(card: DecisionCard) {
    decisionBusyId = card.decision_id;
    try {
      await decisions.ack(card.decision_id);
      toasts.push({ kind: 'success', message: `Approved: ${card.title}`, ttlMs: 3500 });
      await onAfterAction();
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'ack failed' });
    } finally {
      decisionBusyId = null;
    }
  }

  async function rejectProjectDecision(card: DecisionCard) {
    decisionBusyId = card.decision_id;
    try {
      await decisions.reject(card.decision_id);
      toasts.push({ kind: 'success', message: `Rejected: ${card.title}`, ttlMs: 3500 });
      await onAfterAction();
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'reject failed' });
    } finally {
      decisionBusyId = null;
    }
  }

  function projectDecisionHint(card: DecisionCard): string {
    if (card.decision_class === 'briefing') return PIPELINE_COPY.decisions.hintBriefing;
    if (card.decision_class === 'approval') return PIPELINE_COPY.decisions.hintApproval;
    return PIPELINE_COPY.decisions.hintDefault;
  }
</script>

<div class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0" data-testid="project-decisions">
  {#if projectDecisions.length === 0}
    <div class="space-y-3 py-6 lg:col-span-12">
      <p class="text-base text-surface-300 sm:text-lg">No pending decisions for this project.</p>
      {#if isPipelineStuck}
        <p class="text-base text-amber-100 sm:text-lg">
          {PIPELINE_COPY.pipelineTab.decisionsEmptyLead}
          <button
            type="button"
            class="font-semibold text-accent underline hover:text-accent/80"
            on:click={onSelectPipelineTab}
          >
            Pipeline
          </button>
          {PIPELINE_COPY.pipelineTab.decisionsEmptyTrail}
        </p>
      {/if}
    </div>
  {:else}
    <ul
      class="workspace-list divide-y divide-surface-700/60 overflow-y-auto rounded-lg border border-surface-700/60 lg:col-span-4 lg:rounded-r-none lg:border-r-0"
      role="listbox"
    >
      {#each projectDecisions as card (card.decision_id)}
        <li
          class="flex items-stretch border-l-2 {card.decision_id === selectedProjectDecisionId
            ? 'border-accent bg-accent/10'
            : 'border-transparent'}"
        >
          <button
            type="button"
            class="min-w-0 flex-1 px-3 py-2 text-left text-sm"
            on:click={() => (selectedProjectDecisionId = card.decision_id)}
          >
            <span class="text-[0.6rem] uppercase text-surface-500">{card.decision_class}</span>
            <span class="mt-0.5 line-clamp-2 block font-medium text-surface-100">{card.title}</span>
          </button>
          <div class="flex flex-col justify-center gap-1 border-l border-surface-700/60 px-1 py-1">
            <button
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded text-emerald-400 hover:bg-emerald-500/15"
              title="Approve"
              disabled={decisionBusyId === card.decision_id}
              on:click|stopPropagation={() => ackProjectDecision(card)}
            >
              ✓
            </button>
            <button
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded text-rose-400 hover:bg-rose-500/15"
              title="Reject"
              disabled={decisionBusyId === card.decision_id}
              on:click|stopPropagation={() => rejectProjectDecision(card)}
            >
              ✕
            </button>
          </div>
        </li>
      {/each}
    </ul>
    <div
      class="workspace-detail flex flex-col overflow-hidden rounded-lg border border-surface-700/60 lg:col-span-8 lg:rounded-l-none"
    >
      {#if selectedProjectDecision}
        {@const body = decisionBodyText || selectedProjectDecision.body || 'No details.'}
        {@const preview = decisionBodyPreview(body)}
        <header class="shrink-0 border-b border-surface-700/60 px-4 py-3">
          <h3 class="text-sm font-semibold text-surface-50">{selectedProjectDecision.title}</h3>
          <p class="mt-1 text-xs text-surface-400">{projectDecisionHint(selectedProjectDecision)}</p>
        </header>
        <div class="workspace-scroll min-h-0 flex-1 overflow-y-auto p-4">
          {#if decisionBodyLoading}
            <LoadingSpinner label="Loading decision" />
          {:else}
            <pre class="whitespace-pre-wrap text-sm leading-relaxed text-surface-300">{preview.text}</pre>
          {/if}
          {#if body.length > DECISION_BODY_PREVIEW}
            <button
              type="button"
              class="mt-3 text-sm font-medium text-accent hover:text-accent/80"
              on:click={() => (decisionBodyExpanded = !decisionBodyExpanded)}
            >
              {decisionBodyExpanded
                ? 'Show less'
                : `Show full output (${body.length.toLocaleString()} chars)`}
            </button>
          {/if}
        </div>
        <footer class="flex shrink-0 justify-end gap-2 border-t border-surface-700/60 px-4 py-3">
          <button
            type="button"
            class="btn-ghost text-sm"
            disabled={decisionBusyId === selectedProjectDecision.decision_id}
            on:click={() => rejectProjectDecision(selectedProjectDecision)}
          >
            Reject
          </button>
          <button
            type="button"
            class="btn-primary text-sm"
            disabled={decisionBusyId === selectedProjectDecision.decision_id}
            on:click={() => ackProjectDecision(selectedProjectDecision)}
          >
            {decisionBusyId === selectedProjectDecision.decision_id ? 'Working…' : 'Approve'}
          </button>
        </footer>
      {/if}
    </div>
  {/if}
</div>
