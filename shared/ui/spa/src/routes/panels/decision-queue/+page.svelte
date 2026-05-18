<!--
  Spine Hub SPA — Decision Queue panel (V3 Wave 3 part 2, Squad SPA1).

  Surfaces backend at shared/api/routes/decisions.py:
    GET  /api/v2/decisions?status=pending      → DecisionList
    POST /api/v2/decisions/{id}/ack            → DecisionActionResponse
    POST /api/v2/decisions/{id}/reject         → DecisionActionResponse
    POST /api/v2/decisions/subscribe (SSE)     → live card_created/_updated

  Per design decisions:
    - #3  one of the 9 enumerated Hub surfaces
    - #5  active push — SSE keeps the panel live without polling
    - #12 Cite-or-Refuse — Citation chips render below the body if the
          card carries `metadata.citations`

  This panel is the PATTERN for SPA2 + SPA3:
    1. Page-level <script> imports stores + components.
    2. onMount: load() + connect SSE; onDestroy: disconnect SSE.
    3. PanelHeader + slot actions (refresh / filter).
    4. LoadingSpinner → EmptyState → list/grid → CitationChip row.
    5. Tailwind: mobile-first; grid expands at md / lg.

  Mobile viewport behaviour (tested in browser device emulator):
    - 390px (iPhone Safari)  : single column, full-width cards,
                                ack/reject buttons stack vertically.
    - 393px (Android Chrome) : identical to iPhone — single column.
    - 768px (iPad portrait)  : two-column grid, side-by-side action buttons.
    - >= 1024px (desktop)    : three-column grid; sidebar visible permanently.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { decisions } from '$lib/stores/decisions';
  import { toasts } from '$lib/stores/toasts';
  import type { Citation, DecisionCard, DecisionSeverity } from '$lib/api/types';

  let busyId: string | null = null;

  onMount(() => {
    decisions.load('pending');
    decisions.connect();
  });
  onDestroy(() => {
    // NB: layout owns the long-lived SSE; we don't disconnect here.
  });

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

  function extractCitations(card: DecisionCard): Citation[] {
    const raw = (card.metadata?.['citations'] ?? []) as Citation[];
    return Array.isArray(raw) ? raw : [];
  }
</script>

<PanelHeader title="Decision queue" subtitle="Active-push decisions awaiting your call">
  <button
    type="button"
    class="btn-ghost"
    on:click={() => decisions.load('pending')}
    aria-label="Refresh decision queue"
  >
    Refresh
  </button>
</PanelHeader>

{#if $decisions.error}
  <div class="mb-4"><ErrorBanner kind="error" message={$decisions.error} /></div>
{/if}

{#if $decisions.loading && $decisions.items.length === 0}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading queue" /></div>
{:else if $decisions.items.length === 0}
  <EmptyState
    title="Inbox zero"
    message="No pending decisions. New cards will appear here as roles push them."
  />
{:else}
  <ul
    class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
    data-testid="decision-list"
  >
    {#each $decisions.items as card (card.decision_id)}
      <li
        class="panel-card flex flex-col gap-3 border-l-4 {severityClass[card.severity] ?? severityClass.info}"
        data-testid="decision-card"
        data-decision-id={card.decision_id}
        data-severity={card.severity}
      >
        <header class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="flex items-center gap-2 text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
              <span>{card.decision_class}</span>
              {#if card.project_id}
                <span class="rounded bg-surface-100 px-1.5 py-0.5 dark:bg-surface-700">
                  proj {card.project_id}
                </span>
              {/if}
            </div>
            <h2 class="mt-1 break-words text-base font-semibold text-surface-900 dark:text-surface-50">
              {card.title}
            </h2>
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium text-white"
            class:bg-severity-info={card.severity === 'info'}
            class:bg-severity-warning={card.severity === 'warning'}
            class:bg-severity-critical={card.severity === 'critical'}
          >
            {card.severity}
          </span>
        </header>

        {#if card.body}
          <p class="whitespace-pre-wrap break-words text-sm text-surface-700 dark:text-surface-200">
            {card.body}
          </p>
        {/if}

        {#if extractCitations(card).length > 0}
          <div class="flex flex-wrap gap-1">
            {#each extractCitations(card) as cite, i (i)}
              <CitationChip citation={cite} />
            {/each}
          </div>
        {/if}

        <footer class="mt-auto flex flex-col gap-2 border-t border-surface-200 pt-3 dark:border-surface-700 sm:flex-row sm:items-center sm:justify-between">
          <time class="text-xs text-surface-700 dark:text-surface-200">
            {new Date(card.created_at * 1000).toLocaleString()}
          </time>
          <div class="flex flex-col gap-2 xs:flex-row">
            <button
              type="button"
              class="btn-ghost"
              disabled={busyId === card.decision_id}
              on:click={() => reject(card)}
              data-testid="decision-reject"
            >
              Reject
            </button>
            <button
              type="button"
              class="btn-primary"
              disabled={busyId === card.decision_id}
              on:click={() => ack(card)}
              data-testid="decision-ack"
            >
              {busyId === card.decision_id ? 'Working…' : 'Acknowledge'}
            </button>
          </div>
        </footer>
      </li>
    {/each}
  </ul>
{/if}
