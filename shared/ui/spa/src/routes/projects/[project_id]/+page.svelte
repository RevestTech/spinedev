<!--
  Spine Hub SPA — Project workspace.

  Per-project SDLC workspace. Phase pipeline at the top; intake chat
  (real LLM-backed product role) below while in intake phase; switches
  to PRD review / build dashboard as phases advance.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import { api } from '$lib/api/client';

  $: projectId = $page.params.project_id;

  interface ProjectRow {
    project_id: string;
    name: string;
    project_type: string;
    current_phase: string;
    status: string;
    owner?: string;
  }
  let project: ProjectRow | null = null;
  let projectLoading = true;
  let projectError: string | null = null;

  const PHASES = ['intake', 'plan', 'build', 'verify', 'release'] as const;
  type Phase = (typeof PHASES)[number];

  function phaseIndex(p: string | undefined): number {
    return p ? (PHASES as readonly string[]).indexOf(p) : -1;
  }

  interface Turn {
    role: 'user' | 'assistant';
    content: string;
  }
  let transcript: Turn[] = [];
  let userInput = '';
  let chatBusy = false;
  let chatError: string | null = null;
  let intakeDone = false;
  let chatScroller: HTMLDivElement;

  async function loadProject() {
    projectLoading = true;
    projectError = null;
    try {
      const list = await api.get<{ items: string[] }>(`/api/v2/projects?limit=200`);
      // items are JSON-encoded strings; find ours by id.
      const rows: ProjectRow[] = (list.items ?? []).map((s) =>
        typeof s === 'string' ? JSON.parse(s) : (s as ProjectRow)
      );
      project = rows.find((r) => r.project_id === projectId) ?? null;
      if (!project) projectError = `project ${projectId} not found in list`;
    } catch (e) {
      projectError = (e as Error).message || 'failed to load project';
    } finally {
      projectLoading = false;
    }
  }

  async function sendIntake() {
    if (!project || !userInput.trim() || chatBusy || intakeDone) return;
    const msg = userInput.trim();
    chatBusy = true;
    chatError = null;
    // Optimistic user-turn render so the UI feels responsive.
    transcript = [...transcript, { role: 'user', content: msg }];
    userInput = '';
    await tick();
    chatScroller?.scrollTo({ top: chatScroller.scrollHeight, behavior: 'smooth' });
    try {
      const res = await api.post<{
        reply: string;
        transcript: Turn[];
        done: boolean;
        model: string;
      }>(`/api/v2/projects/${projectId}/intake/chat`, {
        message: msg,
        transcript: transcript.slice(0, -1), // server expects prior turns sans the just-added user turn
        project_name: project.name,
        project_type: project.project_type,
        greenfield: false // TODO: thread through from project metadata when stored
      });
      transcript = res.transcript;
      intakeDone = res.done;
      await tick();
      chatScroller?.scrollTo({ top: chatScroller.scrollHeight, behavior: 'smooth' });
    } catch (e) {
      // Roll the optimistic user-turn back on failure.
      transcript = transcript.slice(0, -1);
      userInput = msg;
      chatError = (e as Error).message || 'intake chat failed';
    } finally {
      chatBusy = false;
    }
  }

  async function kickoff() {
    // Auto-fire an opening turn so the user sees the role talking first.
    if (!project || transcript.length > 0) return;
    transcript = [];
    userInput = `Start the intake for project "${project.name}" (${project.project_type}).`;
    await sendIntake();
  }

  onMount(async () => {
    await loadProject();
    if (project?.current_phase === 'intake') kickoff();
  });
</script>

<PanelHeader
  title={project?.name ?? 'Project workspace'}
  subtitle={project ? `${project.project_type} · phase: ${project.current_phase} · ${project.status}` : 'Loading…'}
>
  <a href="{base}/" class="btn-ghost text-sm">← Dashboard</a>
</PanelHeader>

{#if projectError}
  <div class="mb-4"><ErrorBanner kind="error" message={projectError} onDismiss={() => (projectError = null)} /></div>
{/if}

{#if projectLoading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading project" /></div>
{:else if project}
  <!-- Phase pipeline -->
  <section class="panel-card mb-6">
    <h2 class="mb-3 text-sm font-semibold text-surface-900 dark:text-surface-50">SDLC pipeline</h2>
    <ol class="flex flex-wrap items-center gap-2 text-xs">
      {#each PHASES as ph, i (ph)}
        {@const state = (() => {
          const idx = phaseIndex(project.current_phase);
          return idx < 0 ? 'pending' : i < idx ? 'done' : i === idx ? 'active' : 'pending';
        })()}
        <li
          class="rounded-full px-3 py-1 font-medium"
          class:bg-accent={state === 'active'}
          class:text-white={state === 'active'}
          class:bg-severity-info={state === 'done'}
          class:bg-surface-200={state === 'pending'}
          class:text-surface-700={state === 'pending'}
          class:dark:bg-surface-700={state === 'pending'}
          class:dark:text-surface-200={state === 'pending'}
        >
          {i + 1}. {ph}
        </li>
        {#if i < PHASES.length - 1}
          <li class="text-surface-700/40 dark:text-surface-200/40" aria-hidden="true">→</li>
        {/if}
      {/each}
    </ol>
  </section>

  {#if project.current_phase === 'intake'}
    <!-- Intake chat -->
    <section class="panel-card flex flex-col gap-3" style="min-height: 28rem;">
      <header class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">
          Intake with the product role
        </h2>
        {#if intakeDone}
          <span class="rounded-full bg-severity-info px-3 py-1 text-xs text-white">
            ✓ Intake complete — drafting PRD next
          </span>
        {/if}
      </header>

      <div
        bind:this={chatScroller}
        class="flex-1 overflow-y-auto rounded-md border border-surface-200 bg-surface-50 p-3 dark:border-surface-700 dark:bg-surface-900"
        style="max-height: 32rem;"
        data-testid="intake-transcript"
      >
        {#if transcript.length === 0}
          <p class="text-sm text-surface-700/70 dark:text-surface-200/70">
            Starting intake…
          </p>
        {/if}
        {#each transcript as turn, i (i)}
          <div class="mb-3 flex gap-2" class:justify-end={turn.role === 'user'}>
            <div
              class="max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm"
              class:bg-accent={turn.role === 'user'}
              class:text-white={turn.role === 'user'}
              class:bg-white={turn.role === 'assistant'}
              class:dark:bg-surface-800={turn.role === 'assistant'}
              class:border={turn.role === 'assistant'}
              class:border-surface-200={turn.role === 'assistant'}
              class:dark:border-surface-700={turn.role === 'assistant'}
            >
              <div class="mb-1 text-[0.65rem] uppercase tracking-wide opacity-70">
                {turn.role === 'user' ? 'You' : 'product role'}
              </div>
              {turn.content}
            </div>
          </div>
        {/each}
        {#if chatBusy}
          <div class="mb-3 flex gap-2">
            <div class="rounded-lg border border-surface-200 bg-white px-3 py-2 text-sm dark:border-surface-700 dark:bg-surface-800">
              <LoadingSpinner label="Thinking" />
            </div>
          </div>
        {/if}
      </div>

      {#if chatError}
        <ErrorBanner kind="error" message={chatError} onDismiss={() => (chatError = null)} />
      {/if}

      {#if !intakeDone}
        <form on:submit|preventDefault={sendIntake} class="flex items-end gap-2">
          <textarea
            bind:value={userInput}
            placeholder="Type your answer… (Enter to send, Shift+Enter for newline)"
            rows="2"
            class="flex-1 rounded-md border border-surface-300 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none dark:border-surface-600 dark:bg-surface-700 dark:text-surface-50"
            disabled={chatBusy}
            on:keydown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendIntake();
              }
            }}
            data-testid="intake-input"
          ></textarea>
          <button
            type="submit"
            class="btn-primary"
            disabled={chatBusy || !userInput.trim()}
            data-testid="intake-send"
          >
            {chatBusy ? '…' : 'Send'}
          </button>
        </form>
      {:else}
        <div class="rounded-md border border-severity-info/30 bg-severity-info/10 p-3 text-sm">
          The product role has enough to draft a PRD. PRD generation +
          approval card lands in the next iteration — for now the
          transcript above is the requirements record. Refresh
          <a href="{base}/panels/decision-queue" class="text-accent underline">decisions</a>
          shortly.
        </div>
      {/if}
    </section>
  {:else}
    <section class="panel-card">
      <p class="text-sm text-surface-700 dark:text-surface-200">
        Workspace view for phase <strong>{project.current_phase}</strong> not yet
        implemented in this iteration. Use the
        <a href="{base}/panels/decision-queue" class="text-accent underline">decision queue</a>
        to see what's pending.
      </p>
    </section>
  {/if}
{/if}
