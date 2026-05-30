<script lang="ts">
  /** Banners + in-flight activity card — recovery/run only, no terminal feed. */
  import ElapsedSeconds from '$lib/components/ElapsedSeconds.svelte';
  import {
    PIPELINE_COPY,
    dispatchKindLabel,
    recoveryActionInfo,
  } from '$lib/projectPipelineCopy';
  import { dispatchInFlightActive } from '$lib/projectRecoveryUtils';
  import { wsRecovery, wsRunState, wsRecoveryBusy } from '$lib/stores/projectWorkspace';

  function pipelineRoleInfo(role: string) {
    const r = PIPELINE_COPY.roles[role as keyof typeof PIPELINE_COPY.roles];
    return r ?? { label: role, what: 'Processing project work', typical: '~60s' };
  }

  $: recovery = $wsRecovery;
  $: run = $wsRunState;
  $: recoveryBusy = $wsRecoveryBusy;

  $: activityAction =
    recovery?.dispatch_in_flight?.action ?? run.lastDispatchedAction ?? recovery?.recommended_action;
  $: activityInfo = activityAction ? recoveryActionInfo(activityAction) : null;
  $: showActivityPanel =
    Boolean(activityInfo) &&
    (dispatchInFlightActive(recovery) ||
      run.activeRole ||
      recoveryBusy ||
      run.recoveryStarted ||
      run.lastDispatchedAction);

  $: elapsedSinceMs = (() => {
    const inflight = recovery?.dispatch_in_flight;
    if (inflight?.started_at) {
      const t = Date.parse(String(inflight.started_at).replace('Z', '+00:00'));
      if (!Number.isNaN(t)) return t;
    }
    if (run.lastDispatchAt) return run.lastDispatchAt;
    if (run.activeRoleStartedAt) return run.activeRoleStartedAt;
    return null;
  })();
</script>

{#if recovery?.fix_loop_exhausted}
  <div class="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-base text-rose-100">
    {PIPELINE_COPY.fixLoop.exhausted(
      recovery.code_fix_iteration ?? 0,
      recovery.max_code_fix_iterations ?? 3
    )}
  </div>
{:else if (recovery?.code_review_blocked ?? false) && (recovery?.code_fix_iteration ?? 0) > 0}
  <div class="mb-3 rounded-lg border border-surface-700/60 bg-surface-900/40 px-4 py-3 text-base text-surface-300">
    {PIPELINE_COPY.fixLoop.iteration(
      recovery?.code_fix_iteration ?? 0,
      recovery?.max_code_fix_iterations ?? 3
    )}
  </div>
{/if}

{#if showActivityPanel && activityInfo}
  <div class="mb-4 rounded-lg border border-accent/30 bg-accent/5 p-4" data-testid="pipeline-activity-panel">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-lg font-semibold text-surface-50">{PIPELINE_COPY.pipelineTab.activityTitle(activityInfo.label)}</p>
        <p class="mt-1 text-base text-surface-400">
          Typical duration: {activityInfo.typical}
          · <ElapsedSeconds sinceMs={elapsedSinceMs} suffix="s elapsed" />
          {#if dispatchInFlightActive(recovery)}
            · {PIPELINE_COPY.pipelineTab.hubActive}
          {/if}
        </p>
      </div>
      {#if recoveryBusy}
        <span class="text-base text-accent">{PIPELINE_COPY.pipelineTab.sending}</span>
      {:else if run.activeRole || dispatchInFlightActive(recovery)}
        <span class="inline-flex items-center gap-2 text-base text-accent">
          <span class="h-2.5 w-2.5 animate-pulse rounded-full bg-accent" aria-hidden="true"></span>
          {PIPELINE_COPY.pipelineTab.roleRunning}
        </span>
      {/if}
    </div>
    <ol class="mt-4 space-y-2.5 text-base text-surface-200">
      {#each activityInfo.steps as step, i}
        <li class="flex gap-3">
          <span class="shrink-0 font-mono text-sm text-surface-500">{i + 1}.</span>
          <span>{step}</span>
        </li>
      {/each}
    </ol>
    <p class="mt-4 text-base text-surface-400">
      <span class="font-medium text-surface-200">{PIPELINE_COPY.pipelineTab.activityWhenDone}</span>
      {activityInfo.outcome}
    </p>
  </div>
{:else if run.recoveryStarted}
  <div class="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-base text-surface-200">{run.recoveryStarted}</div>
{/if}
