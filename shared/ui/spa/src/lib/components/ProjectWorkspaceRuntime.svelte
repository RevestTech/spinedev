<script lang="ts">
  /** Side effects only — polls and SSE flags; no DOM so parent +page never re-renders on recovery ticks. */
  import { onDestroy, onMount } from 'svelte';
  import { decisions } from '$lib/stores/decisions';
  import {
    wsRecovery,
    wsPipelineBootReady,
    wsSetSseLive,
    wsBind,
    scheduleLoadRecovery,
    type RecoveryStatus,
  } from '$lib/stores/projectWorkspace';
  import { dispatchInFlightActive } from '$lib/projectRecoveryUtils';

  export let projectId: string;
  export let matchKeys: string[] = [];

  let fallbackPollHandle: number | null = null;
  let dispatchPollHandle: number | null = null;
  const FALLBACK_POLL_MS = 45_000;
  const DISPATCH_POLL_MS = 10_000;

  let sseLive = false;
  let recoverySnapshot: RecoveryStatus | null = null;
  let boundProjectId: string | null = null;
  let boundMatchSig = '';

  function matchSig(keys: string[]): string {
    return keys.filter(Boolean).join('\0');
  }

  function bindWorkspace(id: string, keys: string[]): void {
    const sig = matchSig(keys);
    if (boundProjectId === id && boundMatchSig === sig) return;
    boundProjectId = id;
    boundMatchSig = sig;
    wsBind(id, keys);
  }

  function startFallbackPoll() {
    if (fallbackPollHandle !== null || !projectId) return;
    fallbackPollHandle = window.setInterval(() => {
      scheduleLoadRecovery(projectId);
    }, FALLBACK_POLL_MS) as unknown as number;
  }

  function stopFallbackPoll() {
    if (fallbackPollHandle !== null) {
      window.clearInterval(fallbackPollHandle);
      fallbackPollHandle = null;
    }
  }

  function startDispatchPoll() {
    if (dispatchPollHandle !== null || !projectId) return;
    dispatchPollHandle = window.setInterval(() => {
      scheduleLoadRecovery(projectId, true);
    }, DISPATCH_POLL_MS) as unknown as number;
  }

  function stopDispatchPoll() {
    if (dispatchPollHandle !== null) {
      window.clearInterval(dispatchPollHandle);
      dispatchPollHandle = null;
    }
  }

  function syncPollers() {
    wsSetSseLive(sseLive);
    if (sseLive) {
      stopFallbackPoll();
    } else {
      startFallbackPoll();
    }
    if (dispatchInFlightActive(recoverySnapshot) && !sseLive) {
      startDispatchPoll();
    } else {
      stopDispatchPoll();
    }
  }

  $: if (projectId && $wsPipelineBootReady) {
    bindWorkspace(projectId, matchKeys);
  }

  onMount(() => {
    const unsubDecisions = decisions.subscribe((s) => {
      if (s.liveConnected === sseLive) return;
      sseLive = s.liveConnected;
      syncPollers();
    });
    const unsubRecovery = wsRecovery.subscribe((r) => {
      recoverySnapshot = r;
      syncPollers();
    });
    return () => {
      unsubDecisions();
      unsubRecovery();
    };
  });

  onDestroy(() => {
    stopFallbackPoll();
    stopDispatchPoll();
  });
</script>
