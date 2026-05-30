<script lang="ts">
  import {
    PIPELINE_COPY,
    humanStuckReason,
    dispatchKindLabel,
    recoveryActionInfo,
  } from '$lib/projectPipelineCopy';
  import {
    dispatchInFlightActive,
    primaryStuckReason,
  } from '$lib/projectRecoveryUtils';
  import { wsRecovery, wsRunState, wsRecoveryBusy } from '$lib/stores/projectWorkspace';
  import { projectScopedDecisions } from '$lib/stores/projectDecisionsStore';

  export let projectPhase: string;
  export let codeReviewBlocked = false;
  export let onSelectDecisions: () => void = () => {};
  export let onSelectPipelineAndDispatch: (action: string) => void = () => {};

  const PHASES = ['intake', 'plan', 'build', 'verify', 'release'] as const;

  function phaseIndex(phase: string | undefined): number {
    if (!phase) return -1;
    const p = phase.toLowerCase();
    if (p === 'intake') return 0;
    if (p.startsWith('plan')) return 1;
    if (p.startsWith('build')) return 2;
    if (p.startsWith('verify') || p === 'acceptance') return 3;
    if (p === 'released' || p === 'release' || p === 'operate' || p === 'retro') return 4;
    return -1;
  }

  function pipelineRoleInfo(role: string) {
    const r = PIPELINE_COPY.roles[role as keyof typeof PIPELINE_COPY.roles];
    return r ?? { label: role, what: 'Processing project work', typical: '~60s' };
  }

  $: recovery = $wsRecovery;
  $: run = $wsRunState;
  $: recoveryBusy = $wsRecoveryBusy;
  $: decisionCount = $projectScopedDecisions.length;

  $: isPipelineStuck = Boolean(
    recovery?.stuck ||
      (codeReviewBlocked &&
        !run.activeRole &&
        decisionCount === 0 &&
        !dispatchInFlightActive(recovery))
  );

  $: effectiveStuckReasons = recovery?.reasons ?? [];

  $: selectedRecoverySpec = (() => {
    if (!recovery?.actions?.length) return null;
    const rec = recovery.recommended_action;
    const ids = recovery.actions.map((a) => a.action);
    const action = rec && ids.includes(rec) ? rec : recovery.actions[0]?.action;
    return recovery.actions.find((a) => a.action === action) ?? null;
  })();

  $: recoveryDispatchBlocked =
    recoveryBusy || run.activeRole !== null || dispatchInFlightActive(recovery);

  $: attentionLabel = (() => {
    if (decisionCount > 0) {
      return PIPELINE_COPY.attention.decisionsReview(decisionCount);
    }
    if (isPipelineStuck) return PIPELINE_COPY.attention.paused;
    return null;
  })();

  $: roleInfo = run.activeRole ? pipelineRoleInfo(run.activeRole) : null;

  $: pipelineStatusMode = (() => {
    if (run.activeRole) return 'working';
    if (dispatchInFlightActive(recovery)) return 'running';
    if (decisionCount > 0) return 'decisions';
    if (recovery?.last_role_failure?.error) return 'failed';
    if (isPipelineStuck) return 'blocked';
    return 'idle';
  })();

  $: pipelineHeadline = (() => {
    if (run.activeRole && roleInfo) return PIPELINE_COPY.status.working(roleInfo.label);
    const inflight = recovery?.dispatch_in_flight;
    if (dispatchInFlightActive(recovery) && inflight) {
      return PIPELINE_COPY.status.starting(dispatchKindLabel(inflight.dispatch_kind));
    }
    if (decisionCount > 0) {
      return PIPELINE_COPY.status.decisions(decisionCount);
    }
    if (isPipelineStuck && effectiveStuckReasons.length > 0) {
      return `${PIPELINE_COPY.status.pausedPrefix} — ${humanStuckReason(primaryStuckReason(effectiveStuckReasons))}`;
    }
    if (isPipelineStuck) return PIPELINE_COPY.attention.paused;
    if (recovery?.last_role_failure?.error) {
      const failedRole = recovery.last_role_failure.role ?? 'Previous step';
      return PIPELINE_COPY.status.failed(pipelineRoleInfo(failedRole).label);
    }
    return PIPELINE_COPY.status.idle;
  })();

  $: pipelineSubtext = (() => {
    if (run.activeRole && roleInfo) {
      return `${run.activeRoleMessage ?? roleInfo.what} · typical ${roleInfo.typical}`;
    }
    if (decisionCount > 0) return PIPELINE_COPY.subtext.decisions;
    if (isPipelineStuck && selectedRecoverySpec) {
      return PIPELINE_COPY.subtext.suggestedAction(selectedRecoverySpec.label);
    }
    if (dispatchInFlightActive(recovery)) {
      const action =
        recovery?.dispatch_in_flight?.action ??
        run.lastDispatchedAction ??
        recovery?.recommended_action;
      const info = action ? recoveryActionInfo(action) : null;
      if (info) return `${info.steps[0]} · typical ${info.typical}`;
      return PIPELINE_COPY.subtext.dispatchWaiting;
    }
    if (recovery?.last_role_failure?.error) return recovery.last_role_failure.error;
    return PIPELINE_COPY.subtext.background;
  })();

  function statusStripClass(mode: string): string {
    switch (mode) {
      case 'working':
      case 'running':
        return 'border-accent/40 bg-accent/10';
      case 'decisions':
      case 'blocked':
        return 'border-amber-400/40 bg-amber-400/10';
      case 'failed':
        return 'border-rose-500/40 bg-rose-500/10';
      default:
        return 'border-surface-600/80 bg-surface-800/50';
    }
  }
</script>

{#if attentionLabel}
  <div class="mb-4 flex flex-wrap items-center gap-3" data-testid="project-attention-badge">
    <span
      class="inline-flex items-center gap-2 rounded-full border border-amber-500/50 bg-amber-500/15 px-4 py-1.5 text-sm font-semibold text-amber-100"
    >
      {#if recovery?.stuck && decisionCount === 0}
        <span class="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true"></span>
      {/if}
      {attentionLabel}
    </span>
    {#if isPipelineStuck && selectedRecoverySpec && decisionCount === 0}
      <button
        type="button"
        class="btn-primary text-sm sm:text-base"
        disabled={recoveryDispatchBlocked}
        on:click={() => onSelectPipelineAndDispatch(selectedRecoverySpec.action)}
      >
        {recoveryBusy ? 'Starting…' : `Run ${selectedRecoverySpec.label}`}
      </button>
    {/if}
  </div>
{/if}

<div
  class="mb-5 rounded-lg border px-5 py-4 {statusStripClass(pipelineStatusMode)}"
  data-testid="pipeline-status-strip"
>
  <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
    <div class="min-w-0 flex-1">
      {#if run.activeRole && roleInfo}
        <div class="flex items-start gap-3">
          <span class="relative mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center">
            <span class="relative h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
          </span>
          <div class="min-w-0">
            <p class="pw-status-headline text-surface-50">{pipelineHeadline}</p>
            <p class="pw-status-sub mt-1 text-surface-300">{pipelineSubtext}</p>
          </div>
        </div>
      {:else}
        <p class="pw-status-headline text-surface-50">{pipelineHeadline}</p>
        <p class="pw-status-sub mt-1 text-surface-300">{pipelineSubtext}</p>
      {/if}
    </div>
    <div class="flex shrink-0 flex-wrap items-center gap-2">
      {#if decisionCount > 0}
        <button type="button" class="btn-primary text-base" on:click={onSelectDecisions}>
          {PIPELINE_COPY.decisions.reviewButton(decisionCount)}
        </button>
      {:else if isPipelineStuck && selectedRecoverySpec && !recoveryDispatchBlocked}
        <button
          type="button"
          class="btn-primary text-base"
          on:click={() => onSelectPipelineAndDispatch(selectedRecoverySpec.action)}
        >
          {recoveryBusy ? 'Starting…' : `Run ${selectedRecoverySpec.label}`}
        </button>
      {/if}
    </div>
  </div>
  <div class="mt-3 flex flex-wrap items-center gap-2">
    {#each PHASES as ph, i (ph)}
      {@const state = (() => {
        const idx = phaseIndex(projectPhase);
        return idx < 0 ? 'pending' : i < idx ? 'done' : i === idx ? 'active' : 'pending';
      })()}
      <span
        class="rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide sm:text-sm {state === 'active'
          ? 'bg-accent text-white'
          : state === 'done'
            ? 'border border-sky-500/40 bg-sky-500/10 text-sky-200'
            : 'border border-surface-600 bg-surface-800/40 text-surface-400'}"
      >{ph}</span>
      {#if i < PHASES.length - 1}<span class="text-base text-surface-600">→</span>{/if}
    {/each}
  </div>
</div>
