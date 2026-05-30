<!--
  Spine Hub SPA — Project workspace.

  Phase-aware: shows intake chat during intake; shows artifacts (PRD,
  TRD, impl plan, QA plan) as they accumulate in project metadata.
  Polls recovery via SSE recovery_pulse when live; falls back to GET /recovery
  only when the stream is offline. Full project metadata reloads are deferred
  during in-flight dispatches unless the user is on Artifacts or Code tabs.
-->
<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { afterNavigate, goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import ProjectSubnav from '$lib/components/ProjectSubnav.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import ProjectEditDialog from '$lib/components/ProjectEditDialog.svelte';
  import ProjectWorkspaceChrome from '$lib/components/ProjectWorkspaceChrome.svelte';
  import ProjectWorkspaceRuntime from '$lib/components/ProjectWorkspaceRuntime.svelte';
  import ProjectWorkspaceTabs from '$lib/components/ProjectWorkspaceTabs.svelte';
  import type { WorkspaceTab } from '$lib/projectWorkspaceTypes';
  import ProjectPipelinePanel from '$lib/components/ProjectPipelinePanel.svelte';
  // Path A / B realtime surfaces are temporarily removed from the
  // workspace shell (2026-05-30) after the project page started
  // hanging on load. Components remain in src/lib/components/ for a
  // careful lazy-load re-add in a follow-up.
  import ProjectDecisionsPanel from '$lib/components/ProjectDecisionsPanel.svelte';
  import { api } from '$lib/api/client';
  import { get } from 'svelte/store';
  import { decisions } from '$lib/stores/decisions';
  import { projectDecisionKeys, projectScopedDecisions } from '$lib/stores/projectDecisionsStore';
  import { toasts } from '$lib/stores/toasts';
  import { formatProjectSubtitle } from '$lib/projectPipelineCopy';
  import {
    archiveProject,
    deleteProject,
    isArchived,
    projectBrief,
    restoreProject,
    updateProject,
  } from '$lib/projectLifecycle';
  import { yieldMainThread } from '$lib/yieldMainThread';
  import { dispatchInFlightActive } from '$lib/projectRecoveryUtils';
  import {
    wsRecovery,
    wsRunState,
    wsBind,
    wsUnbind,
    wsResetTransient,
    wsSetMetadataPatchHandler,
    wsSetArtifactsRefreshHandler,
    scheduleLoadRecovery,
    wsLoadTerminal,
    wsLoadRecoveryNow,
    wsWaitForRecoverySnapshot,
    wsDispatchRecovery,
  } from '$lib/stores/projectWorkspace';

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
  let projectLoading = false;
  /** Pipeline/runtime mounts only after bind + recovery snapshot (prevents main-thread freeze). */
  let workspaceReady = false;
  let projectError: string | null = null;
  let workspaceLoadPromise: Promise<void> | null = null;
  /** Suppress duplicate initial load when SvelteKit afterNavigate follows onMount. */
  let skipNextInitialNavigate = false;


  function phaseIndex(phase: string | undefined): number {
    if (!phase) return -1;
    const p = phase.toLowerCase();
    if (p === 'intake') return 0;
    if (p.startsWith('plan')) return 1;
    if (p.startsWith('build')) return 2;
    if (p.startsWith('verify') || p === 'acceptance') return 3;
    if (p === 'released' || p === 'release' || p === 'operate' || p === 'retro') return 4;
    return -1;
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

  let pollHandle: number | null = null; // legacy — cleared on 404 if ever set
  let projectArtifactsLoaded = false;
  let lastLoadedProjectId: string | null = null;

  type WorkspaceTabId = WorkspaceTab;
  let workspaceTab: WorkspaceTabId = 'pipeline';
  let workspaceTabPinned = false;
  /** One-shot auto tab pick on project open — avoids yanking tabs on every poll refresh. */
  let initialWorkspaceTabSet = false;
  let workspaceLoadInFlight = false;
  let workspaceRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  type ConfirmKind = 'archive' | 'delete' | 'restore';
  let confirmOpen = false;
  let confirmKind: ConfirmKind = 'archive';
  let confirmBusy = false;

  let editOpen = false;
  let editName = '';
  let editDescription = '';
  let editBusy = false;
  let editError: string | null = null;

  function openEditDialog() {
    if (!project) return;
    editName = project.name;
    editDescription = projectBrief(project);
    editError = null;
    editOpen = true;
  }

  function openConfirm(kind: ConfirmKind) {
    confirmKind = kind;
    confirmOpen = true;
  }

  async function handleConfirm() {
    if (!project || !projectId) return;
    confirmBusy = true;
    try {
      if (confirmKind === 'archive') {
        await archiveProject(projectId);
        toasts.push({ kind: 'success', message: `Archived "${project.name}"`, ttlMs: 4000 });
        await loadProject();
      } else if (confirmKind === 'restore') {
        await restoreProject(projectId);
        toasts.push({ kind: 'success', message: `Restored "${project.name}"`, ttlMs: 4000 });
        await loadProject();
      } else {
        await deleteProject(projectId);
        toasts.push({ kind: 'success', message: `Deleted "${project.name}"`, ttlMs: 4000 });
        confirmOpen = false;
        await goto(`${base}/projects`);
        return;
      }
      confirmOpen = false;
    } catch (e) {
      toasts.push({ kind: 'error', message: (e as Error).message || 'Project action failed' });
    } finally {
      confirmBusy = false;
    }
  }

  async function handleEditSave(e: CustomEvent<{ name: string; description: string }>) {
    if (!projectId) return;
    editBusy = true;
    editError = null;
    try {
      await updateProject(projectId, {
        name: e.detail.name,
        description: e.detail.description || undefined,
      });
      toasts.push({ kind: 'success', message: 'Project updated', ttlMs: 3500 });
      editOpen = false;
      await loadProject();
    } catch (err) {
      editError = (err as Error).message || 'Save failed';
    } finally {
      editBusy = false;
    }
  }

  $: confirmCopy = (() => {
    const name = project?.name ?? 'this project';
    if (confirmKind === 'archive') {
      return {
        title: 'Archive project?',
        message: `"${name}" will move to archived projects. You can restore it later.`,
        confirmLabel: 'Archive',
        variant: 'warning' as const,
      };
    }
    if (confirmKind === 'restore') {
      return {
        title: 'Restore project?',
        message: `"${name}" will return to your active project list.`,
        confirmLabel: 'Restore',
        variant: 'default' as const,
      };
    }
    return {
      title: 'Delete project?',
      message: `"${name}" will be permanently removed from the Hub UI. This cannot be undone from the SPA.`,
      confirmLabel: 'Delete',
      variant: 'danger' as const,
    };
  })();

  async function waitForDecisionsLoaded(): Promise<void> {
    if (!get(decisions).loading) return;
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        unsub();
        clearTimeout(timer);
        resolve();
      };
      const unsub = decisions.subscribe((s) => {
        if (!s.loading) finish();
      });
      const timer = window.setTimeout(finish, 8000);
    });
  }

  function pipelineStuckSnapshot(): boolean {
    const recovery = get(wsRecovery);
    const activeRole = get(wsRunState);
    const cards = get(projectScopedDecisions);
    const blocked = Boolean(
      project?.metadata?.code_review_blocked ?? recovery?.code_review_blocked
    );
    return Boolean(
      recovery?.stuck ||
        (blocked &&
          !activeRole.activeRole &&
          cards.length === 0 &&
          !dispatchInFlightActive(recovery))
    );
  }

  function syncInitialWorkspaceTab() {
    if (!project || initialWorkspaceTabSet || workspaceTabPinned) return;
    const pending = get(projectScopedDecisions);
    if (project.current_phase === 'intake') workspaceTab = 'intake';
    else if (pending.length > 0) workspaceTab = 'decisions';
    else if (pipelineStuckSnapshot()) workspaceTab = 'pipeline';
    initialWorkspaceTabSet = true;
    validateWorkspaceTab();
    if (workspaceTab === 'pipeline' && projectId) {
      void wsLoadTerminal(projectId);
    }
  }

  function allowedWorkspaceTabs(): WorkspaceTabId[] {
    const tabs: WorkspaceTabId[] = [];
    if (project?.current_phase === 'intake') tabs.push('intake');
    tabs.push('decisions', 'pipeline');
    if (showArtifactsTab()) tabs.push('artifacts');
    const fileCount = codeFiles.length > 0 ? codeFiles.length : codeFilesCount(project);
    if (fileCount > 0) tabs.push('code');
    return tabs;
  }

  function validateWorkspaceTab() {
    if (!project) return;
    const tabs = allowedWorkspaceTabs();
    if (!tabs.includes(workspaceTab)) {
      workspaceTab =
        tabs.find((t) => t === 'decisions') ??
        tabs.find((t) => t === 'pipeline') ??
        tabs[0] ??
        'pipeline';
    }
  }

  function showArtifactsTab(): boolean {
    if (!project) return false;
    if (projectArtifactsLoaded && (artifacts?.length ?? 0) > 0) return true;
    return phaseIndex(project.current_phase) >= 1;
  }

  function codeFilesCount(p: ProjectFull | null): number {
    if (!p?.metadata) return 0;
    const md = p.metadata;
    if (typeof md.code_files_count === 'number') return md.code_files_count;
    return Array.isArray(md.code_files) ? md.code_files.length : 0;
  }

  function selectWorkspaceTab(tab: WorkspaceTabId) {
    if (workspaceTab === 'code' && tab !== 'code') stopDeployPoll();
    workspaceTabPinned = true;
    workspaceTab = tab;
    if (tab === 'artifacts' && project && !projectArtifactsLoaded) {
      void loadProjectFull(true);
    }
    if (tab === 'code' && project) {
      void ensureCodeTabLoaded();
      startDeployPollIfNeeded();
    }
    if (tab === 'pipeline' && projectId) {
      void wsLoadTerminal(projectId);
    }
  }

  function syncProjectDecisionKeys() {
    projectDecisionKeys.set(projectMatchKeys());
  }

  function patchProjectMetadata(_patch: Record<string, unknown>, phase?: string) {
    if (!project) return;
    if (phase && phase !== project.current_phase) {
      project = { ...project, current_phase: phase };
    }
  }

  function projectMatchKeys(): string[] {
    const keys: string[] = [];
    if (projectId) keys.push(String(projectId));
    if (project?.id != null) keys.push(String(project.id));
    if (project?.project_id) keys.push(String(project.project_id));
    return keys;
  }

  async function refreshProjectLite() {
    if (!projectId) return;
    scheduleLoadRecovery(projectId, true, true);
    try {
      const summary = await api.get<ProjectFull>(`/api/v2/projects/${projectId}/summary`);
      project = project
        ? {
            ...project,
            ...summary,
            metadata: { ...(project.metadata ?? {}), ...(summary.metadata ?? {}) },
          }
        : summary;
      await yieldMainThread();
    } catch {
      /* summary refresh is best-effort */
    }
  }

  function dispatchFromChrome(action: string) {
    if (!projectId) return;
    wsDispatchRecovery(projectId, action, undefined, () => selectWorkspaceTab('pipeline'));
  }

  let fastPollHandle: number | null = null;

  function stopFastPoll() {
    if (fastPollHandle !== null) {
      window.clearInterval(fastPollHandle);
      fastPollHandle = null;
    }
  }

  function stopDeployPoll() {
    if (deployPollHandle !== null) {
      window.clearInterval(deployPollHandle);
      deployPollHandle = null;
    }
  }

  /** Clear live UI state when switching projects so tabs/logs do not bleed across workspaces. */
  function resetTransientWorkspaceState() {
    wsResetTransient();
    codeFiles = [];
    openFile = null;
    openFileContent = '';
    deployment = { running: false };
    stopDeployPoll();
    stopFastPoll();
    projectArtifactsLoaded = false;
  }

  function isTurn(value: unknown): value is Turn {
    if (!value || typeof value !== 'object') return false;
    const t = value as Turn;
    return (t.role === 'user' || t.role === 'assistant') && typeof t.content === 'string' && t.content.length > 0;
  }

  /** Restore intake chat from project.metadata after refresh or first open. */
  function restoreIntakeFromMetadata(p: ProjectFull) {
    if (transcript.length > 0) return;
    const saved = p.metadata?.intake_transcript;
    if (Array.isArray(saved)) {
      const turns = saved.filter(isTurn);
      if (turns.length) transcript = turns;
    }
    if (p.metadata?.intake_done === true) intakeDone = true;
  }

  let projectFullLoadPromise: Promise<void> | null = null;
  async function loadProjectFull(includeArtifacts: boolean): Promise<void> {
    if (!projectId) return;
    const run = async () => {
      try {
        const res = await api.getOffThread<ProjectFull>(
          `/api/v2/projects/${projectId}/full?include_artifacts=${includeArtifacts ? 'true' : 'false'}`
        );
        if (project && !includeArtifacts) {
          project = {
            ...project,
            ...res,
            metadata: { ...(project.metadata ?? {}), ...(res.metadata ?? {}) },
          };
        } else {
          project = res;
        }
        if (includeArtifacts) projectArtifactsLoaded = true;
        await yieldMainThread();
      } catch {
        /* Summary already painted; full fetch can retry on tab open. */
      }
    };
    if (projectFullLoadPromise) {
      await projectFullLoadPromise;
    }
    projectFullLoadPromise = run().finally(() => {
      projectFullLoadPromise = null;
    });
    await projectFullLoadPromise;
  }

  async function loadProject(
    includeArtifacts = false,
    opts: { reveal?: boolean } = {}
  ): Promise<boolean> {
    if (!projectId) return false;
    const reveal = opts.reveal !== false;
    try {
      const summary = await api.get<ProjectFull>(`/api/v2/projects/${projectId}/summary`);
      projectError = null;
      if (reveal) projectLoading = false;
      project = summary;
      await yieldMainThread();
      if (includeArtifacts) {
        await loadProjectFull(true);
      }
      return true;
    } catch (e) {
      const msg = (e as Error).message || 'failed to load project';
      if (/project.*not.*found|404/i.test(msg)) {
        projectError = `Project ${projectId} no longer exists (Hub data may have been wiped by --rebuild). Use the dashboard to create a fresh project.`;
        project = null;
        if (pollHandle !== null) {
          window.clearInterval(pollHandle);
          pollHandle = null;
        }
      } else {
        projectError = msg;
      }
      return false;
    }
  }

  /** Load project + recovery; full-page spinner only on first open of a project id. */
  async function loadWorkspace(
    id: string,
    opts: { initial?: boolean; refreshProject?: boolean; includeArtifacts?: boolean } = {}
  ) {
    if (!id) {
      projectLoading = false;
      projectError = 'Missing project id in route';
      return;
    }
    if (opts.initial && id === lastLoadedProjectId && workspaceReady && !opts.refreshProject) {
      return;
    }
    if (workspaceLoadPromise) {
      if (opts.initial) return workspaceLoadPromise;
      if (!opts.initial) return;
    }
    workspaceLoadPromise = loadWorkspaceInner(id, opts).finally(() => {
      workspaceLoadPromise = null;
    });
    return workspaceLoadPromise;
  }

  async function loadWorkspaceInner(
    id: string,
    opts: { initial?: boolean; refreshProject?: boolean; includeArtifacts?: boolean }
  ) {
    if (workspaceLoadInFlight && !opts.initial) return;
    workspaceLoadInFlight = true;
    const isNewProject = id !== lastLoadedProjectId;
    const shouldRefreshProject =
      opts.refreshProject ?? Boolean(opts.initial || isNewProject);
    const includeArtifacts = opts.includeArtifacts ?? false;
    if (opts.initial || isNewProject) {
      projectLoading = true;
      if (isNewProject) {
        workspaceReady = false;
        lastLoadedProjectId = id;
        project = null;
        wsUnbind();
        wsRecovery.set(null);
        workspaceTabPinned = false;
        initialWorkspaceTabSet = false;
        workspaceTab = 'pipeline';
        transcript = [];
        intakeDone = false;
        lastCodeFilesSig = '';
        projectArtifactsLoaded = false;
        resetTransientWorkspaceState();
      }
    }
    wsSetMetadataPatchHandler(patchProjectMetadata);
    wsSetArtifactsRefreshHandler(() => {
      if (workspaceTab === 'artifacts') scheduleProjectRefresh(true);
    });
    try {
      if (shouldRefreshProject) {
        const ok = await loadProject(includeArtifacts, { reveal: false });
        if (!ok) return;
        if (project) {
          syncProjectDecisionKeys();
          restoreIntakeFromMetadata(project);
        }
        await waitForDecisionsLoaded();
        await yieldMainThread();
      }
      if (opts.initial || isNewProject) {
        await Promise.race([
          (async () => {
            await wsLoadRecoveryNow(id);
            await wsWaitForRecoverySnapshot(id, 4000);
          })(),
          new Promise<void>((resolve) => setTimeout(resolve, 12_000)),
        ]);
        await yieldMainThread();
      }
      if (!(opts.initial || isNewProject)) {
        scheduleLoadRecovery(id, true);
      }
      if (shouldRefreshProject && project) {
        syncInitialWorkspaceTab();
      }
      await tick();
      await yieldMainThread();
      workspaceReady = true;
      projectLoading = false;
      if (
        project?.current_phase === 'intake' &&
        transcript.length === 0 &&
        !intakeDone
      ) {
        void kickoff();
      }
    } finally {
      workspaceLoadInFlight = false;
      projectLoading = false;
    }
  }

  function scheduleProjectRefresh(wantArtifacts = false) {
    if (!projectId) return;
    const live = get(decisions).liveConnected;
    if (live && dispatchInFlightActive(get(wsRecovery)) && workspaceTab !== 'artifacts') {
      return;
    }
    if (wantArtifacts && workspaceTab === 'artifacts') {
      if (workspaceRefreshTimer !== null) clearTimeout(workspaceRefreshTimer);
      workspaceRefreshTimer = setTimeout(() => {
        workspaceRefreshTimer = null;
        void loadProjectFull(true);
      }, 500);
    }
    if (!live) scheduleLoadRecovery(projectId);
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

  function startDeployPollIfNeeded() {
    if (deployPollHandle !== null) return;
    if (codeFilesCount(project) <= 0 && codeFiles.length <= 0) return;
    void loadDeployment();
    deployPollHandle = window.setInterval(loadDeployment, 8000) as unknown as number;
  }

  onMount(async () => {
    await tick();
    skipNextInitialNavigate = true;
    await loadWorkspace($page.params.project_id, { initial: true });
  });

  afterNavigate(async ({ to, from }) => {
    const nextId = to?.params?.project_id;
    if (!nextId) return;
    if (skipNextInitialNavigate) {
      skipNextInitialNavigate = false;
      return;
    }
    const prevId = from?.params?.project_id;
    if (nextId !== prevId) {
      await loadWorkspace(nextId, { initial: true });
    }
  });

  onDestroy(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
    stopDeployPoll();
    stopFastPoll();
    if (workspaceRefreshTimer !== null) clearTimeout(workspaceRefreshTimer);
    wsUnbind();
    wsSetMetadataPatchHandler(null);
    wsSetArtifactsRefreshHandler(null);
    projectDecisionKeys.set([]);
  });

  // Artifact markdown is heavy (~100KB+). Only materialize when the Artifacts tab is open.
  let artifacts: { label: string; key: string; md: string }[] = [];
  let selectedArtifactKey: string | null = null;
  $: artifacts =
    workspaceTab === 'artifacts' && project
      ? (() => {
          const md = project.metadata || {};
          const out: { label: string; key: string; md: string }[] = [];
          if (md.prd_md) out.push({ label: 'PRD (product role)', key: 'prd_md', md: md.prd_md });
          if (md.roadmap_md)
            out.push({ label: 'Roadmap (planner role)', key: 'roadmap_md', md: md.roadmap_md });
          if (md.trd_md) out.push({ label: 'TRD (architect role)', key: 'trd_md', md: md.trd_md });
          if (md.sprint_plan_md)
            out.push({
              label: 'Sprint plan (conductor role)',
              key: 'sprint_plan_md',
              md: md.sprint_plan_md,
            });
          if (md.code_intro_md)
            out.push({ label: 'Engineer intro', key: 'code_intro_md', md: md.code_intro_md });
          if (md.code_review_md)
            out.push({
              label: `Security review (security_engineer) ${md.code_review_blocked ? '⛔ BLOCKED' : '✅ PASS'}`,
              key: 'code_review_md',
              md: md.code_review_md,
            });
          if (md.qa_md) out.push({ label: 'Test plan (qa role)', key: 'qa_md', md: md.qa_md });
          if (md.release_gate_md)
            out.push({
              label: 'Ship gate (release_manager)',
              key: 'release_gate_md',
              md: md.release_gate_md,
            });
          return out;
        })()
      : [];

  $: if (artifacts.length > 0) {
    const keys = artifacts.map((a) => a.key);
    const preferred = artifacts[artifacts.length - 1]?.key ?? null;
    if (!selectedArtifactKey || !keys.includes(selectedArtifactKey)) {
      selectedArtifactKey = preferred;
    }
  } else {
    selectedArtifactKey = null;
  }

  $: selectedArtifact = artifacts.find((a) => a.key === selectedArtifactKey) ?? null;

  function artifactShortLabel(label: string): string {
    return label.split(' (')[0];
  }

  function artifactTone(key: string): string {
    if (key === 'code_review_md' && project?.metadata?.code_review_blocked) {
      return 'text-severity-critical';
    }
    return '';
  }

  interface FileEntry { path: string; bytes: number }
  let codeFiles: FileEntry[] = [];
  let codeFilesLoading = false;
  let lastCodeFilesSig = '';
  let openFile: string | null = null;
  let openFileContent = '';
  let openFileLoading = false;

  async function refreshCodeFiles() {
    if (!project) return;
    const hasCode =
      codeFilesCount(project) > 0 ||
      project.metadata?.code_workspace ||
      (Array.isArray(project.metadata?.code_files) && project.metadata.code_files.length > 0);
    if (!hasCode) {
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

  async function ensureCodeTabLoaded() {
    if (!project) return;
    const sig = codeFilesMetadataSig(project);
    if (sig && sig !== lastCodeFilesSig) {
      lastCodeFilesSig = sig;
      await refreshCodeFiles();
    } else if (!sig) {
      lastCodeFilesSig = '';
      codeFiles = [];
    }
    if (codeFiles.length > 0 && (!openFile || !codeFiles.some((f) => f.path === openFile))) {
      void loadFile(codeFiles[0].path);
    }
  }

  function codeFilesMetadataSig(p: ProjectFull | null): string {
    if (!p?.metadata) return '';
    const count = codeFilesCount(p);
    const workspace = p.metadata.code_workspace ? '1' : '0';
    return `${count}:${workspace}`;
  }

  // Deployment status — polls /deployment only while Code tab is open.
  interface Deployment {
    running: boolean;
    cli_mode?: boolean;
    deploy_ok?: boolean | null;
    port?: number;
    url?: string;
    pid?: number;
    cmd?: string;
    log_tail?: string;
    rc?: number | null;
    started?: number;
  }
  let deployment: Deployment = { running: false };
  let deployPollHandle: number | null = null;
  let deployActionBusy = false;

  async function loadDeployment() {
    try {
      deployment = await api.get<Deployment>(`/api/v2/projects/${projectId}/deployment`);
    } catch {
      deployment = { running: false };
    }
  }

  async function startDeployment() {
    deployActionBusy = true;
    try {
      await api.post(`/api/v2/projects/${projectId}/deployment/start`, {});
      toasts.push({
        kind: 'success',
        message: deployment.cli_mode ? 'Container run started' : 'Local deployment starting',
        ttlMs: 3500
      });
      setTimeout(loadDeployment, 4000);
    } catch (e) {
      toasts.push({
        kind: 'error',
        message: (e as Error).message || 'Failed to start deployment'
      });
    } finally {
      deployActionBusy = false;
    }
  }

  async function stopDeployment() {
    deployActionBusy = true;
    try {
      await api.post(`/api/v2/projects/${projectId}/deployment/stop`, {});
      await loadDeployment();
      toasts.push({ kind: 'success', message: 'Deployment stopped', ttlMs: 3000 });
    } catch (e) {
      toasts.push({
        kind: 'error',
        message: (e as Error).message || 'Failed to stop deployment'
      });
    } finally {
      deployActionBusy = false;
    }
  }

</script>

<header class="project-workspace-header mb-5 flex flex-col gap-2 border-b border-surface-700 pb-4 sm:flex-row sm:items-center sm:justify-between">
  <div class="min-w-0">
    <h1 class="text-2xl font-semibold text-surface-50 sm:text-3xl">
      {project?.name ?? 'Project workspace'}
    </h1>
    <p class="mt-1 text-base text-surface-300">
      {#if project}
        {formatProjectSubtitle(project.project_type, project.current_phase, project.status)}
      {:else}
        Loading…
      {/if}
    </p>
  </div>
  <div class="flex flex-wrap items-center gap-2">
    {#if project}
      <button type="button" class="btn-ghost text-sm" on:click={openEditDialog} data-testid="project-edit-btn">
        Edit
      </button>
      {#if isArchived(project)}
        <button type="button" class="btn-secondary text-sm" on:click={() => openConfirm('restore')}>
          Restore
        </button>
      {:else}
        <button type="button" class="btn-secondary text-sm" on:click={() => openConfirm('archive')}>
          Archive
        </button>
      {/if}
      <button type="button" class="btn-danger text-sm" on:click={() => openConfirm('delete')} data-testid="project-delete-btn">
        Delete
      </button>
    {/if}
    <a href="{base}/projects" class="btn-ghost text-base">← All projects</a>
  </div>
</header>

{#if project}
  <ProjectSubnav projectId={project.project_id} projectName={project.name} active="workspace" />
{/if}

{#if project && isArchived(project)}
  <div class="mb-4 rounded-lg border border-surface-600 bg-surface-800/50 px-4 py-3 text-sm text-surface-300">
    This project is archived. Restore it to resume the pipeline, or delete it to remove it from the Hub.
  </div>
{/if}

{#if projectError}
  <div class="mb-4"><ErrorBanner kind="error" message={projectError} onDismiss={() => (projectError = null)} /></div>
{/if}

{#if projectLoading && !project}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading project" /></div>
{:else if projectError && !project}
  <div class="mb-4"><ErrorBanner kind="error" message={projectError} onDismiss={() => (projectError = null)} /></div>
{:else if project && !workspaceReady}
  <div class="flex flex-col items-center justify-center gap-3 py-16" data-testid="workspace-boot">
    <LoadingSpinner label="Preparing pipeline" />
    <p class="text-sm text-surface-400">Loading recovery actions and activity stream…</p>
  </div>
{:else if project}
  <ProjectWorkspaceRuntime projectId={project.project_id} matchKeys={projectMatchKeys()} />
  <div class="project-workspace">
  <ProjectWorkspaceChrome
    projectPhase={project.current_phase}
    codeReviewBlocked={Boolean(project.metadata?.code_review_blocked)}
    onSelectDecisions={() => selectWorkspaceTab('decisions')}
    onSelectPipelineAndDispatch={dispatchFromChrome}
  />

  <section class="workspace-shell panel-card mb-6" data-testid="project-pipeline">
    <ProjectWorkspaceTabs
      {workspaceTab}
      onSelectTab={selectWorkspaceTab}
      projectPhase={project.current_phase}
      showArtifacts={showArtifactsTab()}
      artifactCount={artifacts.length}
      codeFileCount={codeFiles.length > 0 ? codeFiles.length : codeFilesCount(project)}
      codeReviewBlocked={Boolean(project.metadata?.code_review_blocked)}
    />

    <div class="workspace-tab-panel min-h-0 flex-1 pt-4" role="tabpanel">
      {#if workspaceTab === 'intake'}
        <div class="workspace-pane flex h-full flex-col gap-3" data-testid="intake-transcript-root">
          <div bind:this={chatScroller} class="workspace-scroll flex-1 overflow-y-auto rounded-lg border border-surface-700/60 bg-surface-950/40 p-3">
            {#if transcript.length === 0}<p class="text-sm text-surface-500">Starting intake…</p>{/if}
            {#each transcript as turn, i (i)}
              <div class="mb-3 flex gap-2" class:justify-end={turn.role === 'user'}>
                <div class="max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm {turn.role === 'user' ? 'bg-accent text-white' : 'border border-surface-700 bg-surface-900 text-surface-100'}">
                  <div class="mb-1 text-[0.65rem] uppercase tracking-wide opacity-70">{turn.role === 'user' ? 'You' : 'product'}</div>
                  {turn.content}
                </div>
              </div>
            {/each}
            {#if chatBusy}<LoadingSpinner label="Thinking" />{/if}
          </div>
          {#if chatError}<ErrorBanner kind="error" message={chatError} onDismiss={() => (chatError = null)} />{/if}
          {#if !intakeDone}
            <form on:submit|preventDefault={sendIntake} class="flex items-end gap-2">
              <textarea bind:value={userInput} rows="2" class="input-field flex-1 resize-none" placeholder="Answer the product role…" disabled={chatBusy} data-testid="intake-input"></textarea>
              <button type="submit" class="btn-primary" disabled={chatBusy || !userInput.trim()} data-testid="intake-send">{chatBusy ? '…' : 'Send'}</button>
            </form>
          {:else}
            <p class="text-xs text-sky-300">Intake complete — PRD drafting in progress. Check Artifacts tab shortly.</p>
          {/if}
        </div>

      {:else if workspaceTab === 'decisions'}
        <ProjectDecisionsPanel
          codeReviewBlocked={Boolean(project.metadata?.code_review_blocked)}
          onSelectPipelineTab={() => selectWorkspaceTab('pipeline')}
          onAfterAction={refreshProjectLite}
        />

      {:else if workspaceTab === 'pipeline'}
        <ProjectPipelinePanel
          projectId={project.project_id}
          onSelectPipelineTab={() => selectWorkspaceTab('pipeline')}
        />

      {:else if workspaceTab === 'artifacts'}
        <div class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0" data-testid="artifacts-panel">
          <ul class="workspace-list divide-y divide-surface-700/60 overflow-y-auto rounded-lg border border-surface-700/60 lg:col-span-4 lg:rounded-r-none lg:border-r-0" role="listbox">
            {#each artifacts as art (art.key)}
              <li>
                <button type="button" class="w-full border-l-2 px-3 py-2.5 text-left text-sm hover:bg-surface-800/60 {art.key === selectedArtifactKey ? 'border-accent bg-accent/10' : 'border-transparent'}" on:click={() => (selectedArtifactKey = art.key)}>
                  <span class="font-medium text-surface-100 {artifactTone(art.key)}">{artifactShortLabel(art.label)}</span>
                  <span class="text-[0.65rem] text-surface-500">{art.md.length.toLocaleString()} chars</span>
                </button>
              </li>
            {/each}
          </ul>
          <div class="workspace-detail flex flex-col overflow-hidden rounded-lg border border-surface-700/60 lg:col-span-8 lg:rounded-l-none">
            {#if selectedArtifact}
              <header class="shrink-0 border-b border-surface-700/60 px-4 py-2 text-sm font-semibold text-surface-50">{selectedArtifact.label}</header>
              <div class="workspace-scroll min-h-0 flex-1 overflow-y-auto p-4">
                <pre class="whitespace-pre-wrap text-xs leading-relaxed text-surface-200">{selectedArtifact.md}</pre>
              </div>
            {/if}
          </div>
        </div>

      {:else if workspaceTab === 'code'}
        <div class="workspace-pane flex h-full flex-col gap-4">
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-700/60 px-3 py-2">
            <span class="text-xs text-surface-400">{deployment.cli_mode ? 'Container CLI' : 'Local deployment'}</span>
            <div class="flex gap-2">
              {#if deployment.running && deployment.url}
                <a href={deployment.url} target="_blank" rel="noopener" class="btn-secondary text-xs">Open {deployment.url}</a>
                <button type="button" class="btn-ghost text-xs" on:click={stopDeployment} disabled={deployActionBusy}>Stop</button>
              {:else}
                <button type="button" class="btn-primary text-xs" on:click={startDeployment} disabled={deployActionBusy}>{deployActionBusy ? 'Running…' : deployment.cli_mode ? 'Run in container' : 'Deploy locally'}</button>
              {/if}
              <a href="/api/v2/projects/{projectId}/workspace/zip" class="btn-ghost text-xs" download>Download .zip</a>
            </div>
          </div>
          {#if project.metadata?.code_workspace_host}
            <p class="text-xs text-surface-500">Host path: <code class="font-mono text-surface-300">{project.metadata.code_workspace_host}</code></p>
          {/if}
          <div class="workspace-split grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-12 lg:gap-4">
            <ul class="workspace-list overflow-y-auto rounded-lg border border-surface-700/60 font-mono text-xs lg:col-span-4">
              {#each codeFiles as f (f.path)}
                <li>
                  <button type="button" class="block w-full px-2 py-1.5 text-left hover:bg-surface-800/60 {openFile === f.path ? 'bg-accent/20 text-accent' : 'text-surface-300'}" on:click={() => loadFile(f.path)}>{f.path}</button>
                </li>
              {/each}
            </ul>
            <div class="workspace-detail flex flex-col overflow-hidden rounded-lg border border-surface-700/60 lg:col-span-8">
              {#if openFile}
                <header class="shrink-0 border-b border-surface-700/60 px-3 py-2 font-mono text-xs text-surface-400">{openFile}</header>
                <div class="workspace-scroll min-h-0 flex-1 overflow-y-auto p-3">
                  {#if openFileLoading}<LoadingSpinner label="Loading file" />{:else}<pre class="whitespace-pre-wrap text-xs">{openFileContent}</pre>{/if}
                </div>
              {/if}
            </div>
          </div>
        </div>
      {/if}
    </div>
  </section>
  </div>

  <ConfirmDialog
    bind:open={confirmOpen}
    title={confirmCopy.title}
    message={confirmCopy.message}
    confirmLabel={confirmCopy.confirmLabel}
    variant={confirmCopy.variant}
    busy={confirmBusy}
    on:confirm={handleConfirm}
  />

  <ProjectEditDialog
    bind:open={editOpen}
    name={editName}
    description={editDescription}
    busy={editBusy}
    error={editError}
    on:save={handleEditSave}
    on:cancel={() => {
      if (!editBusy) editError = null;
    }}
  />

{/if}

<style>
  .project-workspace-header h1 {
    letter-spacing: -0.02em;
  }
  .pw-status-headline {
    font-size: 1.25rem;
    line-height: 1.4;
    font-weight: 600;
  }
  .pw-status-sub {
    font-size: 1rem;
    line-height: 1.5;
  }
  @media (min-width: 640px) {
    .pw-status-headline {
      font-size: 1.375rem;
    }
    .pw-status-sub {
      font-size: 1.0625rem;
    }
  }
  .project-workspace .workspace-tab-panel :is(p, li, button, textarea, pre) {
    font-size: 1rem;
    line-height: 1.55;
  }
  .project-workspace .workspace-tab-panel .text-xs {
    font-size: 0.9375rem;
  }
  .workspace-shell {
    display: flex;
    flex-direction: column;
    height: calc(100dvh - 12rem);
    min-height: 22rem;
    overflow: hidden;
  }
  .workspace-tab-panel {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }
  .workspace-pane {
    min-height: 0;
    height: 100%;
    overflow: hidden;
  }
  .workspace-split {
    min-height: 0;
    height: 100%;
    grid-template-rows: minmax(0, 1fr);
  }
  @media (min-width: 1024px) {
    .workspace-split > * {
      min-height: 0;
    }
  }
  .workspace-list,
  .workspace-detail,
  .workspace-scroll {
    min-height: 0;
  }
  .workspace-list,
  .workspace-scroll {
    max-height: 100%;
    overflow-y: auto;
  }
  .workspace-detail {
    display: flex;
    flex-direction: column;
    max-height: 100%;
    overflow: hidden;
  }
  @media (max-width: 1023px) {
    .workspace-shell {
      height: auto;
      min-height: 28rem;
    }
    .workspace-list {
      max-height: 10rem;
    }
    .workspace-scroll {
      max-height: 14rem;
    }
  }
</style>
