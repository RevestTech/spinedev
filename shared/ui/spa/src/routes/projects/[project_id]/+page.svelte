<!--
  Spine Hub SPA — Project workspace.

  Phase-aware: shows intake chat during intake; shows artifacts (PRD,
  TRD, impl plan, QA plan) as they accumulate in project metadata.
  Polls every 4s to pick up live phase + artifact updates from the
  background role dispatcher.
-->
<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import { api } from '$lib/api/client';

  $: projectId = $page.params.project_id;

  interface ProjectFull {
    id: number;
    project_id: string;
    name: string;
    project_type: string;
    current_phase: string;
    status: string;
    owner?: string;
    metadata: Record<string, any>;
    prd_md?: string | null;
  }
  let project: ProjectFull | null = null;
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

  let pollHandle: number | null = null;

  async function loadProject() {
    try {
      const res = await api.get<ProjectFull>(`/api/v2/projects/${projectId}/full`);
      project = res;
      projectError = null;
    } catch (e) {
      const msg = (e as Error).message || 'failed to load project';
      // Project not found = likely the Hub volume was wiped (--rebuild) since
      // the URL was minted. Stop polling + offer a way back.
      if (/project.*not.*found|404/i.test(msg)) {
        projectError = `Project ${projectId} no longer exists (Hub data may have been wiped by --rebuild). Use the dashboard to create a fresh project.`;
        if (pollHandle !== null) {
          window.clearInterval(pollHandle);
          pollHandle = null;
        }
      } else {
        projectError = msg;
      }
    } finally {
      projectLoading = false;
    }
  }

  async function sendIntake() {
    if (!project || !userInput.trim() || chatBusy || intakeDone) return;
    const msg = userInput.trim();
    chatBusy = true;
    chatError = null;
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
        transcript: transcript.slice(0, -1),
        project_name: project.name,
        project_type: project.project_type,
        greenfield: Boolean(project.metadata?.greenfield)
      });
      transcript = res.transcript;
      intakeDone = res.done;
      await tick();
      chatScroller?.scrollTo({ top: chatScroller.scrollHeight, behavior: 'smooth' });
    } catch (e) {
      transcript = transcript.slice(0, -1);
      userInput = msg;
      chatError = (e as Error).message || 'intake chat failed';
    } finally {
      chatBusy = false;
    }
  }

  async function kickoff() {
    if (!project || transcript.length > 0) return;
    const greenfield = Boolean(project.metadata?.greenfield);
    const desc = project.metadata?.description;
    const descBlock = desc ? `\n\nMy brief: ${desc}` : '';
    userInput = greenfield
      ? `Start the intake for "${project.name}" — a brand-new greenfield ${project.project_type} I want to build from scratch.${descBlock}`
      : `Start the intake for "${project.name}" — a ${project.project_type} against existing code.${descBlock}`;
    await sendIntake();
  }

  onMount(async () => {
    await loadProject();
    if (project?.current_phase === 'intake') kickoff();
    // Poll for phase / artifact updates so the user sees the system
    // working without manual refresh. Lightweight read (single row).
    pollHandle = window.setInterval(loadProject, 4000) as unknown as number;
  });

  onDestroy(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
  });

  // Pre-computed artifact list per current state. Order matches the
  // dispatch chain so artifacts appear top-down in the order roles ran.
  $: artifacts = (() => {
    if (!project) return [] as { label: string; key: string; md: string }[];
    const md = project.metadata || {};
    const out: { label: string; key: string; md: string }[] = [];
    if (md.prd_md) out.push({ label: 'PRD (product role)', key: 'prd_md', md: md.prd_md });
    if (md.roadmap_md) out.push({ label: 'Roadmap (planner role)', key: 'roadmap_md', md: md.roadmap_md });
    if (md.trd_md) out.push({ label: 'TRD (architect role)', key: 'trd_md', md: md.trd_md });
    if (md.sprint_plan_md) out.push({ label: 'Sprint plan (conductor role)', key: 'sprint_plan_md', md: md.sprint_plan_md });
    if (md.code_intro_md) out.push({ label: 'Engineer intro', key: 'code_intro_md', md: md.code_intro_md });
    if (md.qa_md) out.push({ label: 'Test plan (qa role)', key: 'qa_md', md: md.qa_md });
    if (md.release_gate_md) out.push({ label: 'Ship gate (release_manager)', key: 'release_gate_md', md: md.release_gate_md });
    return out;
  })();

  // Generated code files (if engineer produced any).
  interface FileEntry { path: string; bytes: number }
  let codeFiles: FileEntry[] = [];
  let codeFilesLoading = false;
  let openFile: string | null = null;
  let openFileContent = '';
  let openFileLoading = false;

  async function refreshCodeFiles() {
    if (!project) return;
    if (!(project.metadata?.code_files?.length > 0 || project.metadata?.code_workspace)) {
      codeFiles = [];
      return;
    }
    codeFilesLoading = true;
    try {
      const res = await api.get<{ items: FileEntry[]; missing: boolean }>(
        `/api/v2/projects/${projectId}/workspace/files`
      );
      codeFiles = res.items || [];
    } catch {
      codeFiles = [];
    } finally {
      codeFilesLoading = false;
    }
  }

  async function loadFile(path: string) {
    openFile = path;
    openFileLoading = true;
    openFileContent = '';
    try {
      const res = await api.get<{ content: string }>(
        `/api/v2/projects/${projectId}/workspace/file?path=${encodeURIComponent(path)}`
      );
      openFileContent = res.content;
    } catch (e) {
      openFileContent = `// failed to load: ${(e as Error).message}`;
    } finally {
      openFileLoading = false;
    }
  }

  $: if (project?.metadata?.code_files) refreshCodeFiles();
</script>

<PanelHeader
  title={project?.name ?? 'Project workspace'}
  subtitle={project ? `${project.project_type} · phase: ${project.current_phase} · ${project.status}` : 'Loading…'}
>
  <a href="{base}/" class="btn-ghost text-sm">← Dashboard</a>
  <a href="{base}/panels/decision-queue" class="btn-ghost text-sm">Decisions →</a>
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
          class:text-white={state === 'active' || state === 'done'}
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
    <section class="panel-card flex flex-col gap-3 mb-6" style="min-height: 28rem;">
      <header class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">
          Intake with the product role
        </h2>
        {#if intakeDone}
          <span class="rounded-full bg-severity-info px-3 py-1 text-xs text-white">
            ✓ Intake complete — drafting PRD…
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
          <p class="text-sm text-surface-700/70 dark:text-surface-200/70">Starting intake…</p>
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
          <button type="submit" class="btn-primary" disabled={chatBusy || !userInput.trim()} data-testid="intake-send">
            {chatBusy ? '…' : 'Send'}
          </button>
        </form>
      {:else}
        <div class="rounded-md border border-severity-info/30 bg-severity-info/10 p-3 text-sm">
          PRD draft running in the background. You'll see an approval card
          in <a href="{base}/panels/decision-queue" class="text-accent underline">decisions</a>
          in a few seconds. Approve to advance to the architect.
        </div>
      {/if}
    </section>
  {/if}

  <!-- Artifacts panel (PRD/TRD/IMPL/QA shown as they appear) -->
  {#if artifacts.length > 0}
    <section class="mb-6">
      <h2 class="mb-3 text-sm font-semibold text-surface-900 dark:text-surface-50">
        Artifacts produced
      </h2>
      <div class="space-y-3">
        {#each artifacts as art (art.key)}
          <details class="panel-card" open={art.key === artifacts[artifacts.length - 1].key}>
            <summary class="cursor-pointer text-sm font-semibold text-surface-900 dark:text-surface-50">
              {art.label}
              <span class="ml-2 text-xs font-normal text-surface-700/70 dark:text-surface-200/70">
                ({art.md.length.toLocaleString()} chars)
              </span>
            </summary>
            <pre class="mt-3 whitespace-pre-wrap rounded-md bg-surface-50 p-3 text-xs leading-relaxed text-surface-900 dark:bg-surface-900 dark:text-surface-50">{art.md}</pre>
          </details>
        {/each}
      </div>
    </section>
  {/if}

  <!-- Generated code files (engineer role) -->
  {#if codeFiles.length > 0}
    <section class="mb-6">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">
          Generated code · {codeFiles.length} file{codeFiles.length === 1 ? '' : 's'}
        </h2>
        <a
          href="/api/v2/projects/{projectId}/workspace/zip"
          class="btn-ghost text-xs"
          download
        >
          Download .zip
        </a>
      </header>
      <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
        <ul class="panel-card md:col-span-1 max-h-96 overflow-y-auto text-xs font-mono">
          {#each codeFiles as f (f.path)}
            <li>
              <button
                type="button"
                class="block w-full text-left rounded px-2 py-1 hover:bg-surface-100 dark:hover:bg-surface-700 {openFile === f.path ? 'bg-accent text-white' : ''}"
                on:click={() => loadFile(f.path)}
              >
                {f.path} <span class="opacity-60">({f.bytes.toLocaleString()}b)</span>
              </button>
            </li>
          {/each}
        </ul>
        <div class="panel-card md:col-span-2 max-h-96 overflow-y-auto">
          {#if openFile}
            <header class="mb-2 text-xs font-mono text-surface-700 dark:text-surface-200">
              {openFile}
            </header>
            {#if openFileLoading}
              <LoadingSpinner label="Loading file" />
            {:else}
              <pre class="whitespace-pre-wrap text-xs leading-relaxed">{openFileContent}</pre>
            {/if}
          {:else}
            <p class="text-sm text-surface-700/70 dark:text-surface-200/70">
              Click any file to view its contents.
            </p>
          {/if}
        </div>
      </div>
      {#if project.metadata?.code_run_block}
        <details class="panel-card mt-4">
          <summary class="cursor-pointer text-sm font-semibold text-surface-900 dark:text-surface-50">
            Run locally
          </summary>
          <pre class="mt-3 whitespace-pre-wrap rounded-md bg-surface-900 p-3 text-xs text-green-400">{project.metadata.code_run_block}</pre>
        </details>
      {/if}
    </section>
  {/if}

  <!-- Status hint when between phases (artifact generated but no card yet visible) -->
  {#if project.current_phase !== 'intake' && project.current_phase !== 'release'}
    <section class="panel-card text-sm">
      <p class="text-surface-700 dark:text-surface-200">
        Phase: <strong>{project.current_phase}</strong>. Look in
        <a href="{base}/panels/decision-queue" class="text-accent underline">decisions</a>
        for the next approval card. The page auto-refreshes every 4s.
      </p>
    </section>
  {/if}

  {#if project.current_phase === 'release'}
    <section class="panel-card text-sm">
      <p class="text-surface-700 dark:text-surface-200">
        🎉 <strong>{project.name}</strong> reached the <strong>release</strong> phase.
        All four roles signed off; artifacts above are the trail.
      </p>
    </section>
  {/if}
{/if}
