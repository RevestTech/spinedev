<!--
  Reusable confirmation dialog — replaces window.confirm for destructive actions.
-->
<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let open = false;
  export let title = 'Confirm';
  export let message = '';
  export let confirmLabel = 'Confirm';
  export let cancelLabel = 'Cancel';
  export let variant: 'default' | 'danger' | 'warning' = 'default';
  export let busy = false;

  const dispatch = createEventDispatcher<{ confirm: void; cancel: void }>();

  function onBackdrop(e: MouseEvent) {
    if (busy) return;
    if (e.target === e.currentTarget) dispatch('cancel');
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open || busy) return;
    if (e.key === 'Escape') dispatch('cancel');
  }

  $: confirmClass =
    variant === 'danger'
      ? 'btn-danger'
      : variant === 'warning'
        ? 'btn-secondary border-severity-warning/60 text-severity-warning'
        : 'btn-primary';
</script>

<svelte:window on:keydown={onKeydown} />

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center"
    role="presentation"
    on:click={onBackdrop}
    data-testid="confirm-dialog-backdrop"
  >
    <div
      class="w-full max-w-md rounded-t-xl border border-surface-700/80 bg-surface-900 p-5 shadow-card sm:rounded-xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      data-testid="confirm-dialog"
    >
      <h2 id="confirm-dialog-title" class="text-lg font-semibold text-surface-50">{title}</h2>
      {#if message}
        <p class="mt-2 text-sm leading-relaxed text-surface-300">{message}</p>
      {/if}
      <slot />
      <div class="mt-5 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          class="btn-ghost"
          disabled={busy}
          on:click={() => dispatch('cancel')}
          data-testid="confirm-dialog-cancel"
        >
          {cancelLabel}
        </button>
        <button
          type="button"
          class={confirmClass}
          disabled={busy}
          on:click={() => dispatch('confirm')}
          data-testid="confirm-dialog-confirm"
        >
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </div>
  </div>
{/if}
