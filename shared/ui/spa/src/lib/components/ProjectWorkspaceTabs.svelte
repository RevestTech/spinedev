<script lang="ts">
  import { PIPELINE_COPY } from '$lib/projectPipelineCopy';
  import { dispatchInFlightActive } from '$lib/projectRecoveryUtils';
  import { projectScopedDecisions } from '$lib/stores/projectDecisionsStore';
  import { wsRecovery, wsRunState } from '$lib/stores/projectWorkspace';

  import type { WorkspaceTab } from '$lib/projectWorkspaceTypes';

  export type { WorkspaceTab };

  export let workspaceTab: WorkspaceTab;
  export let onSelectTab: (tab: WorkspaceTab) => void;
  export let projectPhase: string | undefined = undefined;
  export let showArtifacts = false;
  export let artifactCount = 0;
  export let codeFileCount = 0;
  export let codeReviewBlocked = false;

  $: decisionCount = $projectScopedDecisions.length;
  $: activeRole = $wsRunState.activeRole;
  $: recovery = $wsRecovery;

  $: isPipelineStuck = Boolean(
    recovery?.stuck ||
      (codeReviewBlocked &&
        !activeRole &&
        decisionCount === 0 &&
        !dispatchInFlightActive(recovery))
  );

  $: tabs = (() => {
    const out: { id: WorkspaceTab; label: string; count?: number; attention?: boolean }[] = [];
    if (projectPhase === 'intake') out.push({ id: 'intake', label: 'Intake' });
    out.push({
      id: 'decisions',
      label: 'Decisions',
      count: decisionCount || undefined,
    });
    out.push({
      id: 'pipeline',
      label: 'Pipeline',
      attention: Boolean(isPipelineStuck && !activeRole && decisionCount === 0),
    });
    if (showArtifacts) {
      out.push({
        id: 'artifacts',
        label: 'Artifacts',
        count: artifactCount || undefined,
      });
    }
    if (codeFileCount > 0) {
      out.push({ id: 'code', label: 'Code', count: codeFileCount });
    }
    return out;
  })();
</script>

<nav
  class="workspace-tab-bar flex flex-wrap items-center gap-1 border-b border-surface-700/60 pb-0"
  role="tablist"
  aria-label="Project workspace"
>
  {#each tabs as tab (tab.id)}
    <button
      type="button"
      role="tab"
      aria-selected={workspaceTab === tab.id}
      class="workspace-tab-btn relative px-4 py-3 text-base font-medium transition-colors {workspaceTab === tab.id
        ? 'text-accent'
        : 'text-surface-400 hover:text-surface-200'}"
      on:click={() => onSelectTab(tab.id)}
    >
      {tab.label}
      {#if tab.count}
        <span
          class="ml-2 rounded-full bg-accent/20 px-2 py-0.5 text-xs font-semibold text-accent sm:text-sm"
          >{tab.count}</span
        >
      {:else if tab.attention}
        <span
          class="ml-2 rounded-full border border-amber-500/50 bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-200 sm:text-sm"
          >{PIPELINE_COPY.pipelineTab.badgeActionRequired}</span
        >
      {/if}
    </button>
  {/each}
</nav>

<style>
  .workspace-tab-btn[aria-selected='true'] {
    box-shadow: inset 0 -2px 0 0 rgb(139 92 246);
  }
</style>
