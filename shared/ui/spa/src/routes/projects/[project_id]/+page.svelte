<!--
  Spine Hub SPA — Project workspace.

  Phase-aware: shows intake chat during intake; shows artifacts (PRD,
  TRD, impl plan, QA plan) as they accumulate in project metadata.
  Polls every 4s to pick up live phase + artifact updates from the
  background role dispatcher.
-->
<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { afterNavigate } from '$app/navigation';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import RoleTerminal, { type TerminalLine } from '$lib/components/RoleTerminal.svelte';
  import { api, subscribeSse, isAbortError } from '$lib/api/client';
  import { decisions } from '$lib/stores/decisions';
  import { toasts } from '$lib/stores/toasts';
  import {
    stuckForProject,
    type StuckSummary
  } from '$lib/projectAttention';
  import {
    PIPELINE_COPY,
    humanStuckReason,
    dispatchKindLabel,
    formatProjectSubtitle,
    recoveryActionInfo,
  } from '$lib/projectPipelineCopy';
  import type { DecisionCard } from '$lib/api/types';

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

  let pollHandle: number | null = null;

  interface RecoveryActionSpec {
    action: string;
    label: string;
    description: string;
  }
  interface RecoveryStatus {
    stuck: boolean;
    reasons: string[];
    pending_decisions: number;
    recommended_action?: string | null;
    last_role_failure?: { role?: string; error?: string; retry_action?: string } | null;
    dispatch_in_flight?: { dispatch_kind?: string; action?: string; started_at?: string } | null;
    actions: RecoveryActionSpec[];
    code_fix_iteration?: number;
    max_code_fix_iterations?: number;
    fix_loop_exhausted?: boolean;
  }
  let recovery: RecoveryStatus | null = null;
  let recoveryLoading = false;
  let recoveryBusy = false;
  let recoveryError: string | null = null;
  let recoveryStarted: string | null = null;
  let recoveryNote = '';
  let selectedRecoveryAction: string | null = null;
  let selectedArtifactKey: string | null = null;
  let stuckByProject: Record<string, StuckSummary> = {};
  let lastLoadedProjectId: string | null = null;

  type WorkspaceTab = 'intake' | 'decisions' | 'pipeline' | 'artifacts' | 'code';
  let workspaceTab: WorkspaceTab = 'pipeline';
  let workspaceTabPinned = false;
  let selectedProjectDecisionId: string | null = null;
  let decisionBusyId: string | null = null;

  function decisionMatchesProject(card: DecisionCard, proj: ProjectFull): boolean {
    const pid = card.project_id;
    if (!pid) return false;
    return (
      pid === proj.project_id ||
      pid === String(proj.id) ||
      card.metadata?.project_uuid === proj.project_id
    );
  }

  $: projectDecisions = project
    ? $decisions.items.filter((c) => decisionMatchesProject(c, project!))
    : [];

  $: {
    if (projectDecisions.length === 0) {
      selectedProjectDecisionId = null;
    } else if (
      !selectedProjectDecisionId ||
      !projectDecisions.some((c) => c.decision_id === selectedProjectDecisionId)
    ) {
      selectedProjectDecisionId = projectDecisions[0].decision_id;
    }
  }
  $: selectedProjectDecision =
    projectDecisions.find((c) => c.decision_id === selectedProjectDecisionId) ?? null;

  function selectWorkspaceTab(tab: WorkspaceTab) {
    workspaceTabPinned = true;
    workspaceTab = tab;
  }

  async function ackProjectDecision(card: DecisionCard) {
    decisionBusyId = card.decision_id;
    try {
      await decisions.ack(card.decision_id);
      toasts.push({ kind: 'success', message: `Approved: ${card.title}`, ttlMs: 3500 });
      await loadWorkspace(projectId);
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'ack failed' });
    } finally {
      decisionBusyId = null;
    }
  }

  async function rejectProjectDecision(card: DecisionCard) {
    decisionBusyId = card.decision_id;
    try {
      await decisions.reject(card.decision_id);
      toasts.push({ kind: 'success', message: `Rejected: ${card.title}`, ttlMs: 3500 });
      await loadWorkspace(projectId);
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'reject failed' });
    } finally {
      decisionBusyId = null;
    }
  }

  function projectDecisionHint(card: DecisionCard): string {
    if (card.decision_class === 'briefing') return PIPELINE_COPY.decisions.hintBriefing;
    if (card.decision_class === 'approval') return PIPELINE_COPY.decisions.hintApproval;
    return PIPELINE_COPY.decisions.hintDefault;
  }

  async function loadStuckSummary() {
    try {
      const res = await api.get<{ by_project_id?: Record<string, StuckSummary> }>(
        '/api/v2/projects/recovery/summary?limit=200'
      );
      stuckByProject = res.by_project_id ?? {};
    } catch {
      stuckByProject = {};
    }
  }

  async function loadRecovery() {
    if (!projectId) return;
    recoveryLoading = true;
    try {
      const res = await api.get<RecoveryStatus & { ok?: boolean }>(
        `/api/v2/projects/${projectId}/recovery`
      );
      recovery = {
        stuck: Boolean(res.stuck),
        reasons: res.reasons ?? [],
        pending_decisions: res.pending_decisions ?? 0,
        recommended_action: res.recommended_action,
        last_role_failure: res.last_role_failure ?? null,
        dispatch_in_flight: res.dispatch_in_flight ?? null,
        actions: res.actions ?? [],
        code_fix_iteration: res.code_fix_iteration,
        max_code_fix_iterations: res.max_code_fix_iterations,
        fix_loop_exhausted: res.fix_loop_exhausted,
      };
      // Only clear dispatch errors on successful refresh — not poll timeouts.
      if (!recoveryBusy) recoveryError = null;
    } catch (e) {
      const msg = (e as Error).message || 'failed to load recovery status';
      // Background poll must not mask a successful dispatch start.
      if (!recoveryBusy && !recoveryStarted) recoveryError = msg;
    } finally {
      recoveryLoading = false;
    }
  }

  async function dispatchRecovery(action: string) {
    if (recoveryBusy || !projectId) return;
    recoveryBusy = true;
    recoveryError = null;
    recoveryStarted = null;
    const actionInfo = recoveryActionInfo(action);
    try {
      const res = await api.post<{ message?: string; action?: string; dispatch_kind?: string }>(
        `/api/v2/projects/${projectId}/recovery/dispatch`,
        {
          action,
          note: recoveryNote.trim() || undefined,
        },
      );
      lastDispatchedAction = action;
      lastDispatchAt = Date.now();
      recoveryStarted =
        res.message ??
        PIPELINE_COPY.dispatch.queued(actionInfo?.label ?? 'Pipeline step');
      recoveryNote = '';
      selectWorkspaceTab('pipeline');
      const role = actionInfo?.role ?? 'engineer';
      activeRole = role;
      activeRoleStartedAt = Date.now();
      activeRoleMessage = actionInfo?.steps?.[0] ?? null;
      pushFeed({
        type: 'dispatch_started',
        role,
        message: actionInfo?.label ?? action,
        ts: Date.now() / 1000
      });
      appendTerminalLine({
        formatted: PIPELINE_COPY.dispatch.terminalQueued(actionInfo?.label ?? action),
        level: 'info',
        ts: Date.now() / 1000
      });
      await loadRecovery();
      void loadTerminalLog();
      void loadProject();
      startFastPoll();
    } catch (e) {
      recoveryError = (e as Error).message || 'dispatch failed';
    } finally {
      recoveryBusy = false;
    }
  }

  function projectMatchKeys(): Set<string> {
    const keys = new Set<string>();
    if (projectId) keys.add(String(projectId));
    if (project?.id != null) keys.add(String(project.id));
    if (project?.project_id) keys.add(String(project.project_id));
    return keys;
  }

  function matchesThisProject(evProject: string | undefined | null): boolean {
    if (!evProject) return false;
    return projectMatchKeys().has(String(evProject));
  }

  function startFastPoll() {
    if (fastPollHandle !== null) return;
    fastPollHandle = window.setInterval(() => {
      void loadRecovery();
      void loadProject();
      void loadTerminalLog();
    }, 3000) as unknown as number;
  }

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
    terminalLines = [];
    feed = [];
    activeRole = null;
    activeRoleStartedAt = null;
    activeRoleMessage = null;
    lastDispatchedAction = null;
    lastDispatchAt = null;
    recoveryStarted = null;
    recoveryError = null;
    recoveryNote = '';
    codeFiles = [];
    openFile = null;
    openFileContent = '';
    deployment = { running: false };
    stopDeployPoll();
    stopFastPoll();
  }

  // Live activity feed — subscribes to /api/v2/decisions/subscribe and
  // filters events scoped to this project (role_started, role_finished,
  // role_failed, card_created, card_updated).
  interface FeedEvent {
    type: string;
    role?: string;
    message?: string;
    ts: number;
    artifact_chars?: number;
    files_written?: number;
    install_ok?: boolean;
    error?: string;
    title?: string;
    formatted?: string;
    level?: string;
  }
  let feed: FeedEvent[] = [];
  let activeRole: string | null = null;
  let activeRoleStartedAt: number | null = null;
  let activeRoleMessage: string | null = null;
  let lastDispatchedAction: string | null = null;
  let lastDispatchAt: number | null = null;
  let fastPollHandle: number | null = null;
  let nowTick = Date.now();
  let nowInterval: number | null = null;
  let sseSub: { close: () => void } | null = null;
  let terminalLines: TerminalLine[] = [];

  function appendTerminalLine(line: TerminalLine) {
    const text = (line.formatted || line.message || '').trim();
    if (!text) return;
    const prev = terminalLines[terminalLines.length - 1];
    if (prev && (prev.formatted || prev.message) === text) return;
    terminalLines = [...terminalLines, { ...line, formatted: line.formatted || text }].slice(-500);
  }

  function formatFeedAsTerminal(ev: FeedEvent): string | null {
    switch (ev.type) {
      case 'dispatch_started':
        return `[hub] You started ${ev.message ?? 'a role'}`;
      case 'role_started':
        return `[${ev.role ?? 'role'}] ${ev.message ?? 'started'}`;
      case 'role_finished':
        return `[${ev.role ?? 'role'}] finished${
          ev.files_written != null ? ` · ${ev.files_written} files written` : ''
        }${ev.artifact_chars != null ? ` · ${ev.artifact_chars} chars` : ''}`;
      case 'role_failed':
        return `[${ev.role ?? 'role'}] FAILED — ${ev.error ?? 'unknown error'}`;
      default:
        return null;
    }
  }

  async function loadTerminalLog() {
    if (!projectId) return;
    try {
      const res = await api.get<{ lines?: TerminalLine[] }>(
        `/api/v2/projects/${projectId}/activity/terminal?limit=500`
      );
      if (res.lines) {
        terminalLines = res.lines;
      }
    } catch {
      /* terminal history is best-effort */
    }
  }

  function pipelineRoleInfo(role: string) {
    const r = PIPELINE_COPY.roles[role as keyof typeof PIPELINE_COPY.roles];
    return r ?? { label: role, what: 'Processing project work', typical: '~60s' };
  }
  $: roleInfo = activeRole ? pipelineRoleInfo(activeRole) : null;
  $: elapsedSecs = activeRoleStartedAt ? Math.max(0, Math.round((nowTick - activeRoleStartedAt) / 1000)) : 0;
  $: progressCeiling = (() => {
    if (!roleInfo) return 60;
    const m = roleInfo.typical.match(/(\d+)\s*-\s*(\d+)/);
    return m ? parseInt(m[2], 10) : 60;
  })();

  async function loadProject(): Promise<boolean> {
    if (!projectId) return false;
    try {
      const res = await api.get<ProjectFull>(`/api/v2/projects/${projectId}/full`);
      project = res;
      projectError = null;
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
  async function loadWorkspace(id: string, opts: { initial?: boolean } = {}) {
    if (!id) return;
    const isNewProject = id !== lastLoadedProjectId;
    if (opts.initial || isNewProject) {
      projectLoading = true;
      if (isNewProject) {
        lastLoadedProjectId = id;
        project = null;
        recovery = null;
        stuckByProject = {};
        workspaceTabPinned = false;
        workspaceTab = 'pipeline';
        transcript = [];
        intakeDone = false;
        resetTransientWorkspaceState();
      }
    }
    try {
      const ok = await loadProject();
      if (!ok) return;
      await Promise.all([loadRecovery(), loadStuckSummary()]);
      if (isNewProject) void loadTerminalLog();
      if (project?.current_phase === 'intake' && transcript.length === 0) {
        await kickoff();
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

  function pushFeed(ev: FeedEvent) {
    if (ev.type === 'role_log') {
      appendTerminalLine({
        formatted: ev.formatted ?? ev.message,
        message: ev.message,
        level: ev.level,
        ts: ev.ts
      });
    } else {
      const formatted = formatFeedAsTerminal(ev);
      if (formatted) {
        appendTerminalLine({
          formatted,
          level: ev.type === 'role_failed' ? 'error' : 'info',
          ts: ev.ts
        });
      }
    }
    feed = [...feed, ev].slice(-50);
    if (ev.type === 'role_started') {
      activeRole = ev.role ?? null;
      activeRoleStartedAt = (ev.ts ?? Date.now() / 1000) * 1000;
      activeRoleMessage = ev.message ?? null;
    }
    if (ev.type === 'role_finished' || ev.type === 'role_failed') {
      // Card landing also implies role is idle until next dispatch.
      if (activeRole === ev.role) {
        activeRole = null;
        activeRoleStartedAt = null;
        activeRoleMessage = null;
      }
      if (ev.type === 'role_finished') {
        lastDispatchedAction = null;
        recoveryStarted = null;
      }
      void loadWorkspace(projectId);
    }
    if (ev.type === 'card_created' || ev.type === 'card_updated') {
      void loadWorkspace(projectId);
      void decisions.load('pending');
    }
  }

  function subscribeLiveFeed() {
    if (sseSub) return;
    sseSub = subscribeSse<FeedEvent & { card?: any; project_uuid?: string }>(
      '/api/v2/decisions/subscribe',
      {
        onEvent: ({ data }) => {
          const ev = data as FeedEvent & { card?: any; project_uuid?: string };
          if (!ev?.type) return;
          const evProject =
            ev.project_uuid ??
            ev.card?.project_id ??
            ev.card?.metadata?.project_uuid;
          if (!matchesThisProject(evProject)) return;
          pushFeed({
            type: ev.type,
            role: ev.role ?? ev.card?.metadata?.produced_by,
            message: ev.message ?? ev.card?.title,
            title: ev.card?.title,
            ts: ev.ts ?? Date.now() / 1000,
            artifact_chars: ev.artifact_chars,
            files_written: ev.files_written,
            install_ok: ev.install_ok,
            error: ev.error,
            formatted: (ev as FeedEvent).formatted,
            level: (ev as FeedEvent).level
          });
        },
        onError: (err) => {
          if (isAbortError(err)) return;
          sseSub = null;
          setTimeout(() => subscribeLiveFeed(), 3000);
        }
      },
      { body: {} }
    );
  }

  onMount(() => {
    decisions.load('pending');
    void loadWorkspace(projectId, { initial: true });
    pollHandle = window.setInterval(() => {
      if (projectId) void loadWorkspace(projectId);
    }, 8000) as unknown as number;
    subscribeLiveFeed();
    void loadTerminalLog();
    nowInterval = window.setInterval(() => { nowTick = Date.now(); }, 1000) as unknown as number;
  });

  afterNavigate(({ to, from }) => {
    const nextId = to?.params?.project_id;
    const prevId = from?.params?.project_id;
    if (nextId && nextId !== prevId) {
      void loadWorkspace(nextId, { initial: true });
    }
  });

  onDestroy(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
    stopDeployPoll();
    if (nowInterval !== null) window.clearInterval(nowInterval);
    stopFastPoll();
    sseSub?.close();
    sseSub = null;
  });

  $: if (dispatchInFlightActive(recovery) || activeRole || recoveryBusy) {
    startFastPoll();
  } else if (!lastDispatchAt || Date.now() - lastDispatchAt > 5 * 60 * 1000) {
    stopFastPoll();
  }

  function feedLabel(ev: FeedEvent): string {
    if (ev.type === 'dispatch_started') {
      return `You started ${ev.message ?? ev.role ?? 'a role'}`;
    }
    if (ev.type === 'role_started') return `${ev.role} started${ev.message ? ' — ' + ev.message : ''}`;
    if (ev.type === 'role_finished') {
      if (ev.files_written !== undefined) return `${ev.role} wrote ${ev.files_written} files`;
      if (ev.install_ok !== undefined) return `${ev.role} install ${ev.install_ok ? 'succeeded' : 'failed'}`;
      if (ev.artifact_chars !== undefined) return `${ev.role} produced ${ev.artifact_chars.toLocaleString()} chars`;
      return `${ev.role} finished`;
    }
    if (ev.type === 'role_failed') return `${ev.role} failed: ${ev.error ?? 'unknown error'}`;
    if (ev.type === 'card_created') return `Decision: ${ev.title ?? ev.message ?? '(no title)'}`;
    if (ev.type === 'card_updated') return `Decision updated: ${ev.title ?? ev.message ?? ''}`;
    return ev.type.replace(/_/g, ' ');
  }

  function feedTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function feedEmptyMessage(): string {
    if (activeRole && roleInfo) {
      return `${roleInfo.label}: ${roleInfo.what} Typical duration: ${roleInfo.typical}.`;
    }
    if (dispatchInFlightActive(recovery)) {
      const kind = recovery?.dispatch_in_flight?.dispatch_kind;
      const label = dispatchKindLabel(kind);
      return `${label} is in progress. Log output will appear here shortly (typically within 30–90 seconds).`;
    }
    if (recoveryStarted || lastDispatchedAction) {
      return 'Your request was accepted. Output will stream here as the step runs.';
    }
    return PIPELINE_COPY.terminal.emptyIdle;
  }

  $: terminalActive = Boolean(activeRole || recoveryBusy || dispatchInFlightActive(recovery));
  $: terminalTitle = activeRole
    ? PIPELINE_COPY.terminal.titleLive(pipelineRoleInfo(activeRole).label)
    : dispatchInFlightActive(recovery)
      ? PIPELINE_COPY.terminal.titleLive(
          dispatchKindLabel(recovery?.dispatch_in_flight?.dispatch_kind)
        )
      : PIPELINE_COPY.terminal.titleIdle;
  $: terminalEmptyMessage = terminalActive
    ? PIPELINE_COPY.terminal.emptyRunning
    : feedEmptyMessage();

  $: activityAction =
    recovery?.dispatch_in_flight?.action ??
    lastDispatchedAction ??
    selectedRecoveryAction;
  $: activityInfo = activityAction ? recoveryActionInfo(activityAction) : null;
  $: showActivityPanel =
    Boolean(activityInfo) &&
    (dispatchInFlightActive(recovery) ||
      activeRole ||
      recoveryBusy ||
      recoveryStarted ||
      lastDispatchedAction);
  $: dispatchElapsedSecs =
    recovery?.dispatch_in_flight?.started_at
      ? Math.max(
          0,
          Math.round(
            (nowTick -
              Date.parse(String(recovery.dispatch_in_flight.started_at).replace('Z', '+00:00'))) /
              1000
          )
        )
      : lastDispatchAt
        ? Math.max(0, Math.round((nowTick - lastDispatchAt) / 1000))
        : elapsedSecs;

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
    if (md.code_review_md) out.push({ label: `Security review (security_engineer) ${md.code_review_blocked ? '⛔ BLOCKED' : '✅ PASS'}`, key: 'code_review_md', md: md.code_review_md });
    if (md.qa_md) out.push({ label: 'Test plan (qa role)', key: 'qa_md', md: md.qa_md });
    if (md.release_gate_md) out.push({ label: 'Ship gate (release_manager)', key: 'release_gate_md', md: md.release_gate_md });
    return out;
  })();

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

  $: if (recovery?.actions?.length) {
    const ids = recovery.actions.map((a) => a.action);
    const rec = recovery.recommended_action;
    if (!selectedRecoveryAction || !ids.includes(selectedRecoveryAction)) {
      selectedRecoveryAction =
        rec && ids.includes(rec) ? rec : ids[0] ?? null;
    }
  } else {
    selectedRecoveryAction = null;
  }

  $: selectedRecoverySpec =
    recovery?.actions.find((a) => a.action === selectedRecoveryAction) ?? null;

  const DISPATCH_STALE_MS = 20 * 60 * 1000;

  function isDispatchStale(
    inflight: RecoveryStatus['dispatch_in_flight']
  ): boolean {
    if (!inflight?.started_at) return true;
    const started = Date.parse(String(inflight.started_at).replace('Z', '+00:00'));
    if (Number.isNaN(started)) return true;
    return Date.now() - started > DISPATCH_STALE_MS;
  }

  function dispatchInFlightActive(rec: RecoveryStatus | null): boolean {
    const inflight = rec?.dispatch_in_flight;
    return Boolean(inflight && !isDispatchStale(inflight));
  }

  function primaryStuckReason(reasons: string[]): string {
    const order = [
      'fix_loop_exhausted',
      'code_review_blocked',
      'last_role_failed',
      'workspace_empty_stale_metadata',
      'workspace_empty_no_code',
      'no_pending_decisions',
    ];
    for (const r of order) {
      if (reasons.includes(r)) return r;
    }
    return reasons[0] ?? 'no_pending_decisions';
  }

  $: stuckSummaryEntry = project
    ? stuckForProject(
        {
          project_id: String(project.id),
          project_uuid: project.project_id,
          name: project.name,
          project_type: project.project_type,
          current_phase: project.current_phase,
          status: project.status
        },
        stuckByProject
      )
    : stuckForProject(
        { project_id: projectId, name: '', project_type: '', current_phase: '', status: '' },
        stuckByProject
      );

  $: isPipelineStuck = Boolean(
    recovery?.stuck ||
      stuckSummaryEntry ||
      (project?.metadata?.code_review_blocked &&
        !activeRole &&
        projectDecisions.length === 0 &&
        !dispatchInFlightActive(recovery))
  );

  $: effectiveStuckReasons =
    recovery?.reasons && recovery.reasons.length > 0
      ? recovery.reasons
      : (stuckSummaryEntry?.reasons ?? []);

  $: projectNeedsAttention = projectDecisions.length > 0 || isPipelineStuck;

  $: attentionLabel = (() => {
    if (projectDecisions.length > 0) {
      return PIPELINE_COPY.attention.decisionsReview(projectDecisions.length);
    }
    if (isPipelineStuck) return PIPELINE_COPY.attention.paused;
    return null;
  })();

  $: recoveryActionsSorted = recovery?.actions
    ? [...recovery.actions].sort((a, b) => {
        const rec = recovery?.recommended_action;
        if (a.action === rec) return -1;
        if (b.action === rec) return 1;
        return 0;
      })
    : [];

  $: recoveryDispatchBlocked =
    recoveryBusy || activeRole !== null || dispatchInFlightActive(recovery);

  $: pipelineStatusMode = (() => {
    if (activeRole) return 'working';
    if (dispatchInFlightActive(recovery)) return 'running';
    if (projectDecisions.length > 0) return 'decisions';
    if (recovery?.last_role_failure?.error) return 'failed';
    if (isPipelineStuck) return 'blocked';
    return 'idle';
  })();

  $: pipelineHeadline = (() => {
    if (activeRole && roleInfo) return PIPELINE_COPY.status.working(roleInfo.label);
    const inflight = recovery?.dispatch_in_flight;
    if (dispatchInFlightActive(recovery) && inflight) {
      const label = dispatchKindLabel(inflight.dispatch_kind);
      return PIPELINE_COPY.status.starting(label);
    }
    if (projectDecisions.length > 0) {
      return PIPELINE_COPY.status.decisions(projectDecisions.length);
    }
    if (isPipelineStuck && effectiveStuckReasons.length > 0) {
      return `${PIPELINE_COPY.status.pausedPrefix} — ${humanStuckReason(primaryStuckReason(effectiveStuckReasons))}`;
    }
    if (isPipelineStuck) {
      return PIPELINE_COPY.attention.paused;
    }
    if (recovery?.last_role_failure?.error) {
      const failedRole = recovery.last_role_failure.role ?? 'Previous step';
      return PIPELINE_COPY.status.failed(pipelineRoleInfo(failedRole).label);
    }
    return PIPELINE_COPY.status.idle;
  })();

  $: pipelineSubtext = (() => {
    if (activeRole && roleInfo) {
      return PIPELINE_COPY.subtext.roleProgress(
        activeRoleMessage ?? roleInfo.what,
        elapsedSecs,
        roleInfo.typical
      );
    }
    if (projectDecisions.length > 0) {
      return PIPELINE_COPY.subtext.decisions;
    }
    if (isPipelineStuck && selectedRecoverySpec) {
      return PIPELINE_COPY.subtext.suggestedAction(selectedRecoverySpec.label);
    }
    if (dispatchInFlightActive(recovery)) {
      if (activityInfo) {
        return PIPELINE_COPY.subtext.dispatchProgress(
          activityInfo.steps[0],
          dispatchElapsedSecs,
          activityInfo.typical
        );
      }
      return PIPELINE_COPY.subtext.dispatchWaiting;
    }
    if (recovery?.last_role_failure?.error) {
      return recovery.last_role_failure.error;
    }
    return PIPELINE_COPY.subtext.background;
  })();

  function statusStripClass(mode: string): string {
    switch (mode) {
      case 'working':
      case 'running':
        return 'border-accent/40 bg-accent/10';
      case 'decisions':
      case 'blocked':
        return 'border-amber-400/40 bg-amber-400/10';
      case 'failed':
        return 'border-rose-500/40 bg-rose-500/10';
      default:
        return 'border-surface-600/80 bg-surface-800/50';
    }
  }

  function feedTone(ev: FeedEvent): string {
    if (ev.type === 'dispatch_started') return 'border border-violet-400/40 bg-violet-400/10 text-violet-200';
    if (ev.type === 'role_started') return 'border border-accent/40 bg-accent/10 text-accent';
    if (ev.type === 'role_finished' && ev.install_ok === false) {
      return 'border border-amber-400/40 bg-amber-400/10 text-amber-200';
    }
    if (ev.type === 'role_finished') return 'border border-sky-400/40 bg-sky-400/10 text-sky-200';
    if (ev.type === 'role_failed') return 'border border-rose-500/40 bg-rose-500/10 text-rose-200';
    if (ev.type === 'card_created') return 'border border-violet-400/40 bg-violet-400/10 text-violet-200';
    return 'border border-surface-600 bg-surface-800/60 text-surface-300';
  }

  function artifactShortLabel(label: string): string {
    return label.split(' (')[0];
  }

  function artifactTone(key: string): string {
    if (key === 'code_review_md' && project?.metadata?.code_review_blocked) {
      return 'text-severity-critical';
    }
    return '';
  }

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

  $: if (codeFiles.length > 0 && (!openFile || !codeFiles.some((f) => f.path === openFile))) {
    void loadFile(codeFiles[0].path);
  }

  $: if (project?.metadata?.code_files) refreshCodeFiles();

  // Deployment status — polls /deployment for live process state.
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

  $: if (project?.metadata?.code_files?.length > 0 && deployPollHandle === null) {
    loadDeployment();
    deployPollHandle = window.setInterval(loadDeployment, 5000) as unknown as number;
  }

  $: workspaceTabs = (() => {
    const tabs: { id: WorkspaceTab; label: string; count?: number; attention?: boolean }[] = [];
    if (project?.current_phase === 'intake') tabs.push({ id: 'intake', label: 'Intake' });
    tabs.push({
      id: 'decisions',
      label: 'Decisions',
      count: projectDecisions.length || undefined,
    });
    tabs.push({
      id: 'pipeline',
      label: 'Pipeline',
      attention: Boolean(
        isPipelineStuck && !activeRole && projectDecisions.length === 0
      ),
    });
    if (artifacts.length > 0) {
      tabs.push({ id: 'artifacts', label: 'Artifacts', count: artifacts.length });
    }
    if (codeFiles.length > 0) {
      tabs.push({ id: 'code', label: 'Code', count: codeFiles.length });
    }
    return tabs;
  })();

  $: if (project) {
    if (!workspaceTabs.some((t) => t.id === workspaceTab)) {
      workspaceTab =
        workspaceTabs.find((t) => t.id === 'decisions')?.id ??
        workspaceTabs.find((t) => t.id === 'pipeline')?.id ??
        workspaceTabs[0]?.id ??
        'pipeline';
    } else if (!workspaceTabPinned) {
      if (project.current_phase === 'intake') workspaceTab = 'intake';
      else if (projectDecisions.length > 0) workspaceTab = 'decisions';
      else if (isPipelineStuck && !activeRole) workspaceTab = 'pipeline';
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
  <a href="{base}/" class="btn-ghost text-base">← Dashboard</a>
</header>

{#if projectError}
  <div class="mb-4"><ErrorBanner kind="error" message={projectError} onDismiss={() => (projectError = null)} /></div>
{/if}

{#if projectLoading && !project}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading project" /></div>
{:else if projectError && !project}
  <div class="mb-4"><ErrorBanner kind="error" message={projectError} onDismiss={() => (projectError = null)} /></div>
{:else if project}
  <div class="project-workspace">
  {#if attentionLabel}
    <div class="mb-4 flex flex-wrap items-center gap-3" data-testid="project-attention-badge">
      <span
        class="inline-flex items-center gap-2 rounded-full border border-amber-500/50 bg-amber-500/15 px-4 py-1.5 text-sm font-semibold text-amber-100"
      >
        {#if recovery?.stuck && projectDecisions.length === 0}
          <span class="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true"></span>
        {/if}
        {attentionLabel}
      </span>
      {#if isPipelineStuck && selectedRecoverySpec && projectDecisions.length === 0}
        <button
          type="button"
          class="btn-primary text-sm sm:text-base"
          disabled={recoveryDispatchBlocked}
          on:click={() => {
            selectWorkspaceTab('pipeline');
            dispatchRecovery(selectedRecoverySpec.action);
          }}
        >
          {recoveryBusy ? 'Starting…' : `Run ${selectedRecoverySpec.label}`}
        </button>
      {/if}
    </div>
  {/if}
  <div
    class="mb-5 rounded-lg border px-5 py-4 {statusStripClass(pipelineStatusMode)}"
    data-testid="pipeline-status-strip"
  >
    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div class="min-w-0 flex-1">
        {#if activeRole && roleInfo}
          <div class="flex items-start gap-3">
            <span class="relative mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center">
              <span class="relative h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
            </span>
            <div class="min-w-0">
              <p class="pw-status-headline text-surface-50">{pipelineHeadline}</p>
              <p class="pw-status-sub mt-1 text-surface-300">{pipelineSubtext}</p>
            </div>
          </div>
        {:else}
          <p class="pw-status-headline text-surface-50">{pipelineHeadline}</p>
          <p class="pw-status-sub mt-1 text-surface-300">{pipelineSubtext}</p>
        {/if}
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-2">
        {#if projectDecisions.length > 0}
          <button type="button" class="btn-primary text-base" on:click={() => selectWorkspaceTab('decisions')}>
            {PIPELINE_COPY.decisions.reviewButton(projectDecisions.length)}
          </button>
        {:else if isPipelineStuck && selectedRecoverySpec && !recoveryDispatchBlocked}
          <button type="button" class="btn-primary text-base" on:click={() => { selectWorkspaceTab('pipeline'); dispatchRecovery(selectedRecoverySpec.action); }}>
            {recoveryBusy ? 'Starting…' : `Run ${selectedRecoverySpec.label}`}
          </button>
        {/if}
      </div>
    </div>
    <div class="mt-3 flex flex-wrap items-center gap-2">
      {#each PHASES as ph, i (ph)}
        {@const state = (() => {
          const idx = phaseIndex(project.current_phase);
          return idx < 0 ? 'pending' : i < idx ? 'done' : i === idx ? 'active' : 'pending';
        })()}
        <span class="rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide sm:text-sm {state === 'active' ? 'bg-accent text-white' : state === 'done' ? 'border border-sky-500/40 bg-sky-500/10 text-sky-200' : 'border border-surface-600 bg-surface-800/40 text-surface-400'}">{ph}</span>
        {#if i < PHASES.length - 1}<span class="text-base text-surface-600">→</span>{/if}
      {/each}
    </div>
  </div>

  <section class="workspace-shell panel-card mb-6" data-testid="project-pipeline">
    <nav class="workspace-tab-bar flex flex-wrap items-center gap-1 border-b border-surface-700/60 pb-0" role="tablist" aria-label="Project workspace">
      {#each workspaceTabs as tab (tab.id)}
        <button
          type="button"
          role="tab"
          aria-selected={workspaceTab === tab.id}
          class="workspace-tab-btn relative px-4 py-3 text-base font-medium transition-colors {workspaceTab === tab.id ? 'text-accent' : 'text-surface-400 hover:text-surface-200'}"
          on:click={() => selectWorkspaceTab(tab.id)}
        >
          {tab.label}
          {#if tab.count}
            <span class="ml-2 rounded-full bg-accent/20 px-2 py-0.5 text-xs font-semibold text-accent sm:text-sm">{tab.count}</span>
          {:else if tab.attention}
            <span class="ml-2 rounded-full border border-amber-500/50 bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-200 sm:text-sm">{PIPELINE_COPY.pipelineTab.badgeActionRequired}</span>
          {/if}
        </button>
      {/each}
      <a href="{base}/panels/decision-queue" class="ml-auto text-sm text-surface-500 hover:text-accent">All decisions →</a>
    </nav>

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
        <div class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0" data-testid="project-decisions">
          {#if projectDecisions.length === 0}
            <div class="space-y-3 py-6 lg:col-span-12">
              <p class="text-base text-surface-300 sm:text-lg">No pending decisions for this project.</p>
              {#if isPipelineStuck}
                <p class="text-base text-amber-100 sm:text-lg">
                  {PIPELINE_COPY.pipelineTab.decisionsEmptyLead}
                  <button type="button" class="font-semibold text-accent underline hover:text-accent/80" on:click={() => selectWorkspaceTab('pipeline')}>Pipeline</button>
                  {PIPELINE_COPY.pipelineTab.decisionsEmptyTrail}
                </p>
              {/if}
            </div>
          {:else}
            <ul class="workspace-list divide-y divide-surface-700/60 overflow-y-auto rounded-lg border border-surface-700/60 lg:col-span-4 lg:rounded-r-none lg:border-r-0" role="listbox">
              {#each projectDecisions as card (card.decision_id)}
                <li class="flex items-stretch border-l-2 {card.decision_id === selectedProjectDecisionId ? 'border-accent bg-accent/10' : 'border-transparent'}">
                  <button type="button" class="min-w-0 flex-1 px-3 py-2 text-left text-sm" on:click={() => (selectedProjectDecisionId = card.decision_id)}>
                    <span class="text-[0.6rem] uppercase text-surface-500">{card.decision_class}</span>
                    <span class="mt-0.5 line-clamp-2 block font-medium text-surface-100">{card.title}</span>
                  </button>
                  <div class="flex flex-col justify-center gap-1 border-l border-surface-700/60 px-1 py-1">
                    <button type="button" class="inline-flex h-7 w-7 items-center justify-center rounded text-emerald-400 hover:bg-emerald-500/15" title="Approve" disabled={decisionBusyId === card.decision_id} on:click|stopPropagation={() => ackProjectDecision(card)}>✓</button>
                    <button type="button" class="inline-flex h-7 w-7 items-center justify-center rounded text-rose-400 hover:bg-rose-500/15" title="Reject" disabled={decisionBusyId === card.decision_id} on:click|stopPropagation={() => rejectProjectDecision(card)}>✕</button>
                  </div>
                </li>
              {/each}
            </ul>
            <div class="workspace-detail flex flex-col overflow-hidden rounded-lg border border-surface-700/60 lg:col-span-8 lg:rounded-l-none">
              {#if selectedProjectDecision}
                <header class="shrink-0 border-b border-surface-700/60 px-4 py-3">
                  <h3 class="text-sm font-semibold text-surface-50">{selectedProjectDecision.title}</h3>
                  <p class="mt-1 text-xs text-surface-400">{projectDecisionHint(selectedProjectDecision)}</p>
                </header>
                <div class="workspace-scroll min-h-0 flex-1 overflow-y-auto p-4">
                  <pre class="whitespace-pre-wrap text-sm leading-relaxed text-surface-300">{selectedProjectDecision.body || 'No details.'}</pre>
                </div>
                <footer class="flex shrink-0 justify-end gap-2 border-t border-surface-700/60 px-4 py-3">
                  <button type="button" class="btn-ghost text-sm" disabled={decisionBusyId === selectedProjectDecision.decision_id} on:click={() => rejectProjectDecision(selectedProjectDecision)}>Reject</button>
                  <button type="button" class="btn-primary text-sm" disabled={decisionBusyId === selectedProjectDecision.decision_id} on:click={() => ackProjectDecision(selectedProjectDecision)}>
                    {decisionBusyId === selectedProjectDecision.decision_id ? 'Working…' : 'Approve'}
                  </button>
                </footer>
              {/if}
            </div>
          {/if}
        </div>

      {:else if workspaceTab === 'pipeline'}
        {#if recoveryError}<div class="mb-3"><ErrorBanner kind="error" message={recoveryError} onDismiss={() => (recoveryError = null)} /></div>{/if}
        {#if recovery?.fix_loop_exhausted}
          <div class="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-base text-rose-100">
            {PIPELINE_COPY.fixLoop.exhausted(
              recovery.code_fix_iteration ?? 0,
              recovery.max_code_fix_iterations ?? 3
            )}
          </div>
        {:else if project?.metadata?.code_review_blocked && (recovery?.code_fix_iteration ?? 0) > 0}
          <div class="mb-3 rounded-lg border border-surface-700/60 bg-surface-900/40 px-4 py-3 text-base text-surface-300">
            {PIPELINE_COPY.fixLoop.iteration(
              recovery?.code_fix_iteration ?? project.metadata.code_fix_iteration ?? 0,
              recovery?.max_code_fix_iterations ?? 3
            )}
          </div>
        {/if}
        {#if showActivityPanel && activityInfo}
          <div class="mb-4 rounded-lg border border-accent/30 bg-accent/5 p-4" data-testid="pipeline-activity-panel">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-lg font-semibold text-surface-50">{PIPELINE_COPY.pipelineTab.activityTitle(activityInfo.label)}</p>
                <p class="mt-1 text-base text-surface-400">
                  Typical duration: {activityInfo.typical}
                  · {dispatchElapsedSecs}s elapsed
                  {#if dispatchInFlightActive(recovery)}
                    · {PIPELINE_COPY.pipelineTab.hubActive}
                  {/if}
                </p>
              </div>
              {#if recoveryBusy}
                <span class="text-base text-accent">{PIPELINE_COPY.pipelineTab.sending}</span>
              {:else if activeRole || dispatchInFlightActive(recovery)}
                <span class="inline-flex items-center gap-2 text-base text-accent">
                  <span class="h-2.5 w-2.5 animate-pulse rounded-full bg-accent" aria-hidden="true"></span>
                  {PIPELINE_COPY.pipelineTab.roleRunning}
                </span>
              {/if}
            </div>
            <ol class="mt-4 space-y-2.5 text-base text-surface-200">
              {#each activityInfo.steps as step, i}
                <li class="flex gap-3">
                  <span class="shrink-0 font-mono text-sm text-surface-500">{i + 1}.</span>
                  <span>{step}</span>
                </li>
              {/each}
            </ol>
            <p class="mt-4 text-base text-surface-400">
              <span class="font-medium text-surface-200">{PIPELINE_COPY.pipelineTab.activityWhenDone}</span>
              {activityInfo.outcome}
            </p>
          </div>
        {:else if recoveryStarted}
          <div class="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-base text-surface-200">{recoveryStarted}</div>
        {/if}
        <div class="workspace-pane workspace-split grid h-full grid-cols-1 lg:grid-cols-12 lg:gap-0" data-testid="pipeline-controls">
          <div class="lg:col-span-5 lg:border-r lg:border-surface-700/60 lg:pr-4">
            <p class="mb-2 text-base text-surface-400">{PIPELINE_COPY.pipelineTab.controlsLead}</p>
            {#if recoveryLoading && !recovery}
              <LoadingSpinner label="Loading actions" />
            {:else if !recovery?.actions?.length}
              <p class="text-base text-surface-400">{PIPELINE_COPY.pipelineTab.noActions}</p>
            {:else}
              <ul class="mb-3 divide-y divide-surface-700/60 overflow-y-auto rounded-lg border border-surface-700/60" role="listbox">
                {#each recoveryActionsSorted as act (act.action)}
                  <li>
                    <button type="button" class="flex w-full items-center justify-between gap-2 border-l-2 px-3 py-2 text-left text-sm hover:bg-surface-800/60 disabled:opacity-50 {act.action === selectedRecoveryAction ? 'border-accent bg-accent/10' : 'border-transparent'}" disabled={recoveryDispatchBlocked} on:click={() => (selectedRecoveryAction = act.action)}>
                      <span class="text-surface-100">{act.label}</span>
                      {#if act.action === recovery.recommended_action}<span class="text-[0.55rem] uppercase text-accent">{PIPELINE_COPY.pipelineTab.suggested}</span>{/if}
                    </button>
                  </li>
                {/each}
              </ul>
              {#if selectedRecoverySpec}
                <p class="mb-2 text-base text-surface-300">{selectedRecoverySpec.description}</p>
                <textarea class="input-field mb-2 resize-none text-base" rows="2" bind:value={recoveryNote} placeholder={PIPELINE_COPY.pipelineTab.notePlaceholder} disabled={recoveryDispatchBlocked}></textarea>
                <button type="button" class="btn-primary w-full text-base" disabled={recoveryDispatchBlocked} on:click={() => dispatchRecovery(selectedRecoverySpec.action)}>{recoveryBusy ? PIPELINE_COPY.pipelineTab.starting : PIPELINE_COPY.pipelineTab.runAction(selectedRecoverySpec.label)}</button>
              {/if}
            {/if}
          </div>
          <div class="workspace-activity flex min-h-[22rem] flex-col lg:col-span-7 lg:pl-4">
            <div class="mb-2 flex items-center justify-between gap-2">
              <p class="text-base text-surface-400">{PIPELINE_COPY.pipelineTab.liveTerminalLabel}</p>
              {#if terminalActive}
                <span class="text-xs text-surface-500">{PIPELINE_COPY.pipelineTab.refreshHint}</span>
              {/if}
            </div>
            <div class="min-h-0 flex-1">
              <RoleTerminal
                lines={terminalLines}
                active={terminalActive}
                title={terminalTitle}
                emptyMessage={terminalEmptyMessage}
              />
            </div>
            {#if feed.length > 0}
              <details class="mt-3 rounded-lg border border-surface-700/60 bg-surface-950/30 px-3 py-2">
                <summary class="cursor-pointer text-sm text-surface-400">
                  Event summary ({feed.length})
                </summary>
                <ol class="mt-2 max-h-40 space-y-1 overflow-y-auto">
                  {#each [...feed].reverse().slice(0, 12) as ev, i (i)}
                    <li class="flex items-start gap-2 text-xs text-surface-400">
                      <span class="shrink-0 uppercase {feedTone(ev)}">{ev.type.replace(/_/g, ' ')}</span>
                      <span class="min-w-0 flex-1">{feedLabel(ev)}</span>
                      <time class="shrink-0">{feedTime(ev.ts)}</time>
                    </li>
                  {/each}
                </ol>
              </details>
            {/if}
          </div>
        </div>

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
  .workspace-tab-btn[aria-selected='true'] {
    box-shadow: inset 0 -2px 0 0 rgb(139 92 246);
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
  .workspace-activity,
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
    .workspace-scroll,
    .workspace-activity .workspace-scroll {
      max-height: 14rem;
    }
  }
</style>
