/**
 * Isolated project workspace runtime — terminal stream, recovery state, and SSE
 * handling live here so the parent +page.svelte does not re-render on every
 * role_log line during long engineer / security runs.
 *
 * Design contract (do not break):
 * - Hub SSE is filtered to the bound project BEFORE queueing.
 * - High-frequency data (terminal, feed) commits via scheduleFrameCommit.
 * - Leaf Svelte components subscribe to narrow stores (see PipelineActivityLog).
 * - Recovery chrome updates are throttled; never tie log lines to full-page state.
 */

import { get, writable } from 'svelte/store';
import { api } from '$lib/api/client';
import { ApiError } from '$lib/api/types';
import type { TerminalLine } from '$lib/terminalLine';
import { PIPELINE_COPY, recoveryActionInfo } from '$lib/projectPipelineCopy';
import { toasts } from '$lib/stores/toasts';
import { yieldMainThread } from '$lib/yieldMainThread';
import { flushFrameCommitsForBoot, scheduleFrameCommit } from '$lib/uiFrameScheduler';
import {
  decisionActivity,
  decisionRoleLogBatch,
  type DecisionActivityEvent,
} from '$lib/stores/decisions';
import {
  dispatchInFlightActive,
  type RecoveryStatus,
} from '$lib/projectRecoveryUtils';

export type { RecoveryStatus };

export interface RunState {
  activeRole: string | null;
  activeRoleStartedAt: number | null;
  activeRoleMessage: string | null;
  lastDispatchedAction: string | null;
  lastDispatchAt: number | null;
  recoveryStarted: string | null;
}

export interface FeedEvent {
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
  refresh_artifacts?: boolean;
}

export type MetadataPatchHandler = (
  patch: Record<string, unknown>,
  currentPhase?: string
) => void;

export type ArtifactsRefreshHandler = () => void;

const TERMINAL_CAP = 200;
const FEED_CAP = 50;
const SSE_BATCH_SIZE = 12;
const SSE_BATCH_MS = 200;
const SSE_QUEUE_CAP = 256;
const LOG_FLUSH_MS = 400;
const LOG_BATCH_MAX = 24;
const RECOVERY_PULSE_MIN_MS = 300;

const initialRunState: RunState = {
  activeRole: null,
  activeRoleStartedAt: null,
  activeRoleMessage: null,
  lastDispatchedAction: null,
  lastDispatchAt: null,
  recoveryStarted: null,
};

export const wsRecovery = writable<RecoveryStatus | null>(null);
export const wsRunState = writable<RunState>({ ...initialRunState });
export const wsTerminal = writable<TerminalLine[]>([]);
export const wsFeed = writable<FeedEvent[]>([]);
export const wsRecoveryBusy = writable(false);
export const wsRecoveryLoading = writable(false);
export const wsRecoveryError = writable<string | null>(null);
export const wsLastRecoveryPulseAt = writable(0);
export const wsDispatchUiStale = writable(false);

let boundProjectId: string | null = null;
let projectMatchKeys = new Set<string>();
let activityUnsub: (() => void) | null = null;
let roleLogUnsub: (() => void) | null = null;
let sseQueue: DecisionActivityEvent[] = [];
let sseFlushTimer: ReturnType<typeof setTimeout> | null = null;
let logBuffer: TerminalLine[] = [];
let logFlushTimer: ReturnType<typeof setTimeout> | null = null;
let recoveryLoadTimer: ReturnType<typeof setTimeout> | null = null;
/** Coalesce concurrent GET /recovery calls; callers always await the same promise. */
let recoveryLoadPromise: Promise<void> | null = null;
let recoveryLoadPending = false;
/** Bumped on wsUnbind so in-flight recovery responses cannot paint the wrong project. */
let recoveryLoadGeneration = 0;
/** Drop hub SSE noise until the first recovery snapshot for this bind is applied. */
let workspaceActivityReady = false;
const RECOVERY_FETCH_TIMEOUT_MS = 12_000;
let dispatchUiStaleTimer: ReturnType<typeof setTimeout> | null = null;
let metadataPatchHandler: MetadataPatchHandler | null = null;
let artifactsRefreshHandler: ArtifactsRefreshHandler | null = null;
let sseLiveConnected = false;
let lastRecoveryPulseAppliedAt = 0;
let pendingRecoveryPulse: DecisionActivityEvent | null = null;
let recoveryPulseTimer: ReturnType<typeof setTimeout> | null = null;

export function wsSetSseLive(connected: boolean): void {
  sseLiveConnected = connected;
}

export function wsSetMetadataPatchHandler(handler: MetadataPatchHandler | null): void {
  metadataPatchHandler = handler;
}

export function wsSetArtifactsRefreshHandler(handler: ArtifactsRefreshHandler | null): void {
  artifactsRefreshHandler = handler;
}

function matchesProject(evProject: string | undefined | null): boolean {
  if (!evProject) return false;
  return projectMatchKeys.has(String(evProject));
}

function eventProjectUuid(ev: DecisionActivityEvent): string | undefined {
  return (ev.project_uuid ??
    ev.card?.project_id ??
    ev.card?.metadata?.project_uuid) as string | undefined;
}

/** Drop hub-wide SSE noise before it enters the workspace queue. */
function shouldAcceptActivityEvent(ev: DecisionActivityEvent): boolean {
  if (ev.type === 'recovery_pulse' || ev.type === 'project_pulse') {
    return matchesProject(ev.project_uuid);
  }
  const pid = eventProjectUuid(ev);
  return matchesProject(pid);
}

function flushRecoveryPulse(): void {
  recoveryPulseTimer = null;
  const ev = pendingRecoveryPulse;
  pendingRecoveryPulse = null;
  if (!ev) return;
  applyRecoveryFromPulse(ev);
}

function scheduleRecoveryPulse(ev: DecisionActivityEvent): void {
  pendingRecoveryPulse = ev;
  const now = Date.now();
  const elapsed = now - lastRecoveryPulseAppliedAt;
  if (elapsed >= RECOVERY_PULSE_MIN_MS) {
    if (recoveryPulseTimer !== null) {
      clearTimeout(recoveryPulseTimer);
      recoveryPulseTimer = null;
    }
    lastRecoveryPulseAppliedAt = now;
    pendingRecoveryPulse = null;
    applyRecoveryFromPulse(ev);
    return;
  }
  if (recoveryPulseTimer === null) {
    recoveryPulseTimer = setTimeout(flushRecoveryPulse, RECOVERY_PULSE_MIN_MS - elapsed);
  }
}

function handleRoleLogBatch(batch: DecisionActivityEvent[]): void {
  if (!workspaceActivityReady || !batch.length) return;
  for (const ev of batch) {
    if (!shouldAcceptActivityEvent(ev)) continue;
    pushFeed({
      type: ev.type,
      role: ev.role,
      message: ev.message,
      ts: ev.ts ?? Date.now() / 1000,
      formatted: ev.formatted,
      level: (ev as { level?: string }).level,
    });
  }
}

function flushLogBuffer(): void {
  logFlushTimer = null;
  if (logBuffer.length === 0) return;
  const batch = logBuffer.splice(0, LOG_BATCH_MAX);
  scheduleFrameCommit(() => {
    wsTerminal.update((lines) => [...lines, ...batch].slice(-TERMINAL_CAP));
  });
  if (logBuffer.length > 0) {
    logFlushTimer = setTimeout(flushLogBuffer, LOG_FLUSH_MS);
  }
}

function appendTerminal(line: TerminalLine): void {
  const text = (line.formatted || line.message || '').trim();
  if (!text) return;
  logBuffer.push({ ...line, formatted: line.formatted || text });
  if (logFlushTimer !== null) return;
  logFlushTimer = setTimeout(flushLogBuffer, LOG_FLUSH_MS);
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

function armDispatchUiStaleTimer(): void {
  if (dispatchUiStaleTimer) clearTimeout(dispatchUiStaleTimer);
  wsDispatchUiStale.set(false);
  dispatchUiStaleTimer = setTimeout(() => {
    dispatchUiStaleTimer = null;
    wsDispatchUiStale.set(true);
  }, 120_000);
}

function clearDispatchUiStaleTimer(): void {
  if (dispatchUiStaleTimer) clearTimeout(dispatchUiStaleTimer);
  dispatchUiStaleTimer = null;
  wsDispatchUiStale.set(false);
}

function applyRecoveryFromPulse(ev: DecisionActivityEvent): void {
  wsLastRecoveryPulseAt.set(Date.now());
  scheduleFrameCommit(() => {
    wsRecovery.set({
      stuck: Boolean(ev.stuck),
      reasons: ev.reasons ?? [],
      pending_decisions: ev.pending_decisions ?? 0,
      recommended_action: ev.recommended_action,
      last_role_failure: ev.last_role_failure ?? null,
      dispatch_in_flight:
        ev.dispatch_in_flight && typeof ev.dispatch_in_flight === 'object'
          ? ev.dispatch_in_flight
          : null,
      actions: ev.actions ?? [],
      code_fix_iteration: ev.code_fix_iteration,
      max_code_fix_iterations: ev.max_code_fix_iterations,
      fix_loop_exhausted: ev.fix_loop_exhausted,
      code_review_blocked: ev.code_review_blocked,
      current_phase: typeof ev.current_phase === 'string' ? ev.current_phase : undefined,
    });
  });

  const inflight =
    ev.dispatch_in_flight && typeof ev.dispatch_in_flight === 'object' ? ev.dispatch_in_flight : null;
  const busy = get(wsRecoveryBusy);
  if (!dispatchInFlightActive({ dispatch_in_flight: inflight } as RecoveryStatus) && !busy) {
    wsRunState.update((s) => ({
      ...s,
      activeRole: null,
      activeRoleStartedAt: null,
      activeRoleMessage: null,
      recoveryStarted: null,
    }));
    clearDispatchUiStaleTimer();
  }

  if (typeof ev.current_phase === 'string') {
    metadataPatchHandler?.({}, ev.current_phase);
  }

  wsRecoveryLoading.set(false);
  workspaceActivityReady = true;
}

function pushFeed(ev: FeedEvent): void {
  if (ev.type === 'role_log') {
    appendTerminal({
      formatted: ev.formatted ?? ev.message,
      message: ev.message,
      level: ev.level,
      ts: ev.ts,
    });
    return;
  }

  const formatted = formatFeedAsTerminal(ev);
  if (formatted) {
    appendTerminal({
      formatted,
      level: ev.type === 'role_failed' ? 'error' : 'info',
      ts: ev.ts,
    });
  }

  scheduleFrameCommit(() => {
    wsFeed.update((feed) => [...feed, ev].slice(-FEED_CAP));
  });

  if (ev.type === 'role_started') {
    wsRunState.update((s) => ({
      ...s,
      activeRole: ev.role ?? null,
      activeRoleStartedAt: (ev.ts ?? Date.now() / 1000) * 1000,
      activeRoleMessage: ev.message ?? null,
    }));
  }

  if (ev.type === 'role_finished' || ev.type === 'role_failed') {
    wsRunState.update((s) => {
      if (s.activeRole !== ev.role) return s;
      return {
        ...s,
        activeRole: null,
        activeRoleStartedAt: null,
        activeRoleMessage: null,
      };
    });

    if (ev.type === 'role_finished') {
      wsRunState.update((s) => ({
        ...s,
        lastDispatchedAction: null,
        recoveryStarted: null,
      }));
      clearDispatchUiStaleTimer();
      if (ev.refresh_artifacts) artifactsRefreshHandler?.();
    }

    if (!sseLiveConnected && boundProjectId) scheduleLoadRecovery(boundProjectId, false, false);
  }

  if (ev.type === 'card_created' || ev.type === 'card_updated') {
    if (!sseLiveConnected && boundProjectId) scheduleLoadRecovery(boundProjectId, false, false);
  }
}

function handleProjectPulse(ev: DecisionActivityEvent): void {
  if (ev.dispatch_in_flight === false) {
    wsRecovery.update((r) => (r ? { ...r, dispatch_in_flight: null } : r));
  }
  if (typeof ev.current_phase === 'string') {
    metadataPatchHandler?.({}, ev.current_phase);
  }
  if (!sseLiveConnected && boundProjectId) scheduleLoadRecovery(boundProjectId, false, false);
  if (ev.refresh_artifacts) artifactsRefreshHandler?.();
}

function handleActivityEvent(ev: DecisionActivityEvent): void {
  if (ev.type === 'recovery_pulse') {
    scheduleRecoveryPulse(ev);
    return;
  }
  if (ev.type === 'project_pulse') {
    if (!matchesProject(ev.project_uuid)) return;
    handleProjectPulse(ev);
    return;
  }

  const evProject = eventProjectUuid(ev);
  if (!matchesProject(evProject)) return;

  pushFeed({
    type: ev.type,
    role: (ev.role ?? ev.card?.metadata?.produced_by) as string | undefined,
    message: ev.message ?? ev.card?.title,
    title: ev.card?.title,
    ts: ev.ts ?? Date.now() / 1000,
    artifact_chars: ev.artifact_chars,
    files_written: ev.files_written,
    install_ok: ev.install_ok,
    error: ev.error,
    formatted: ev.formatted,
    level: (ev as { level?: string }).level,
    refresh_artifacts: ev.refresh_artifacts,
  });
}

function queueActivityEvent(ev: DecisionActivityEvent): void {
  if (!workspaceActivityReady && ev.type !== 'recovery_pulse') return;
  if (!shouldAcceptActivityEvent(ev)) return;
  if (sseQueue.length >= SSE_QUEUE_CAP) {
    sseQueue = sseQueue.filter((item) => item.type !== 'role_log').slice(-Math.floor(SSE_QUEUE_CAP / 2));
  }
  sseQueue.push(ev);
  if (sseFlushTimer === null) {
    sseFlushTimer = setTimeout(() => void flushSseQueue(), SSE_BATCH_MS);
  }
}

async function flushSseQueue(): Promise<void> {
  sseFlushTimer = null;
  const batch = sseQueue.splice(0, SSE_BATCH_SIZE);
  for (const item of batch) handleActivityEvent(item);
  await yieldMainThread();
  if (sseQueue.length > 0) {
    sseFlushTimer = setTimeout(() => void flushSseQueue(), SSE_BATCH_MS);
  }
}

export function wsResetTransient(): void {
  wsTerminal.set([]);
  wsFeed.set([]);
  wsRunState.set({ ...initialRunState });
  wsRecoveryError.set(null);
  clearDispatchUiStaleTimer();
  logBuffer = [];
  if (logFlushTimer !== null) {
    clearTimeout(logFlushTimer);
    logFlushTimer = null;
  }
  sseQueue = [];
  if (sseFlushTimer !== null) {
    clearTimeout(sseFlushTimer);
    sseFlushTimer = null;
  }
  if (recoveryPulseTimer !== null) {
    clearTimeout(recoveryPulseTimer);
    recoveryPulseTimer = null;
  }
  pendingRecoveryPulse = null;
  lastRecoveryPulseAppliedAt = 0;
}

function detachWorkspaceListeners(): void {
  activityUnsub?.();
  activityUnsub = null;
  roleLogUnsub?.();
  roleLogUnsub = null;
  if (recoveryLoadTimer !== null) {
    clearTimeout(recoveryLoadTimer);
    recoveryLoadTimer = null;
  }
  wsResetTransient();
}

export function wsBind(projectId: string, extraKeys: string[] = []): void {
  if (boundProjectId === projectId && activityUnsub) return;
  detachWorkspaceListeners();
  boundProjectId = projectId;
  projectMatchKeys = new Set([projectId, ...extraKeys.filter(Boolean)]);
  workspaceActivityReady = false;
  let skipActivityReplay = true;
  activityUnsub = decisionActivity.subscribe((ev) => {
    if (skipActivityReplay) {
      skipActivityReplay = false;
      return;
    }
    if (!ev) return;
    queueMicrotask(() => queueActivityEvent(ev));
  });
  let skipLogReplay = true;
  roleLogUnsub = decisionRoleLogBatch.subscribe((batch) => {
    if (skipLogReplay) {
      skipLogReplay = false;
      return;
    }
    queueMicrotask(() => handleRoleLogBatch(batch));
  });
  if (get(wsRecovery)) workspaceActivityReady = true;
}

export function wsUnbind(): void {
  detachWorkspaceListeners();
  boundProjectId = null;
  projectMatchKeys = new Set();
  recoveryLoadGeneration += 1;
  recoveryLoadPromise = null;
  recoveryLoadPending = false;
  workspaceActivityReady = false;
  wsRecoveryLoading.set(false);
}

export function wsAppendTerminal(line: TerminalLine): void {
  appendTerminal(line);
}

export async function wsLoadTerminal(projectId: string): Promise<void> {
  if (!projectId) return;
  try {
    const res = await api.get<{ lines?: TerminalLine[] }>(
      `/api/v2/projects/${projectId}/activity/terminal?limit=120`
    );
    if (res.lines) {
      wsTerminal.set(res.lines.slice(-120));
    }
  } catch {
    /* best-effort */
  }
}

function applyRecoveryResponse(
  projectId: string,
  gen: number,
  res: RecoveryStatus & { ok?: boolean; code_review_blocked?: boolean; code_files_count?: number }
): void {
  if (gen !== recoveryLoadGeneration) return;
  if (boundProjectId != null && boundProjectId !== projectId) return;
  // Boot GET /recovery is tiny; apply synchronously so workspaceReady can mount controls immediately.
  wsRecovery.set({
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
    code_review_blocked: res.code_review_blocked,
    current_phase: res.current_phase,
  });

  if (typeof res.current_phase === 'string') {
    metadataPatchHandler?.({}, res.current_phase);
  }

  const inflight = res.dispatch_in_flight ?? null;
  const busy = get(wsRecoveryBusy);
  if (!dispatchInFlightActive({ dispatch_in_flight: inflight } as RecoveryStatus) && !busy) {
    wsRunState.update((s) => ({
      ...s,
      activeRole: null,
      activeRoleStartedAt: null,
      activeRoleMessage: null,
      recoveryStarted: null,
    }));
  }
  if (!busy) wsRecoveryError.set(null);
  workspaceActivityReady = true;
}

export async function wsLoadRecoveryNow(projectId: string): Promise<void> {
  if (!projectId) return;
  if (recoveryLoadPromise) return recoveryLoadPromise;

  const gen = recoveryLoadGeneration;
  wsRecoveryLoading.set(true);

  recoveryLoadPromise = (async () => {
    try {
      const res = await api.get<
        RecoveryStatus & { ok?: boolean; code_review_blocked?: boolean; code_files_count?: number }
      >(`/api/v2/projects/${projectId}/recovery`, { timeoutMs: RECOVERY_FETCH_TIMEOUT_MS });
      applyRecoveryResponse(projectId, gen, res);
    } catch (e) {
      if (gen !== recoveryLoadGeneration) return;
      const msg = (e as Error).message || 'failed to load recovery status';
      const busy = get(wsRecoveryBusy);
      const started = get(wsRunState).recoveryStarted;
      if (!busy && !started) wsRecoveryError.set(msg);
      workspaceActivityReady = true;
    } finally {
      if (gen === recoveryLoadGeneration) {
        wsRecoveryLoading.set(false);
      }
      const pending = recoveryLoadPending;
      recoveryLoadPending = false;
      recoveryLoadPromise = null;
      // Never await a follow-up load here — SSE can set recoveryLoadPending repeatedly
      // and would keep the caller's promise open forever (workspace boot hang).
      if (pending) {
        void wsLoadRecoveryNow(projectId);
      }
    }
  })();

  return recoveryLoadPromise;
}

/** Block until GET /recovery data is in wsRecovery (or error/timeout) before mounting pipeline UI. */
export async function wsWaitForRecoverySnapshot(
  projectId: string,
  timeoutMs = 5000
): Promise<void> {
  if (!projectId) return;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (boundProjectId != null && boundProjectId !== projectId) return;
    const recovery = get(wsRecovery);
    if ((recovery?.actions?.length ?? 0) > 0) return;
    if (recovery != null && !get(wsRecoveryLoading)) return;
    if (get(wsRecoveryError)) return;
    await yieldMainThread();
    await flushFrameCommitsForBoot();
  }
}

export function scheduleLoadRecovery(
  projectId: string,
  immediate = false,
  force = false
): void {
  if (!projectId) return;
  if (recoveryLoadPromise) {
    recoveryLoadPending = true;
    return;
  }
  if (recoveryLoadPending) return;
  const lastPulse = get(wsLastRecoveryPulseAt);
  if (!force && sseLiveConnected && lastPulse > 0) {
    const age = Date.now() - lastPulse;
    if (age < (immediate ? 8_000 : 45_000)) return;
  }
  if (immediate) {
    if (recoveryLoadTimer !== null) {
      clearTimeout(recoveryLoadTimer);
      recoveryLoadTimer = null;
    }
    void wsLoadRecoveryNow(projectId);
    return;
  }
  if (recoveryLoadTimer !== null) return;
  recoveryLoadTimer = setTimeout(() => {
    recoveryLoadTimer = null;
    void wsLoadRecoveryNow(projectId);
  }, 750);
}

export function wsDispatchRecovery(
  projectId: string,
  action: string,
  note: string | undefined,
  onSelectPipelineTab: () => void
): void {
  if (get(wsRecoveryBusy) || !projectId) return;

  const run = () => {
    const actionInfo = recoveryActionInfo(action);
    const role = actionInfo?.role ?? 'engineer';

    wsRecoveryBusy.set(true);
    wsRecoveryError.set(null);
    wsRunState.update((s) => ({
      ...s,
      lastDispatchedAction: action,
      lastDispatchAt: Date.now(),
      recoveryStarted: PIPELINE_COPY.dispatch.queued(actionInfo?.label ?? 'Pipeline step'),
      activeRole: role,
      activeRoleStartedAt: Date.now(),
      activeRoleMessage: actionInfo?.steps?.[0] ?? null,
    }));

    appendTerminal({
      formatted: PIPELINE_COPY.dispatch.terminalQueued(actionInfo?.label ?? action),
      level: 'info',
      ts: Date.now() / 1000,
    });

    onSelectPipelineTab();
    armDispatchUiStaleTimer();

    void (async () => {
      try {
        const res = await api.post<{ message?: string }>(
          `/api/v2/projects/${projectId}/recovery/dispatch`,
          { action, note: note?.trim() || undefined }
        );
        await yieldMainThread();
        wsRunState.update((s) => ({
          ...s,
          recoveryStarted:
            res.message ??
            PIPELINE_COPY.dispatch.queued(actionInfo?.label ?? 'Pipeline step'),
        }));
        scheduleLoadRecovery(projectId, true, true);
        setTimeout(() => void wsLoadTerminal(projectId), 300);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const nested =
            typeof e.detail === 'object' && e.detail && 'details' in e.detail
              ? (e.detail.details as { dispatch_in_flight?: RecoveryStatus['dispatch_in_flight'] })
              : (e.detail as { dispatch_in_flight?: RecoveryStatus['dispatch_in_flight'] });
          const inflight = nested?.dispatch_in_flight;
          if (inflight) {
            wsRecovery.update((r) => (r ? { ...r, dispatch_in_flight: inflight } : r));
          }
          wsRecoveryError.set(
            e.message ||
              'A pipeline step is already running. Watch the activity log or clear a stuck dispatch below.'
          );
          toasts.push({
            kind: 'info',
            message:
              e.message ||
              'A pipeline step is already running. Watch the activity log or clear a stuck dispatch below.',
            ttlMs: 6000,
          });
        } else {
          wsRecoveryError.set((e as Error).message || 'dispatch failed');
        }
        clearDispatchUiStaleTimer();
        wsRunState.update((s) => ({
          ...s,
          activeRole: null,
          activeRoleStartedAt: null,
          activeRoleMessage: null,
        }));
      } finally {
        wsRecoveryBusy.set(false);
      }
    })();
  };

  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(run);
  } else {
    run();
  }
}

export async function wsCancelInflight(projectId: string): Promise<void> {
  await api.post(`/api/v2/projects/${projectId}/recovery/cancel-inflight`, {});
  wsRunState.update((s) => ({
    ...s,
    activeRole: null,
    activeRoleStartedAt: null,
    activeRoleMessage: null,
    recoveryStarted: null,
  }));
  scheduleLoadRecovery(projectId, true, true);
}

/** Vitest seam — exercise SSE queue batching without a live stream. */
export function __testQueueActivityEvent(ev: DecisionActivityEvent): void {
  queueActivityEvent(ev);
}

export function __testSetWorkspaceActivityReady(ready: boolean): void {
  workspaceActivityReady = ready;
}

/** Vitest seam — apply GET /recovery payload after wsBind. */
export function __testApplyRecoveryResponse(
  projectId: string,
  res: RecoveryStatus & { ok?: boolean; code_review_blocked?: boolean; code_files_count?: number }
): void {
  applyRecoveryResponse(projectId, recoveryLoadGeneration, res);
}
