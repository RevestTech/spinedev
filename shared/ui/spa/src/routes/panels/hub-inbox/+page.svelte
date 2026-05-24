<!--
  Hub message center — master director briefings and portfolio notices.
  Project approvals live on the Decisions panel.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { hubInbox } from '$lib/stores/hubInbox';
  import { toasts } from '$lib/stores/toasts';
  import type { DecisionCard } from '$lib/api/types';

  let busyId: string | null = null;
  let selectedId: string | null = null;

  onMount(() => {
    void hubInbox.load('pending');
  });

  $: items = $hubInbox.items;
  $: {
    if (items.length === 0) selectedId = null;
    else if (!selectedId || !items.some((c) => c.decision_id === selectedId)) {
      selectedId = items[0].decision_id;
    }
  }
  $: selected = items.find((c) => c.decision_id === selectedId) ?? null;

  async function ack(card: DecisionCard) {
    busyId = card.decision_id;
    try {
      await hubInbox.ack(card.decision_id);
      toasts.push({ kind: 'success', message: `Dismissed ${card.title}`, ttlMs: 3500 });
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'ack failed' });
    } finally {
      busyId = null;
    }
  }

  async function reject(card: DecisionCard) {
    busyId = card.decision_id;
    try {
      await hubInbox.reject(card.decision_id);
      toasts.push({ kind: 'success', message: `Rejected ${card.title}`, ttlMs: 3500 });
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'reject failed' });
    } finally {
      busyId = null;
    }
  }

  function formatTime(unixSec: number): string {
    return new Date(unixSec * 1000).toLocaleString();
  }

  function directorLabel(card: DecisionCard): string {
    const d = card.metadata?.director;
    if (typeof d === 'string' && d.startsWith('director_')) {
      return d.replace('director_', '').replace(/_/g, ' ');
    }
    return 'Hub';
  }
</script>

<style>
  .inbox-split {
    height: calc(100dvh - 13rem);
    min-height: 0;
    overflow: hidden;
    grid-template-rows: minmax(0, 1fr);
  }
  @media (min-width: 1024px) {
    .inbox-split > * {
      min-height: 0;
    }
  }
  .inbox-list,
  .inbox-detail {
    min-height: 0;
    max-height: 100%;
    height: 100%;
  }
  .inbox-detail {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .inbox-body {
    flex: 1 1 0;
    min-height: 0;
    overflow-y: auto;
  }
</style>

<PanelHeader
  title="Hub inbox"
  subtitle="Portfolio health from master directors — not tied to one project"
>
  <button type="button" class="btn-ghost" on:click={() => hubInbox.load('pending')}>
    Refresh
  </button>
</PanelHeader>

<div class="flex flex-col lg:min-h-0 lg:flex-1">
  {#if $hubInbox.error}
    <div class="mb-4 shrink-0"><ErrorBanner kind="error" message={$hubInbox.error} /></div>
  {/if}

  {#if $hubInbox.loading && items.length === 0}
    <div class="flex justify-center py-10"><LoadingSpinner label="Loading inbox" /></div>
  {:else if items.length === 0}
    <EmptyState
      title="Inbox clear"
      message="Master director briefings appear here when the Hub pushes a portfolio rollup. Project approvals stay under Decisions."
    />
  {:else}
    <section class="panel-card flex min-h-0 flex-1 flex-col" data-testid="hub-inbox-panel">
      <header class="mb-3 shrink-0">
        <p class="text-xs text-surface-400">
          {items.length} message{items.length === 1 ? '' : 's'} · Ack dismisses · Reject requests a revised briefing
        </p>
      </header>

      <div class="inbox-split grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-0">
        <ul
          class="inbox-list divide-y divide-surface-700 overflow-y-auto rounded-md border border-surface-700 lg:col-span-4 lg:rounded-r-none lg:border-r-0"
          data-testid="hub-inbox-list"
        >
          {#each items as card (card.decision_id)}
            <li class="border-l-4 border-l-sky-500/60 {card.decision_id === selectedId ? 'bg-accent/10' : ''}">
              <div class="flex items-stretch">
                <button
                  type="button"
                  class="min-w-0 flex-1 px-3 py-2.5 text-left text-sm hover:bg-surface-800/80"
                  on:click={() => (selectedId = card.decision_id)}
                >
                  <span class="text-[0.65rem] uppercase tracking-wide text-surface-500">
                    {directorLabel(card)}
                  </span>
                  <span class="mt-0.5 line-clamp-2 block font-medium text-surface-100">{card.title}</span>
                  <time class="mt-1 block text-[0.65rem] text-surface-500">{formatTime(card.created_at)}</time>
                </button>
                <div class="flex shrink-0 flex-col justify-center gap-1 border-l border-surface-700 px-1.5 py-1.5">
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md text-emerald-400 hover:bg-emerald-500/15 disabled:opacity-40"
                    title="Dismiss"
                    disabled={busyId === card.decision_id}
                    data-testid="hub-inbox-ack"
                    on:click|stopPropagation={() => ack(card)}
                  >
                    ✓
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md text-rose-400 hover:bg-rose-500/15 disabled:opacity-40"
                    title="Reject"
                    disabled={busyId === card.decision_id}
                    on:click|stopPropagation={() => reject(card)}
                  >
                    ✕
                  </button>
                </div>
              </div>
            </li>
          {/each}
        </ul>

        <div class="inbox-detail rounded-md border border-surface-700 lg:col-span-8 lg:rounded-l-none">
          {#if selected}
            <header class="shrink-0 border-b border-surface-700 px-4 py-3">
              <h2 class="text-base font-semibold text-surface-50">{selected.title}</h2>
              <time class="mt-1 block text-xs text-surface-500">{formatTime(selected.created_at)}</time>
              <p class="mt-2 text-xs text-surface-400">
                Summarizes all active projects. For per-project approvals, see
                <a href="{base}/panels/decision-queue" class="text-accent hover:underline">Decisions</a>.
              </p>
            </header>
            <div class="inbox-body p-4">
              <pre class="whitespace-pre-wrap break-words text-sm leading-relaxed text-surface-300">{selected.body}</pre>
            </div>
            <footer class="flex shrink-0 justify-end gap-2 border-t border-surface-700 px-4 py-3">
              <button type="button" class="btn-ghost" disabled={busyId === selected.decision_id} on:click={() => reject(selected)}>
                Reject
              </button>
              <button type="button" class="btn-primary" disabled={busyId === selected.decision_id} on:click={() => ack(selected)}>
                {busyId === selected.decision_id ? 'Working…' : 'Dismiss'}
              </button>
            </footer>
          {/if}
        </div>
      </div>
    </section>
  {/if}
</div>
