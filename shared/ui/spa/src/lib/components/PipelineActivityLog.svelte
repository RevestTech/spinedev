<script lang="ts">
  /**
   * Live terminal + event summary — isolated leaf: only this subtree re-renders
   * when log lines or feed events arrive (not recovery controls / chrome).
   */
  import RoleTerminal from '$lib/components/RoleTerminal.svelte';
  import { PIPELINE_COPY, dispatchKindLabel } from '$lib/projectPipelineCopy';
  import { dispatchInFlightActive, isDispatchStale } from '$lib/projectRecoveryUtils';
  import {
    wsRecovery,
    wsRunState,
    wsRecoveryBusy,
    wsTerminal,
    wsFeed,
    type FeedEvent,
  } from '$lib/stores/projectWorkspace';

  function pipelineRoleInfo(role: string) {
    const r = PIPELINE_COPY.roles[role as keyof typeof PIPELINE_COPY.roles];
    return r ?? { label: role, what: 'Processing project work', typical: '~60s' };
  }

  $: recovery = $wsRecovery;
  $: run = $wsRunState;
  $: recoveryBusy = $wsRecoveryBusy;
  $: feed = $wsFeed;
  $: lines = $wsTerminal;

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

<div class="workspace-activity flex min-h-[22rem] flex-col">
  <div class="mb-2 flex items-center justify-between gap-2">
    <p class="text-base text-surface-400">{PIPELINE_COPY.pipelineTab.liveTerminalLabel}</p>
    {#if terminalActive}
      <span class="text-xs text-surface-500">{PIPELINE_COPY.pipelineTab.refreshHint}</span>
    {/if}
  </div>
  <div class="min-h-0 flex-1">
    <RoleTerminal {lines} active={terminalActive} title={terminalTitle} emptyMessage={terminalEmptyMessage} />
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
