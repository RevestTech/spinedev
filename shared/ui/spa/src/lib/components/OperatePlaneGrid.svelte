<!--
  OperatePlaneGrid (Path A T21).

  8-plane live grid. Each cell renders one V3 #11 control plane
  with its latest status, last-update timestamp, and an optional
  "Invoke action" button (callback dispatches into the existing
  ControlPlane.invoke() path on the backend).

  Updates from `operate_plane_status` events arriving via the
  projectEvents store; the rollup event marks the most recent
  operate cycle.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { writable, type Readable } from 'svelte/store';
  import { subscribe, type ProjectEvent, type ProjectStream } from '$lib/stores/projectEvents';

  export let projectId: string;
  export let onInvoke:
    | ((plane: string, action: string) => void)
    | null = null;

  /** Canonical 8-plane ordering — mirrors PLANE_NAMES in
   * devops/runtime/operate_runner.py. */
  const PLANES = [
    'infrastructure',
    'deployment',
    'monitoring',
    'alerting',
    'networking',
    'database',
    'secrets',
    'ci_cd',
  ] as const;

  let stream: ProjectStream | null = null;
  let events: Readable<ProjectEvent[]> = writable<ProjectEvent[]>([]);

  onMount(() => {
    if (projectId) {
      stream = subscribe(projectId);
      events = stream.eventsOf('operate_plane_status');
    }
  });

  onDestroy(() => {
    stream?.disconnect();
    stream = null;
  });

  interface Cell {
    plane: string;
    status: string;
    verdict: string | null;
    summary: string | null;
    occurred_at: string | null;
    error: string | null;
  }

  $: byPlane = (() => {
    const out = new Map<string, Cell>();
    for (const p of PLANES) {
      out.set(p, {
        plane: p,
        status: 'unknown',
        verdict: null,
        summary: null,
        occurred_at: null,
        error: null,
      });
    }
    // Newest-first iteration ensures the freshest snapshot per plane wins.
    for (const e of $events) {
      const name = (e.payload?.plane as string | undefined) ?? '';
      if (!name || !out.has(name)) continue;
      const current = out.get(name)!;
      // Skip if we've already recorded a newer entry.
      if (
        current.occurred_at &&
        new Date(current.occurred_at).getTime() >=
          new Date(e.occurred_at).getTime()
      ) {
        continue;
      }
      out.set(name, {
        plane: name,
        status: (e.payload?.status as string | undefined) ?? 'unknown',
        verdict: e.verdict,
        summary: e.summary,
        occurred_at: e.occurred_at,
        error: (e.payload?.error as string | null | undefined) ?? null,
      });
    }
    return Array.from(out.values());
  })();

  function tone(status: string): string {
    if (status === 'active' || status === 'ok')
      return 'bg-emerald-50 border-emerald-300 text-emerald-800';
    if (status === 'paused' || status === 'warning')
      return 'bg-amber-50 border-amber-300 text-amber-800';
    if (status === 'error' || status === 'disabled')
      return 'bg-red-50 border-red-300 text-red-800';
    return 'bg-slate-50 border-slate-300 text-slate-600';
  }
</script>

<section class="operate-plane-grid grid grid-cols-2 sm:grid-cols-4 gap-2" aria-label="Operate control planes">
  {#each byPlane as cell (cell.plane)}
    <article
      class="border rounded-md p-2 text-xs flex flex-col gap-1 {tone(cell.status)}"
      data-testid="plane-cell"
      data-plane={cell.plane}
      data-status={cell.status}
    >
      <header class="flex items-center justify-between">
        <span class="font-mono uppercase tracking-wide text-[0.7rem]">
          {cell.plane}
        </span>
        <span class="font-semibold">{cell.status}</span>
      </header>
      {#if cell.summary}
        <p class="truncate text-[0.7rem]">{cell.summary}</p>
      {/if}
      {#if cell.error}
        <p class="truncate text-[0.65rem] text-red-700" data-testid="plane-error">
          {cell.error}
        </p>
      {/if}
      {#if onInvoke}
        <button
          type="button"
          class="self-start mt-1 text-[0.65rem] px-1.5 py-0.5 border rounded bg-white/80 hover:bg-white"
          on:click={() => onInvoke?.(cell.plane, 'status')}
          data-testid="invoke"
        >
          Refresh
        </button>
      {/if}
    </article>
  {/each}
</section>
