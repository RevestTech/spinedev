<!--
  InstinctBadge (Path A T18).

  Surfaces Smart Spine (#27 / B3) instinct corroboration. Shows the
  most-corroborated fingerprint for the active project: pattern,
  trigger, count, distinct actor count. When the same fingerprint
  has been observed by >= 2 distinct actors in this project, the
  badge offers a "Promote to lesson" action (the actual promotion
  call is the operator's choice — surfaced as an `onPromote`
  callback so the parent route can dispatch through the existing
  learning.contribute pipeline).

  No promotion happens automatically; this matches the V3 #27 +
  privacy contract (instincts are local; promotion crosses scopes).
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { writable, type Readable } from 'svelte/store';
  import { subscribe, type ProjectEvent, type ProjectStream } from '$lib/stores/projectEvents';

  export let projectId: string;
  /** Distinct-actor threshold before the promote button appears. */
  export let promotionThreshold = 2;
  /**
   * Optional handler — receives the fingerprint string. Caller is
   * responsible for calling the backend promote_to_lesson_payload
   * pipeline; the badge component is read-only.
   */
  export let onPromote: ((fingerprint: string) => void) | null = null;

  interface Aggregate {
    fingerprint: string;
    pattern: string;
    trigger: string;
    count: number;
    actors: Set<string>;
  }

  let stream: ProjectStream | null = null;
  let events: Readable<ProjectEvent[]> = writable<ProjectEvent[]>([]);

  onMount(() => {
    if (projectId) {
      stream = subscribe(projectId);
      events = stream.eventsOf('instinct_recorded');
    }
  });

  onDestroy(() => {
    stream?.disconnect();
    stream = null;
  });

  $: aggregates = (() => {
    const byFp = new Map<string, Aggregate>();
    for (const e of $events) {
      const fp = (e.payload?.fingerprint as string | undefined) ?? '';
      if (!fp) continue;
      const prev = byFp.get(fp);
      if (prev) {
        prev.count += 1;
        prev.actors.add(e.actor);
      } else {
        byFp.set(fp, {
          fingerprint: fp,
          pattern: (e.payload?.pattern as string | undefined) ?? '',
          trigger: (e.payload?.trigger as string | undefined) ?? '',
          count: 1,
          actors: new Set([e.actor]),
        });
      }
    }
    return Array.from(byFp.values()).sort(
      (a, b) =>
        b.actors.size - a.actors.size || b.count - a.count,
    );
  })();

  $: top = aggregates[0] ?? null;
  $: eligible = (top?.actors.size ?? 0) >= promotionThreshold;
</script>

<section class="instinct-badge border rounded-md p-3 bg-sky-50 border-sky-200" aria-label="Smart Spine instinct corroboration">
  <header class="flex items-center gap-2 mb-1">
    <span class="text-xs uppercase tracking-wide font-semibold text-sky-800">
      instinct
    </span>
    <span class="flex-1 truncate text-sm font-medium text-sky-900" data-testid="instinct-title">
      {#if top}
        {top.pattern}
      {:else}
        No instincts recorded yet for this project.
      {/if}
    </span>
    {#if top}
      <span class="text-xs text-sky-700" data-testid="actor-count">
        {top.actors.size} {top.actors.size === 1 ? 'actor' : 'actors'} · {top.count} obs
      </span>
    {/if}
  </header>
  {#if top}
    <div class="text-xs text-sky-900/80 truncate" data-testid="instinct-trigger">
      when {top.trigger}
    </div>
    {#if eligible}
      <button
        type="button"
        class="mt-2 self-start text-xs px-2 py-0.5 border border-sky-400 rounded bg-white text-sky-700 hover:bg-sky-100"
        on:click={() => top && onPromote && onPromote(top.fingerprint)}
        disabled={!onPromote}
        data-testid="promote"
      >
        Promote to lesson
      </button>
    {/if}
  {/if}
</section>
