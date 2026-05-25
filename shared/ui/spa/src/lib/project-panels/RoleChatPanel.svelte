<!--
  Spine Hub SPA — Talk-to-a-Role panel (V3 Wave 3 part 2, Squad SPA1).

  Surfaces backend at shared/api/routes/role_chat.py:
    POST /api/v2/role-chat { role, message, project_id?, correlation_id? }
      → { role, reply, actor, audit_event_uuid, metadata }

  Per design decisions:
    - #3   one of the 9 enumerated Hub surfaces
    - #12  Cite-or-Refuse — if reply.metadata.citations is non-empty, render
           a row of <CitationChip /> beneath the assistant message
    - #25  Cookie/Bearer auth handled by apiFetch; this panel sees no tokens

  Wave 3 part 2 backend ships a placeholder reply when the MCP tool is not
  yet registered (see role_chat.py KeyError path). The panel handles that
  by surfacing the `metadata.stub` flag visually so QA can tell a real
  reply apart from the stub.

  Streaming reply: the current backend returns synchronously; the panel
  is structured to swap in a streaming SSE variant later without UI churn
  (each message has an `inProgress` flag; the streaming path will append
  partials to that message instead of replacing it).

  Responsive behaviour:
    - 390/393 px (phones)  : full-width chat column, composer pinned bottom
    - 768 px (iPad)        : chat column max-w-chat (48rem), centered
    - >= 1024 px (desktop) : same, with role-picker sidebar inline-left
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { api } from '$lib/api/client';
  import { toasts } from '$lib/stores/toasts';
  import type { Citation, RoleChatRequest, RoleChatResponse, RoleList } from '$lib/api/types';

  export let projectId = '';

  interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    text: string;
    citations?: Citation[];
    stub?: boolean;
    actor?: string;
    inProgress?: boolean;
    error?: string;
  }

  let chatRoles: string[] = [];
  let rolesLoading = true;
  let rolesError: string | null = null;
  let selectedRole = '';
  let messages: ChatMessage[] = [];
  let composer: string = '';
  let busy = false;
  let panelError: string | null = null;
  let scroller: HTMLElement | null = null;

  async function loadRoles() {
    rolesLoading = true;
    rolesError = null;
    try {
      const res = await api.get<RoleList>('/api/v2/registry/roles');
      chatRoles = (res.items ?? [])
        .filter((r) => r.tier === 'project')
        .map((r) => r.name)
        .sort();
      if (chatRoles.length === 0) {
        rolesError = 'No project-tier roles in the registry.';
        selectedRole = '';
        return;
      }
      if (!selectedRole || !chatRoles.includes(selectedRole)) {
        selectedRole = chatRoles[0];
      }
    } catch (err) {
      rolesError = (err as Error).message || 'failed to load roles';
      chatRoles = [];
      selectedRole = '';
    } finally {
      rolesLoading = false;
    }
  }

  onMount(loadRoles);

  function newMessageId(): string {
    return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  }

  async function send() {
    const text = composer.trim();
    if (!text || busy || !selectedRole) return;
    panelError = null;

    const userMsg: ChatMessage = { id: newMessageId(), role: 'user', text };
    const assistantMsg: ChatMessage = {
      id: newMessageId(),
      role: 'assistant',
      text: '',
      inProgress: true
    };
    messages = [...messages, userMsg, assistantMsg];
    composer = '';
    busy = true;
    await tick();
    scrollToBottom();

    const body: RoleChatRequest = {
      role: selectedRole,
      message: text,
      ...(projectId ? { project_id: projectId } : {})
    };
    try {
      const resp = await api.post<RoleChatResponse>('/api/v2/role-chat', body);
      const citations = (resp.metadata?.citations ?? []) as Citation[];
      messages = messages.map((m) =>
        m.id === assistantMsg.id
          ? {
              ...m,
              text: resp.reply,
              citations: Array.isArray(citations) ? citations : [],
              stub: Boolean(resp.metadata?.stub),
              actor: resp.actor,
              inProgress: false
            }
          : m
      );
    } catch (err) {
      const msg = (err as Error).message || 'role chat failed';
      messages = messages.map((m) =>
        m.id === assistantMsg.id ? { ...m, text: '', error: msg, inProgress: false } : m
      );
      panelError = msg;
      toasts.push({ kind: 'error', message: msg });
    } finally {
      busy = false;
      await tick();
      scrollToBottom();
    }
  }

  function scrollToBottom() {
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  function handleKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }
</script>

<PanelHeader title="Talk to a role" subtitle="Chat with any configured Spine role using its charter prompt">
  <label class="flex items-center gap-2 text-sm">
    <span class="text-surface-700 dark:text-surface-200">Role</span>
    <select
      class="rounded-md border border-surface-200 bg-white px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
      bind:value={selectedRole}
      disabled={rolesLoading || chatRoles.length === 0}
      data-testid="role-select"
    >
      {#if rolesLoading}
        <option value="">Loading…</option>
      {:else if chatRoles.length === 0}
        <option value="">No roles</option>
      {:else}
        {#each chatRoles as r}
          <option value={r}>{r}</option>
        {/each}
      {/if}
    </select>
  </label>
</PanelHeader>

{#if rolesError}
  <div class="mb-3"><ErrorBanner kind="error" message={rolesError} onDismiss={() => (rolesError = null)} /></div>
{/if}

{#if panelError}
  <div class="mb-3"><ErrorBanner kind="error" message={panelError} onDismiss={() => (panelError = null)} /></div>
{/if}

<section
  class="mx-auto flex h-[calc(100vh-14rem)] max-w-chat flex-col gap-3"
  aria-label="Role chat"
>
  <div
    bind:this={scroller}
    class="flex-1 space-y-3 overflow-y-auto rounded-lg border border-surface-200 bg-white p-3 dark:border-surface-700 dark:bg-surface-800"
    data-testid="chat-log"
  >
    {#if messages.length === 0}
      <p class="text-sm text-surface-700 dark:text-surface-200">
        Send a message to start a conversation with the <b>{selectedRole}</b> role.
        Replies cite their sources per design decision #12 (Cite-or-Refuse).
      </p>
    {/if}

    {#each messages as m (m.id)}
      <article
        class="flex w-full flex-col gap-1"
        class:items-end={m.role === 'user'}
        class:items-start={m.role === 'assistant'}
        data-message-role={m.role}
      >
        <div
          class="max-w-[85%] rounded-2xl px-3 py-2 text-sm sm:max-w-[75%]"
          class:bg-accent={m.role === 'user'}
          class:text-white={m.role === 'user'}
          class:bg-surface-100={m.role === 'assistant'}
          class:dark:bg-surface-700={m.role === 'assistant'}
          class:text-surface-900={m.role === 'assistant'}
          class:dark:text-surface-50={m.role === 'assistant'}
        >
          {#if m.inProgress}
            <LoadingSpinner size="sm" label={`${selectedRole} is thinking…`} />
          {:else if m.error}
            <span class="text-severity-critical">{m.error}</span>
          {:else}
            <span class="whitespace-pre-wrap break-words">{m.text}</span>
          {/if}

          {#if m.stub}
            <span class="ml-2 rounded-full bg-severity-warning px-1.5 py-0.5 text-[0.6rem] uppercase text-white">
              stub
            </span>
          {/if}
        </div>

        {#if m.role === 'assistant' && m.citations && m.citations.length > 0}
          <div class="flex max-w-[85%] flex-wrap gap-1 sm:max-w-[75%]" data-testid="citation-row">
            {#each m.citations as cite, i (i)}
              <CitationChip citation={cite} />
            {/each}
          </div>
        {/if}

        {#if m.role === 'assistant' && m.actor && !m.inProgress && !m.error}
          <span class="text-[0.65rem] text-surface-700/70 dark:text-surface-200/70">
            via {m.actor}
          </span>
        {/if}
      </article>
    {/each}
  </div>

  <form
    class="flex items-end gap-2"
    on:submit|preventDefault={send}
    data-testid="composer"
  >
    <textarea
      class="min-h-[44px] flex-1 resize-none rounded-md border border-surface-200 bg-white px-3 py-2 text-sm dark:border-surface-700 dark:bg-surface-800"
      placeholder={`Message ${selectedRole}…`}
      rows="2"
      bind:value={composer}
      on:keydown={handleKey}
      disabled={busy}
      data-testid="composer-input"
    ></textarea>
    <button
      type="submit"
      class="btn-primary"
      disabled={busy || !selectedRole || composer.trim().length === 0}
      data-testid="composer-send"
    >
      {busy ? 'Sending…' : 'Send'}
    </button>
  </form>
</section>
