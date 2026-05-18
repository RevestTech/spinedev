<!--
  Spine Hub SPA — LoadingSpinner (V3 Wave 3 part 2, Squad SPA1).
  Pure CSS spinner; no SVG dependency so the SPA bundle stays small.
-->
<script lang="ts">
  export let label: string = 'Loading';
  export let size: 'sm' | 'md' | 'lg' = 'md';
  const dims = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' } as const;
</script>

<div role="status" aria-live="polite" class="inline-flex items-center gap-2 text-surface-700 dark:text-surface-200">
  <span
    class="inline-block animate-spin rounded-full border-2 border-surface-200 border-t-accent {dims[size]}"
    aria-hidden="true"
  ></span>
  <span class="text-sm">{label}</span>
</div>
