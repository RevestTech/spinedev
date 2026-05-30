<script lang="ts">
  /** Left column only — subscribes to recovery/run stores, not terminal feed. */
  import { onDestroy, onMount } from 'svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { PIPELINE_COPY } from '$lib/projectPipelineCopy';
  import { dispatchInFlightActive, isDispatchStale } from '$lib/projectRecoveryUtils';
  import {
    wsRecovery,
    wsRunState,
    wsRecoveryBusy,
    wsRecoveryLoading,
    wsRecoveryError,
    wsDispatchUiStale,
    wsDispatchRecovery,
    wsCancelInflight,
    wsLoadRecoveryNow,
  } from '$lib/stores/projectWorkspace';
  import { toasts } from '$lib/stores/toasts';

  export let projectId: string;
  export let onSelectPipelineTab: () => void = () => {};

  let recoveryNote = '';
  let selectedRecoveryAction: string | null = null;
  let cancelInflightBusy = false;
  let loadingStale = false;
  let loadingWatchStartedAt = 0;
  let staleTimer: ReturnType<typeof setInterval> | null = null;

  $: recovery = $wsRecovery;
  $: run = $wsRunState;
  $: recoveryBusy = $wsRecoveryBusy;
  $: recoveryLoading = $wsRecoveryLoading;
  $: recoveryError = $wsRecoveryError;

  $: if (recoveryLoading && !recovery) {
    if (!loadingWatchStartedAt) loadingWatchStartedAt = Date.now();
  } else {
    loadingWatchStartedAt = 0;
    loadingStale = false;
  }

  onMount(() => {
    staleTimer = setInterval(() => {
      if (recoveryLoading && !recovery && loadingWatchStartedAt) {
        loadingStale = Date.now() - loadingWatchStartedAt > 8000;
      }
    }, 1000);
  });

  onDestroy(() => {
    if (staleTimer !== null) clearInterval(staleTimer);
  });

  async function retryLoadRecovery() {
    loadingStale = false;
    loadingWatchStartedAt = Date.now();
    wsRecoveryError.set(null);
    await wsLoadRecoveryNow(projectId);
  }

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
</script>

{#if recoveryError}
  <div class="mb-3">
    <ErrorBanner kind="error" message={recoveryError} onDismiss={() => wsRecoveryError.set(null)} />
  </div>
{/if}

<p class="mb-2 text-base text-surface-400">{PIPELINE_COPY.pipelineTab.controlsLead}</p>
{#if recoveryLoading && !recovery}
  <LoadingSpinner label="Loading actions" />
  {#if loadingStale}
    <p class="mt-3 text-sm text-surface-400">
      Pipeline controls are taking longer than expected. The Hub API may be slow or the browser thread is busy.
    </p>
    <button type="button" class="btn-secondary mt-2 text-sm" on:click={retryLoadRecovery}>
      Retry loading actions
    </button>
  {/if}
{:else if !recovery?.actions?.length}
  <p class="text-base text-surface-400" data-testid="recovery-no-actions">{PIPELINE_COPY.pipelineTab.noActions}</p>
{:else}
  <div data-testid="recovery-actions-ready">
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
  </div>
{/if}
