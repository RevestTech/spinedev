<script lang="ts">
  import { onDestroy } from 'svelte';

  /** Wall-clock ms when the interval started (preferred). */
  export let sinceMs: number | null = null;
  /** ISO timestamp fallback (e.g. dispatch_in_flight.started_at). */
  export let sinceIso: string | null = null;
  /** Optional suffix after the number, e.g. "s elapsed". */
  export let suffix = 's';
  /** Fired about once per second while running — use for stale timers without parent re-renders. */
  export let onTick: ((seconds: number) => void) | undefined = undefined;

  let seconds = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  function baseMs(): number | null {
    if (sinceMs != null && !Number.isNaN(sinceMs)) return sinceMs;
    if (sinceIso) {
      const t = Date.parse(String(sinceIso).replace('Z', '+00:00'));
      return Number.isNaN(t) ? null : t;
    }
    return null;
  }

  function refresh() {
    const base = baseMs();
    seconds = base != null ? Math.max(0, Math.round((Date.now() - base) / 1000)) : 0;
    onTick?.(seconds);
  }

  $: {
    if (timer) clearInterval(timer);
    timer = null;
    refresh();
    if (baseMs() != null) {
      timer = setInterval(refresh, 1000);
    }
  }

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<span class="tabular-nums">{seconds}{suffix}</span>
