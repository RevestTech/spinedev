<!--
  Spine Hub SPA — Decision Queue panel (V3 Wave 3 part 2, Squad SPA1).

  Surfaces backend at shared/api/routes/decisions.py:
    GET  /api/v2/decisions?status=pending      → DecisionList
    POST /api/v2/decisions/{id}/ack            → DecisionActionResponse
    POST /api/v2/decisions/{id}/reject         → DecisionActionResponse
    POST /api/v2/decisions/subscribe (SSE)     → live card_created/_updated

  Layout: master/detail — compact list left, full briefing + actions right.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { decisions } from '$lib/stores/decisions';
  import { toasts } from '$lib/stores/toasts';
  import { decisionProjectRef } from '$lib/decisionProject';
  import type { Citation, DecisionCard, DecisionSeverity } from '$lib/api/types';

  let busyId: string | null = null;
  let selectedDecisionId: string | null = null;

  onMount(() => {
    decisions.load('pending');
    decisions.connect();
  });
  onDestroy(() => {
    // NB: layout owns the long-lived SSE; we don't disconnect here.
  });

  $: items = $decisions.items;
  $: {
    if (items.length === 0) {
      selectedDecisionId = null;
    } else if (
      !selectedDecisionId ||
      !items.some((c) => c.decision_id === selectedDecisionId)
    ) {
      selectedDecisionId = items[0].decision_id;
    }
  }
  $: selectedCard = items.find((c) => c.decision_id === selectedDecisionId) ?? null;

  async function ack(card: DecisionCard) {
    busyId = card.decision_id;
    try {
      const r = await decisions.ack(card.decision_id);
      toasts.push({ kind: 'success', message: `Acked ${card.title}`, ttlMs: 3500 });
      console.debug('decision.ack', r);
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'ack failed' });
    } finally {
      busyId = null;
    }
  }
  async function reject(card: DecisionCard) {
    busyId = card.decision_id;
    try {
      const r = await decisions.reject(card.decision_id);
      toasts.push({ kind: 'success', message: `Rejected ${card.title}`, ttlMs: 3500 });
      console.debug('decision.reject', r);
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'reject failed' });
    } finally {
      busyId = null;
    }
  }

  const severityClass: Record<DecisionSeverity, string> = {
    info: 'border-l-severity-info',
    warning: 'border-l-severity-warning',
    critical: 'border-l-severity-critical'
  };

  const severityBadgeClass: Record<DecisionSeverity, string> = {
    info: 'bg-severity-info',
    warning: 'bg-severity-warning',
    critical: 'bg-severity-critical'
  };

  function extractCitations(card: DecisionCard): Citation[] {
    const raw = (card.metadata?.['citations'] ?? []) as Citation[];
    return Array.isArray(raw) ? raw : [];
  }

  function formatTime(unixSec: number): string {
    return new Date(unixSec * 1000).toLocaleString();
  }

  function allowsAction(card: DecisionCard, action: string): boolean {
    return !card.actions?.length || card.actions.includes(action);
  }

  function actionHint(card: DecisionCard): string {
    if (card.decision_class === 'approval') {
      return 'Ack advances the pipeline · Reject sends work back · Approve in project workspace or here';
    }
    return 'Ack or reject from the list, or read details on the right';
  }

  function projectHref(ref: ReturnType<typeof decisionProjectRef>): string | null {
    if (!ref.linkId) return null;
    return `${base}/projects/${ref.linkId}`;
  }
</script>

<style>
  /* Grid/flex children default to min-height:auto — content blows past the card. */
  .decision-queue-split {
    height: calc(100dvh - 13rem);
    min-height: 0;
    overflow: hidden;
    grid-template-rows: minmax(0, 1fr);
  }
  @media (min-width: 1024px) {
    .decision-queue-split > * {
      min-height: 0;
    }
  }
  .decision-queue-list,
  .decision-queue-detail {
    min-height: 0;
    max-height: 100%;
    height: 100%;
  }
  .decision-queue-detail {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .decision-queue-body {
    flex: 1 1 0;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
  }
  @media (max-width: 1023px) {
    .decision-queue-split {
      height: auto;
      max-height: none;
      overflow: visible;
    }
    .decision-queue-list {
      max-height: 16rem;
      height: auto;
    }
    .decision-queue-detail {
      height: calc(100dvh - 18rem);
      min-height: 20rem;
    }
  }
</style>

<PanelHeader title="Decision queue" subtitle="Project approvals only — portfolio briefings live in Hub inbox">
  <button
    type="button"
    class="btn-ghost"
    on:click={() => decisions.load('pending')}
    aria-label="Refresh decision queue"
  >
    Refresh
  </button>
</PanelHeader>

<div class="flex flex-col lg:min-h-0 lg:flex-1">
{#if $decisions.error}
  <div class="mb-4 shrink-0"><ErrorBanner kind="error" message={$decisions.error} /></div>
{/if}

{#if $decisions.loading && items.length === 0}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading queue" /></div>
{:else if items.length === 0}
  <EmptyState
    title="Inbox zero"
    message="No project approvals pending. Master director briefings appear in Hub inbox."
  />
{:else}
  <section
    class="panel-card flex min-h-0 flex-1 flex-col"
    data-testid="decision-queue-panel"
  >
    <header class="mb-3 flex shrink-0 items-center justify-between gap-2">
      <div>
        <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">Pending</h2>
        <p class="mt-0.5 text-[0.65rem] text-surface-700/70 dark:text-surface-200/70">
          Project approvals · ack advances the pipeline
        </p>
      </div>
      <span class="text-xs text-surface-700/70 dark:text-surface-200/70">
        {items.length} item{items.length === 1 ? '' : 's'}
      </span>
    </header>

    <div class="decision-queue-split grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-0">
      <ul
        class="decision-queue-list divide-y divide-surface-200 overflow-y-auto rounded-md border border-surface-200 dark:divide-surface-700 dark:border-surface-700 lg:col-span-4 lg:rounded-r-none lg:border-r-0"
        role="listbox"
        aria-label="Pending decisions"
        data-testid="decision-list"
      >
        {#each items as card (card.decision_id)}
          {@const pref = decisionProjectRef(card)}
          {@const prefHref = projectHref(pref)}
          <li
            class="border-l-4 {severityClass[card.severity] ?? severityClass.info} {card.decision_id === selectedDecisionId ? 'bg-accent/10' : ''}"
          >
            <div class="flex flex-wrap items-center gap-2 px-3 pt-2 text-[0.65rem] uppercase tracking-wide text-surface-700 dark:text-surface-200">
              <span>{card.decision_class}</span>
              {#if pref.scope === 'project'}
                {#if prefHref}
                  <a
                    href={prefHref}
                    class="inline-flex max-w-full items-center gap-1 rounded-full border border-accent/40 bg-accent/15 px-2 py-0.5 normal-case tracking-normal text-accent hover:border-accent/60 hover:bg-accent/25"
                    data-testid="decision-project-link"
                  >
                    <span class="truncate font-medium">{pref.label}</span>
                    <span aria-hidden="true">→</span>
                  </a>
                {:else}
                  <span class="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 normal-case tracking-normal text-accent">
                    {pref.label}
                  </span>
                {/if}
              {:else}
                <span class="rounded-full border border-surface-300/40 bg-surface-100 px-2 py-0.5 normal-case tracking-normal text-surface-600 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-300">
                  {pref.label}
                </span>
              {/if}
            </div>
            <div class="flex items-stretch">
              <button
                type="button"
                role="option"
                aria-selected={card.decision_id === selectedDecisionId}
                class="min-w-0 flex-1 px-3 py-2.5 text-left text-sm transition-colors hover:bg-surface-100 dark:hover:bg-surface-800"
                on:click={() => (selectedDecisionId = card.decision_id)}
              >
                <div class="flex items-start gap-2">
                  <div class="min-w-0 flex-1">
                    <span class="line-clamp-2 font-medium text-surface-900 dark:text-surface-50">
                      {card.title}
                    </span>
                    <time class="mt-1 block text-[0.65rem] text-surface-700/70 dark:text-surface-200/70">
                      {formatTime(card.created_at)}
                    </time>
                  </div>
                  <span
                    class="shrink-0 rounded-full px-1.5 py-0.5 text-[0.6rem] font-medium uppercase text-white {severityBadgeClass[card.severity] ?? severityBadgeClass.info}"
                  >
                    {card.severity}
                  </span>
                </div>
              </button>

              <div
                class="flex shrink-0 flex-col justify-center gap-1 border-l border-surface-200 px-1.5 py-1.5 dark:border-surface-700"
                role="group"
                aria-label="Actions for {card.title}"
              >
                {#if allowsAction(card, 'ack')}
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md text-emerald-400 transition-colors hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-40"
                    title="Acknowledge"
                    aria-label="Acknowledge {card.title}"
                    disabled={busyId === card.decision_id}
                    data-testid="decision-list-ack"
                    data-decision-id={card.decision_id}
                    on:click|stopPropagation={() => ack(card)}
                  >
                    {#if busyId === card.decision_id}
                      <span class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                    {:else}
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4" aria-hidden="true">
                        <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.895 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
                      </svg>
                    {/if}
                  </button>
                {/if}
                {#if allowsAction(card, 'reject')}
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md text-rose-400 transition-colors hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-40"
                    title="Reject"
                    aria-label="Reject {card.title}"
                    disabled={busyId === card.decision_id}
                    data-testid="decision-list-reject"
                    data-decision-id={card.decision_id}
                    on:click|stopPropagation={() => reject(card)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4" aria-hidden="true">
                      <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                    </svg>
                  </button>
                {/if}
              </div>
            </div>
          </li>
        {/each}
      </ul>

      <div
        class="decision-queue-detail rounded-md border border-surface-200 dark:border-surface-700 lg:col-span-8 lg:rounded-l-none"
        data-testid="decision-card"
        data-decision-id={selectedCard?.decision_id ?? ''}
        data-severity={selectedCard?.severity ?? ''}
      >
        {#if selectedCard}
          {@const selPref = decisionProjectRef(selectedCard)}
          {@const selPrefHref = projectHref(selPref)}
          <header
            class="shrink-0 border-b border-l-4 border-surface-200 px-4 py-3 dark:border-surface-700 {severityClass[selectedCard.severity] ?? severityClass.info}"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
                  <span>{selectedCard.decision_class}</span>
                  {#if selPref.scope === 'project'}
                    {#if selPrefHref}
                      <a
                        href={selPrefHref}
                        class="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent/15 px-2.5 py-0.5 normal-case tracking-normal text-accent hover:border-accent/60 hover:bg-accent/25"
                        data-testid="decision-detail-project-link"
                      >
                        <span class="font-medium">{selPref.label}</span>
                        <span aria-hidden="true">Open project →</span>
                      </a>
                    {:else}
                      <span class="rounded-full border border-accent/30 bg-accent/10 px-2.5 py-0.5 normal-case tracking-normal text-accent">
                        {selPref.label}
                      </span>
                    {/if}
                  {:else}
                    <span class="rounded-full border border-surface-300/40 bg-surface-100 px-2.5 py-0.5 normal-case tracking-normal text-surface-600 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-300">
                      {selPref.label}
                    </span>
                  {/if}
                </div>
                <h2 class="mt-1 line-clamp-2 break-words text-base font-semibold text-surface-900 dark:text-surface-50">
                  {selectedCard.title}
                </h2>
                <time class="mt-1 block text-xs text-surface-700/70 dark:text-surface-200/70">
                  {formatTime(selectedCard.created_at)}
                </time>
                <p class="mt-1 text-[0.65rem] text-surface-500">{actionHint(selectedCard)}</p>
              </div>
              <span
                class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium text-white {severityBadgeClass[selectedCard.severity] ?? severityBadgeClass.info}"
              >
                {selectedCard.severity}
              </span>
            </div>
          </header>

          <div class="decision-queue-body bg-surface-50 p-4 dark:bg-surface-900/50">
            {#if selectedCard.body}
              <pre
                class="whitespace-pre-wrap break-words text-sm leading-relaxed text-surface-700 dark:text-surface-200"
              >{selectedCard.body}</pre>
            {:else}
              <p class="text-sm text-surface-700/70 dark:text-surface-200/70">No body text.</p>
            {/if}

            {#if extractCitations(selectedCard).length > 0}
              <div class="mt-4 flex flex-wrap gap-1 border-t border-surface-200 pt-4 dark:border-surface-700">
                {#each extractCitations(selectedCard) as cite, i (i)}
                  <CitationChip citation={cite} />
                {/each}
              </div>
            {/if}
          </div>

          <footer
            class="decision-queue-actions flex shrink-0 flex-col gap-2 border-t border-surface-200 bg-surface-900 px-4 py-3 dark:border-surface-700 sm:flex-row sm:items-center sm:justify-between"
          >
            <div class="flex flex-wrap items-center gap-2">
              {#if selPref.scope === 'project' && selPrefHref}
                <a
                  href={selPrefHref}
                  class="text-xs text-surface-400 hover:text-accent"
                  data-testid="decision-detail-open-project"
                >
                  Review in {selPref.label} workspace →
                </a>
              {/if}
            </div>
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
            <button
              type="button"
              class="btn-ghost"
              disabled={busyId === selectedCard.decision_id}
              on:click={() => reject(selectedCard)}
              data-testid="decision-detail-reject"
            >
              Reject
            </button>
            <button
              type="button"
              class="btn-primary"
              disabled={busyId === selectedCard.decision_id}
              on:click={() => ack(selectedCard)}
              data-testid="decision-detail-ack"
            >
              {busyId === selectedCard.decision_id ? 'Working…' : 'Acknowledge'}
            </button>
            </div>
          </footer>
        {:else}
          <p class="p-4 text-sm text-surface-700/70 dark:text-surface-200/70">
            Select a decision to read.
          </p>
        {/if}
      </div>
    </div>
  </section>
{/if}
</div>
