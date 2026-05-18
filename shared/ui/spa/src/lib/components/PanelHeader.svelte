<!--
  Spine Hub SPA — PanelHeader (V3 Wave 3 part 2, Squad SPA1).

  Standard heading bar for every panel page. Slot-driven so panels can
  drop action buttons / filter controls on the right.
-->
<script lang="ts">
  export let title: string;
  export let subtitle: string | null = null;
</script>

<header class="mb-4 flex flex-col gap-2 border-b border-surface-200 pb-3 dark:border-surface-700 sm:mb-6 sm:flex-row sm:items-center sm:justify-between">
  <div class="min-w-0">
    <h1 class="text-lg font-semibold text-surface-900 dark:text-surface-50 sm:text-xl">
      {title}
    </h1>
    {#if subtitle}
      <p class="mt-0.5 truncate text-sm text-surface-700 dark:text-surface-200">{subtitle}</p>
    {/if}
  </div>
  <div class="flex flex-wrap items-center gap-2">
    <slot />
  </div>
</header>
