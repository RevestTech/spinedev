<script lang="ts">
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ElapsedSeconds from '$lib/components/ElapsedSeconds.svelte';
  import RoleTerminalLive from '$lib/components/RoleTerminalLive.svelte';
  import {
    PIPELINE_COPY,
    dispatchKindLabel,
    recoveryActionInfo,
  } from '$lib/projectPipelineCopy';
  import {
    dispatchInFlightActive,
    isDispatchStale,
  } from '$lib/projectRecoveryUtils';
  import {
    wsRecovery,
    wsRunState,
    wsRecoveryBusy,
    wsRecoveryLoading,
    wsRecoveryError,
    wsFeed,
    wsDispatchUiStale,
    wsDispatchRecovery,
    wsCancelInflight,
    type FeedEvent,
  } from '$lib/stores/projectWorkspace';
  import { toasts } from '$lib/stores/toasts';

  export let projectId: string;
  export let codeReviewBlocked = false;
  export let codeFixIteration = 0;
  export let onSelectPipelineTab: () => void = () => {};

  let recoveryNote = '';
  let selectedRecoveryAction: string | null = null;
  let cancelInflightBusy = false;

  function pipelineRoleInfo(role: string) {
    const r = PIPELINE_COPY.roles[role as keyof typeof PIPELINE_COPY.roles];
    return r ?? { label: role, what: 'Processing project work', typical: '~60s' };
  }

  $: recovery = $wsRecovery;
  $: run = $wsRunState;
  $: recoveryBusy = $wsRecoveryBusy;
  $: recoveryLoading = $wsRecoveryLoading;
  $: recoveryError = $wsRecoveryError;
  $: feed = $wsFeed;

  $: if (recovery?.actions?.length) {
    const ids = recovery.actions.map((a) => a.action);
    const rec = recovery.recommended_action;
    if (!selectedRecoveryAction || !ids.includes(selectedRecoveryAction)) {
      selectedRecoveryAction = rec && ids.includes(rec) ? rec : ids[0] ?? null;
    }
  } else {
    selectedRecoveryAction = null;
  }

  $: selectedRecoverySpec =
    recovery?.actions.find((a) => a.action === selectedRecoveryAction) ?? null;

  $: recoveryActionsSorted = recovery?.actions
    ? [...recovery.actions].sort((a, b) => {
        const rec = recovery?.recommended_action;
        if (a.action === rec) return -1;
        if (b.action === rec) return 1;
        return 0;
      })
    : [];

  $: recoveryDispatchBlocked =
    recoveryBusy || run.activeRole !== null || dispatchInFlightActive(recovery);

  $: showClearInflight =
    Boolean(recovery?.dispatch_in_flight) &&
    (isDispatchStale(recovery?.dispatch_in_flight) || $wsDispatchUiStale);

  $: activityAction =
    recovery?.dispatch_in_flight?.action ?? run.lastDispatchedAction ?? selectedRecoveryAction;
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

  $: roleInfo = run.activeRole ? pipelineRoleInfo(run.activeRole) : null;

  $: terminalActive = Boolean(
    run.activeRole || recoveryBusy || dispatchInFlightActive(recovery)
  );
  $: terminalTitle = run.activeRole
    ? PIPELINE_COPY.terminal.titleLive(pipelineRoleInfo(run.activeRole).label)
    : dispatchInFlightActive(recovery)
      ? PIPELINE_COPY.terminal.titleLive(
          dispatchKindLabel(recovery?.dispatch_in_flight?.dispatch_kind)
        )
      : PIPELINE_COPY.terminal.titleIdle;

  function feedEmptyMessage(): string {
    if (run.activeRole && roleInfo) {
      return `${roleInfo.label}: ${roleInfo.what} Typical duration: ${roleInfo.typical}.`;
    }
    const inflight = recovery?.dispatch_in_flight;
    if (inflight && isDispatchStale(inflight)) {
      return 'The previous run was interrupted (Hub restart or timeout). Refresh recovery status or choose an action below to continue.';
    }
    if (dispatchInFlightActive(recovery)) {
      const label = dispatchKindLabel(inflight?.dispatch_kind);
      return `${label} is in progress. Log output will appear here shortly (typically within 30–90 seconds).`;
    }
    if (run.recoveryStarted || run.lastDispatchedAction) {
      return 'Your request was accepted. Output will stream here as the step runs.';
    }
    return PIPELINE_COPY.terminal.emptyIdle;
  }

  $: terminalEmptyMessage = terminalActive
    ? PIPELINE_COPY.terminal.emptyRunning
    : feedEmptyMessage();

  function dispatch(action: string) {
    wsDispatchRecovery(projectId, action, recoveryNote, onSelectPipelineTab);
    recoveryNote = '';
  }

  async function cancelStaleInflight() {
    if (cancelInflightBusy) return;
    cancelInflightBusy = true;
    wsRecoveryError.set(null);
    try {
      await wsCancelInflight(projectId);
      toasts.push({
        kind: 'success',
        message: 'Cleared stuck dispatch flag — you can run the pipeline again.',
        ttlMs: 4000,
      });
    } catch (e) {
      wsRecoveryError.set((e as Error).message || 'failed to clear dispatch');
    } finally {
      cancelInflightBusy = false;
    }
  }

  function feedLabel(ev: FeedEvent): string {
    if (ev.type === 'dispatch_started') {
      return `You started ${ev.message ?? ev.role ?? 'a role'}`;
    }
    if (ev.type === 'role_started') return `${ev.role} started${ev.message ? ' — ' + ev.message : ''}`;
    if (ev.type === 'role_finished') {
      if (ev.files_written !== undefined) return `${ev.role} wrote ${ev.files_written} files`;
      if (ev.install_ok !== undefined) return `${ev.role} install ${ev.install_ok ? 'succeeded' : 'failed'}`;
      if (ev.artifact_chars !== undefined) return `${ev.role} produced ${ev.artifact_chars.toLocaleString()} chars`;
      return `${ev.role} finished`;
    }
    if (ev.type === 'role_failed') return `${ev.role} failed: ${ev.error ?? 'unknown error'}`;
    if (ev.type === 'card_created') return `Decision: ${ev.title ?? ev.message ?? '(no title)'}`;
    if (ev.type === 'card_updated') return `Decision updated: ${ev.title ?? ev.message ?? ''}`;
    return ev.type.replace(/_/g, ' ');
  }

  function feedTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function feedTone(ev: FeedEvent): string {
    if (ev.type === 'dispatch_started') return 'text-violet-200';
    if (ev.type === 'role_started') return 'text-accent';
    if (ev.type === 'role_finished' && ev.install_ok === false) return 'text-amber-200';
    if (ev.type === 'role_finished') return 'text-sky-200';
    if (ev.type === 'role_failed') return 'text-rose-200';
    if (ev.type === 'card_created') return 'text-violet-200';
    return 'text-surface-300';
  }
</script>

{#if recoveryError}
  <div class="mb-3">
    <ErrorBanner kind="error" message={recoveryError} onDismiss={() => wsRecoveryError.set(null)} />
  </div>
{/if}
{#if recovery?.fix_loop_exhausted}
  <div class="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-base text-rose-100">
    {PIPELINE_COPY.fixLoop.exhausted(
      recovery.code_fix_iteration ?? 0,
      recovery.max_code_fix_iterations ?? 3
    )}
  </div>
{:else if codeReviewBlocked && (recovery?.code_fix_iteration ?? codeFixIteration) > 0}
  <div class="mb-3 rounded-lg border border-surface-700/60 bg-surface-900/40 px-4 py-3 text-base text-surface-300">
    {PIPELINE_COPY.fixLoop.iteration(
      recovery?.code_fix_iteration ?? codeFixIteration,
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
<div class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0" data-testid="pipeline-controls">
  <div class="lg:col-span-5 lg:border-r lg:border-surface-700/60 lg:pr-4">
    <p class="mb-2 text-base text-surface-400">{PIPELINE_COPY.pipelineTab.controlsLead}</p>
    {#if recoveryLoading && !recovery}
      <LoadingSpinner label="Loading actions" />
    {:else if !recovery?.actions?.length}
      <p class="text-base text-surface-400">{PIPELINE_COPY.pipelineTab.noActions}</p>
    {:else}
      <ul class="mb-3 divide-y divide-surface-700/60 overflow-y-auto rounded-lg border border-surface-700/60" role="listbox">
        {#each recoveryActionsSorted as act (act.action)}
          <li>
            <button
              type="button"
              class="flex w-full items-center justify-between gap-2 border-l-2 px-3 py-2 text-left text-sm hover:bg-surface-800/60 disabled:opacity-50 {act.action === selectedRecoveryAction ? 'border-accent bg-accent/10' : 'border-transparent'}"
              disabled={recoveryDispatchBlocked}
              on:click={() => (selectedRecoveryAction = act.action)}
            >
              <span class="text-surface-100">{act.label}</span>
              {#if act.action === recovery.recommended_action}
                <span class="text-[0.55rem] uppercase text-accent">{PIPELINE_COPY.pipelineTab.suggested}</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
      {#if selectedRecoverySpec}
        <p class="mb-2 text-base text-surface-300">{selectedRecoverySpec.description}</p>
        <textarea
          class="input-field mb-2 resize-none text-base"
          rows="2"
          bind:value={recoveryNote}
          placeholder={PIPELINE_COPY.pipelineTab.notePlaceholder}
          disabled={recoveryDispatchBlocked}
        ></textarea>
        <button
          type="button"
          class="btn-primary w-full text-base"
          disabled={recoveryDispatchBlocked}
          on:click={() => dispatch(selectedRecoverySpec.action)}
        >
          {recoveryBusy
            ? PIPELINE_COPY.pipelineTab.starting
            : PIPELINE_COPY.pipelineTab.runAction(selectedRecoverySpec.label)}
        </button>
        {#if showClearInflight}
          <button
            type="button"
            class="btn-secondary mt-2 w-full text-sm"
            disabled={cancelInflightBusy}
            on:click={cancelStaleInflight}
          >
            {cancelInflightBusy ? 'Clearing…' : 'Clear stuck dispatch (UI frozen / no log output)'}
          </button>
        {/if}
      {/if}
    {/if}
  </div>
  <div class="workspace-activity flex min-h-[22rem] flex-col lg:col-span-7 lg:pl-4">
    <div class="mb-2 flex items-center justify-between gap-2">
      <p class="text-base text-surface-400">{PIPELINE_COPY.pipelineTab.liveTerminalLabel}</p>
      {#if terminalActive}
        <span class="text-xs text-surface-500">{PIPELINE_COPY.pipelineTab.refreshHint}</span>
      {/if}
    </div>
    <div class="min-h-0 flex-1">
      <RoleTerminalLive active={terminalActive} title={terminalTitle} emptyMessage={terminalEmptyMessage} />
    </div>
    {#if feed.length > 0}
      <details class="mt-3 rounded-lg border border-surface-700/60 bg-surface-950/30 px-3 py-2">
        <summary class="cursor-pointer text-sm text-surface-400">Event summary ({feed.length})</summary>
        <ol class="mt-2 max-h-40 space-y-1 overflow-y-auto">
          {#each [...feed].reverse().slice(0, 12) as ev, i (i)}
            <li class="flex items-start gap-2 text-xs text-surface-400">
              <span class="shrink-0 uppercase {feedTone(ev)}">{ev.type.replace(/_/g, ' ')}</span>
              <span class="min-w-0 flex-1">{feedLabel(ev)}</span>
              <time class="shrink-0">{feedTime(ev.ts)}</time>
            </li>
          {/each}
        </ol>
      </details>
    {/if}
  </div>
</div>
