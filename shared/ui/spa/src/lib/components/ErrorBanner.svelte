<!--
  Spine Hub SPA — ErrorBanner (V3 Wave 3 part 2, Squad SPA1).
  Dismissable error chrome. Severity-aware colour.
-->
<script lang="ts">
  import type { ToastKind } from '$lib/stores/toasts';
  export let kind: ToastKind = 'error';
  export let message: string;
  export let onDismiss: (() => void) | null = null;

  const tone: Record<ToastKind, string> = {
    info: 'bg-severity-info/10 text-blue-900 border-severity-info/40',
    success: 'bg-green-100 text-green-900 border-green-300',
    warning: 'bg-severity-warning/10 text-amber-900 border-severity-warning/40',
    error: 'bg-severity-critical/10 text-red-900 border-severity-critical/40'
  };
</script>

<div
  role={kind === 'error' ? 'alert' : 'status'}
  class="flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm {tone[kind]}"
>
  <span class="min-w-0 flex-1 break-words">{message}</span>
  {#if onDismiss}
    <button
      type="button"
      class="text-xs underline opacity-70 hover:opacity-100"
      on:click={() => onDismiss?.()}
    >
      dismiss
    </button>
  {/if}
</div>
