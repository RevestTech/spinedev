<!--
  Spine Hub SPA — EmptyState (V3 Wave 3 part 2, Squad SPA1).
  Shown when a panel has no data to render. Always explain what to do next.
-->
<script lang="ts">
  export let title: string = 'Nothing to show';
  /** Primary explanation — what this empty view means. */
  export let message: string =
    'Nothing to display in this view yet. Adjust filters or refresh once the Hub has data.';
  /** Optional extra next-step guidance. Leave empty to omit. */
  export let hint: string = '';

  const titleId = `empty-state-title-${Math.random().toString(36).slice(2, 9)}`;
</script>

<div
  class="panel-card mx-auto flex max-w-md flex-col items-center gap-3 py-10 text-center"
  role="region"
  aria-labelledby={titleId}
>
  <h2 id={titleId} class="text-base font-semibold text-surface-50">{title}</h2>
  {#if message}
    <p class="text-sm text-surface-300">{message}</p>
  {/if}
  {#if hint}
    <p class="text-sm text-surface-400">{hint}</p>
  {/if}
  <div class="mt-1 flex flex-wrap items-center justify-center gap-2">
    <slot />
  </div>
</div>
