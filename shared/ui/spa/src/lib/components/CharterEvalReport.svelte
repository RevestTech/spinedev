<!--
  CharterEvalReport (Path A T19).

  Surfaces the latest charter-eval pass@k result per role. Reads
  charter_eval_run events from the `charter:<role>` event channel
  (the harness publishes there per V3 #7a wiring).

  Operators can trigger a fresh run via `onRunEvals` (the caller
  posts to the existing run.py CLI / API path). Red on any
  regressed eval, otherwise green.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    connect,
    disconnect,
    projectEventsOf,
  } from '$lib/stores/projectEvents';

  /** "engineer", "architect", "qa", "planner", "auditor". */
  export let role: string;
  /** Triggered when the operator hits "Run evals". */
  export let onRunEvals: ((role: string) => void) | null = null;

  $: scopedProjectId = `charter:${role}`;

  onMount(() => {
    if (role) {
      connect(scopedProjectId);
    }
  });

  onDestroy(() => {
    disconnect();
  });

  const events = projectEventsOf('charter_eval_run');

  $: latest = $events[0] ?? null;
  $: perEval = (latest?.payload?.per_eval as
    | Array<{
        eval_name: string;
        trials: number;
        passed: number;
        pass_rate: number;
        target_pass_rate: number;
        meets_target: boolean;
      }>
    | undefined) ?? [];
  $: overall = Boolean(latest?.payload?.overall_meets_target);

  function tone(meets: boolean): string {
    return meets
      ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
      : 'bg-red-50 border-red-300 text-red-800';
  }
</script>

<section class="charter-eval-report flex flex-col gap-2" aria-label="Charter regression evals">
  <header class="flex items-center gap-2">
    <span class="text-sm font-semibold text-slate-800">
      Charter eval — {role}
    </span>
    {#if latest}
      <span
        class="text-xs px-2 py-0.5 rounded-full border {tone(overall)}"
        data-testid="overall"
      >
        overall {overall ? 'pass' : 'fail'}
      </span>
    {/if}
    {#if onRunEvals}
      <button
        type="button"
        class="ml-auto text-xs px-2 py-0.5 border rounded hover:bg-slate-50"
        on:click={() => onRunEvals?.(role)}
        data-testid="run-evals"
      >
        Run evals
      </button>
    {/if}
  </header>

  {#if !latest}
    <p class="text-sm text-slate-500 italic" data-testid="empty">
      No eval run recorded yet for {role}.
    </p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each perEval as p}
        <li
          class="border rounded-md px-2 py-1 text-xs flex items-center gap-2 {tone(p.meets_target)}"
          data-testid="eval-row"
        >
          <span class="font-mono truncate flex-1">{p.eval_name}</span>
          <span data-testid="pass-rate">
            {(p.pass_rate * 100).toFixed(0)}%
          </span>
          <span class="opacity-70 text-[0.65rem]">
            target {(p.target_pass_rate * 100).toFixed(0)}%
          </span>
          <span class="font-semibold">
            {p.meets_target ? '✓' : '✗'}
          </span>
        </li>
      {/each}
    </ol>
  {/if}
</section>
