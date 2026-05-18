<!--
  Spine Hub SPA — EmptyState (V3 Wave 3 part 2, Squad SPA1).
  Shown when a panel has no data to render.
-->
<script lang="ts">
  export let title: string = 'Nothing here yet';
  export let message: string = '';
</script>

<div class="panel-card mx-auto flex max-w-md flex-col items-center gap-2 py-10 text-center">
  <h2 class="text-base font-semibold text-surface-900 dark:text-surface-50">{title}</h2>
  {#if message}
    <p class="text-sm text-surface-700 dark:text-surface-200">{message}</p>
  {/if}
  <slot />
</div>
