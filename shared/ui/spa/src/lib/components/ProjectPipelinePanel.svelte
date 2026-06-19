<script lang="ts">
  /**
   * Pipeline tab shell — composes isolated regions so high-frequency log updates
   * do not re-render recovery controls or the project page shell.
   */
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import PipelineRecoveryHeader from '$lib/components/PipelineRecoveryHeader.svelte';
  import PipelineRecoveryControls from '$lib/components/PipelineRecoveryControls.svelte';
  import PipelineActivityLog from '$lib/components/PipelineActivityLog.svelte';
  import { wsPipelineBootReady } from '$lib/stores/projectWorkspace';

  export let projectId: string;
  export let onSelectPipelineTab: () => void = () => {};
</script>

<PipelineRecoveryHeader />

<div
  class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0"
  data-testid="pipeline-controls"
>
  <div class="lg:col-span-5 lg:border-r lg:border-surface-700/60 lg:pr-4">
    <PipelineRecoveryControls {projectId} {onSelectPipelineTab} />
  </div>
  <div class="lg:col-span-7 lg:pl-4">
    {#if $wsPipelineBootReady}
      <PipelineActivityLog />
    {:else}
      <div class="flex min-h-[16rem] items-center justify-center rounded-lg border border-surface-700/60 bg-surface-950/30">
        <LoadingSpinner label="Preparing activity log" />
      </div>
    {/if}
  </div>
</div>
