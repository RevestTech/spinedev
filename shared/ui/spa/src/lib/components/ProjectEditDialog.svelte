<!--
  Edit project name + description (brief).
-->
<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let open = false;
  export let name = '';
  export let description = '';
  export let busy = false;
  export let error: string | null = null;

  const dispatch = createEventDispatcher<{ save: { name: string; description: string }; cancel: void }>();

  function onBackdrop(e: MouseEvent) {
    if (busy) return;
    if (e.target === e.currentTarget) dispatch('cancel');
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open || busy) return;
    if (e.key === 'Escape') dispatch('cancel');
  }

  function submit() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    dispatch('save', { name: trimmed, description: description.trim() });
  }
</script>

<svelte:window on:keydown={onKeydown} />

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center"
    role="presentation"
    on:click={onBackdrop}
    data-testid="project-edit-backdrop"
  >
    <form
      class="w-full max-w-lg rounded-t-xl border border-surface-700/80 bg-surface-900 p-5 shadow-card sm:rounded-xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-edit-title"
      data-testid="project-edit-dialog"
      on:submit|preventDefault={submit}
    >
      <h2 id="project-edit-title" class="text-lg font-semibold text-surface-50">Edit project</h2>
      <p class="mt-1 text-sm text-surface-400">Update the display name and intake brief.</p>

      {#if error}
        <p class="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
          {error}
        </p>
      {/if}

      <label class="mt-4 block">
        <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-surface-400">Name</span>
        <input
          class="input-field"
          bind:value={name}
          maxlength="200"
          required
          disabled={busy}
          data-testid="project-edit-name"
        />
      </label>

      <label class="mt-3 block">
        <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-surface-400">Brief</span>
        <textarea
          class="input-field min-h-[5rem] resize-y"
          bind:value={description}
          maxlength="2000"
          rows="3"
          disabled={busy}
          placeholder="Optional product brief for intake…"
          data-testid="project-edit-description"
        ></textarea>
      </label>

      <div class="mt-5 flex flex-wrap justify-end gap-2">
        <button type="button" class="btn-ghost" disabled={busy} on:click={() => dispatch('cancel')}>
          Cancel
        </button>
        <button type="submit" class="btn-primary" disabled={busy || !name.trim()} data-testid="project-edit-save">
          {busy ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </form>
  </div>
{/if}
