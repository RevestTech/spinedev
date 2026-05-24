<!--
  Spine Hub SPA — ErrorBanner (V3 Wave 3 part 2, Squad SPA1).
  Dismissable status chrome. Severity-aware colour; errors are actionable.
-->
<script lang="ts">
  import type { ToastKind } from '$lib/stores/toasts';
  export let kind: ToastKind = 'error';
  export let message: string;
  export let onDismiss: (() => void) | null = null;
  export let onRetry: (() => void) | null = null;
  export let retryLabel: string = 'Try again';

  const tone: Record<ToastKind, string> = {
    info: 'border-severity-info/40 bg-severity-info/10 text-sky-100',
    success: 'border-green-500/40 bg-green-500/10 text-green-100',
    warning: 'border-severity-warning/40 bg-severity-warning/10 text-amber-100',
    error: 'border-severity-critical/40 bg-severity-critical/10 text-red-100'
  };
</script>

<div
  role={kind === 'error' ? 'alert' : 'status'}
  aria-live={kind === 'error' ? 'assertive' : 'polite'}
  class="flex items-start justify-between gap-3 rounded-md border px-3 py-2.5 text-sm {tone[kind]}"
>
  <span class="min-w-0 flex-1 break-words">{message}</span>
  <div class="flex shrink-0 items-center gap-2">
    {#if onRetry}
      <button
        type="button"
        class="rounded px-2 py-0.5 text-xs font-medium underline decoration-white/40 underline-offset-2 hover:decoration-white/80"
        on:click={() => onRetry?.()}
      >
        {retryLabel}
      </button>
    {/if}
    {#if onDismiss}
      <button
        type="button"
        class="rounded px-2 py-0.5 text-xs font-medium underline decoration-white/40 underline-offset-2 hover:decoration-white/80"
        aria-label="Dismiss notification"
        on:click={() => onDismiss?.()}
      >
        Dismiss
      </button>
    {/if}
    <slot name="actions" />
  </div>
</div>
