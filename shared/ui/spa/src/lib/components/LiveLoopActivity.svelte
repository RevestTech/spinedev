<!--
  LiveLoopActivity (Path B T11).

  Chronological live feed of project-scoped events for the active
  workspace. One row per event with:

    - type-coloured icon + badge
    - one-line summary (the server-side ``summary`` field)
    - relative timestamp
    - click-to-expand for the full payload (json view)

  Caps at the last 100 rows so a long-running workspace stays
  responsive.

  Path A surfaces (LedgerTimeline, AuditorVerdictCard, …) replace
  individual row renderings later when they earn dedicated UX.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { writable, type Readable } from 'svelte/store';
  import {
    subscribe,
    type ProjectEvent,
    type ProjectEventType,
    type ProjectStream,
  } from '$lib/stores/projectEvents';

  export let projectId: string;
  /** Cap rows rendered at once. Older roll off. */
  export let maxRows = 100;

  let expanded = new Set<string>();
  let stream: ProjectStream | null = null;
  let events: Readable<ProjectEvent[]> = writable<ProjectEvent[]>([]);

  onMount(() => {
    if (projectId) {
      stream = subscribe(projectId);
      events = stream.events;
    }
  });

  onDestroy(() => {
    stream?.disconnect();
    stream = null;
  });

  $: rows = $events.slice(0, maxRows);

  function toggle(eventId: string) {
    if (expanded.has(eventId)) {
      expanded.delete(eventId);
    } else {
      expanded.add(eventId);
    }
    expanded = new Set(expanded); // trigger reactivity
  }

  function relativeTime(iso: string): string {
    try {
      const then = new Date(iso).getTime();
      const now = Date.now();
      const diff = Math.max(0, now - then) / 1000;
      if (diff < 60) return `${Math.floor(diff)}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch {
      return iso;
    }
  }

  function bgFor(evt: ProjectEvent): string {
    if (evt.event_type === 'auditor_refusal') return 'bg-amber-50 border-amber-400';
    if (evt.event_type === 'envelope_warning') return 'bg-amber-50 border-amber-300';
    if (evt.verdict === 'denied' || evt.verdict === 'failed' || evt.verdict === 'error') {
      return 'bg-red-50 border-red-400';
    }
    if (evt.verdict === 'allowed' || evt.verdict === 'passed' || evt.verdict === 'ok') {
      return 'bg-emerald-50 border-emerald-400';
    }
    if (evt.event_type === 'audit_event') return 'bg-slate-50 border-slate-300';
    if (evt.event_type === 'instinct_recorded') return 'bg-sky-50 border-sky-300';
    if (evt.event_type === 'charter_eval_run') return 'bg-cyan-50 border-cyan-300';
    return 'bg-white border-slate-200';
  }

  function badgeFor(t: ProjectEventType): string {
    const label: Record<ProjectEventType, string> = {
      ledger_append: 'ledger',
      directive_complete: 'directive',
      instinct_recorded: 'instinct',
      auditor_verdict: 'audit verdict',
      auditor_refusal: 'audit refusal',
      audit_event: 'audit',
      charter_eval_run: 'charter eval',
      operate_plane_status: 'operate',
      envelope_warning: 'envelope warn',
    };
    return label[t] ?? t;
  }

  function symbolFor(t: ProjectEventType): string {
    const sym: Record<ProjectEventType, string> = {
      ledger_append: '◇',
      directive_complete: '✓',
      instinct_recorded: '✶',
      auditor_verdict: '⚖',
      auditor_refusal: '⛔',
      audit_event: '◌',
      charter_eval_run: '☰',
      operate_plane_status: '⏚',
      envelope_warning: '⚠',
    };
    return sym[t] ?? '·';
  }
</script>

<section
  class="live-loop-activity flex flex-col gap-2"
  aria-label="Live operating-loop activity"
>
  <header class="flex items-center justify-between text-xs text-slate-500">
    <span>Live activity</span>
    <span data-testid="row-count">{rows.length} event{rows.length === 1 ? '' : 's'}</span>
  </header>

  {#if rows.length === 0}
    <p class="text-sm text-slate-500 italic">
      No live events yet. Dispatch a role or wait for the watcher.
    </p>
  {:else}
    <ul class="flex flex-col gap-1">
      {#each rows as evt (evt.event_id)}
        <li
          data-event-type={evt.event_type}
          class="border rounded-md px-3 py-2 cursor-pointer text-sm {bgFor(evt)}"
          on:click={() => toggle(evt.event_id)}
          on:keypress={(e) => e.key === 'Enter' && toggle(evt.event_id)}
          role="button"
          tabindex="0"
        >
          <div class="flex items-center gap-2">
            <span class="font-mono text-base" aria-hidden="true">{symbolFor(evt.event_type)}</span>
            <span class="text-xs uppercase tracking-wide text-slate-500">
              {badgeFor(evt.event_type)}
            </span>
            <span class="flex-1 truncate font-medium text-slate-800">
              {evt.summary ?? '(no summary)'}
            </span>
            <span class="text-xs text-slate-500" title={evt.occurred_at}>
              {relativeTime(evt.occurred_at)}
            </span>
          </div>
          {#if expanded.has(evt.event_id)}
            <pre
              class="mt-2 text-xs bg-slate-50 border border-slate-200 rounded p-2 overflow-auto"
              data-testid="expanded-payload"
            >{JSON.stringify(evt.payload, null, 2)}</pre>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .live-loop-activity {
    max-width: 100%;
  }
  pre {
    max-height: 240px;
  }
</style>
