/**
 * Isolated project workspace runtime — terminal stream, recovery state, and SSE
 * handling live here so the parent +page.svelte does not re-render on every
 * role_log line during long engineer / security runs.
 */

import { get, writable } from 'svelte/store';
import { api } from '$lib/api/client';
import { ApiError } from '$lib/api/types';
import type { TerminalLine } from '$lib/terminalLine';
import { PIPELINE_COPY, recoveryActionInfo } from '$lib/projectPipelineCopy';
import { toasts } from '$lib/stores/toasts';
import { yieldMainThread } from '$lib/yieldMainThread';
import {
  decisionActivity,
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
const SSE_BATCH_SIZE = 8;
const SSE_BATCH_MS = 150;
const LOG_FLUSH_MS = 200;

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
let sseQueue: DecisionActivityEvent[] = [];
let sseFlushTimer: ReturnType<typeof setTimeout> | null = null;
let logBuffer: TerminalLine[] = [];
let logFlushTimer: ReturnType<typeof setTimeout> | null = null;
let recoveryLoadTimer: ReturnType<typeof setTimeout> | null = null;
let recoveryLoadInFlight = false;
let recoveryLoadPending = false;
let dispatchUiStaleTimer: ReturnType<typeof setTimeout> | null = null;
let metadataPatchHandler: MetadataPatchHandler | null = null;
let artifactsRefreshHandler: ArtifactsRefreshHandler | null = null;
let sseLiveConnected = false;

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

function flushLogBuffer(): void {
  logFlushTimer = null;
  if (logBuffer.length === 0) return;
  const batch = logBuffer.splice(0);
  wsTerminal.update((lines) => [...lines, ...batch].slice(-TERMINAL_CAP));
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
  });

  const rec = get(wsRecovery);
  const busy = get(wsRecoveryBusy);
  if (!dispatchInFlightActive(rec) && !busy) {
    wsRunState.update((s) => ({
      ...s,
      activeRole: null,
      activeRoleStartedAt: null,
      activeRoleMessage: null,
      recoveryStarted: null,
    }));
    clearDispatchUiStaleTimer();
  }

  const patch: Record<string, unknown> = {};
  if (typeof ev.code_fix_iteration === 'number') patch.code_fix_iteration = ev.code_fix_iteration;
  if (typeof ev.code_review_blocked === 'boolean') patch.code_review_blocked = ev.code_review_blocked;
  if (typeof ev.code_files_count === 'number') patch.code_files_count = ev.code_files_count;
  if (Object.keys(patch).length > 0 || typeof ev.current_phase === 'string') {
    metadataPatchHandler?.(patch, typeof ev.current_phase === 'string' ? ev.current_phase : undefined);
  }

  wsRecoveryLoading.set(false);
  recoveryLoadInFlight = false;
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

  wsFeed.update((feed) => [...feed, ev].slice(-FEED_CAP));

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
    if (!matchesProject(ev.project_uuid)) return;
    applyRecoveryFromPulse(ev);
    return;
  }
  if (ev.type === 'project_pulse') {
    if (!matchesProject(ev.project_uuid)) return;
    handleProjectPulse(ev);
    return;
  }

  const evProject = (ev.project_uuid ??
    ev.card?.project_id ??
    ev.card?.metadata?.project_uuid) as string | undefined;
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
}

export function wsBind(projectId: string, extraKeys: string[] = []): void {
  if (boundProjectId === projectId && activityUnsub) return;
  wsUnbind();
  boundProjectId = projectId;
  projectMatchKeys = new Set([projectId, ...extraKeys.filter(Boolean)]);
  activityUnsub = decisionActivity.subscribe((ev) => {
    if (ev) queueActivityEvent(ev);
  });
}

export function wsUnbind(): void {
  boundProjectId = null;
  projectMatchKeys = new Set();
  activityUnsub?.();
  activityUnsub = null;
  if (recoveryLoadTimer !== null) {
    clearTimeout(recoveryLoadTimer);
    recoveryLoadTimer = null;
  }
  wsResetTransient();
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

export async function wsLoadRecoveryNow(projectId: string): Promise<void> {
  if (!projectId) return;
  if (recoveryLoadInFlight) {
    recoveryLoadPending = true;
    return;
  }
  recoveryLoadInFlight = true;
  wsRecoveryLoading.set(true);
  try {
    const res = await api.get<RecoveryStatus & { ok?: boolean; code_review_blocked?: boolean; code_files_count?: number }>(
      `/api/v2/projects/${projectId}/recovery`
    );
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
    });

    const patch: Record<string, unknown> = {};
    if (typeof res.code_fix_iteration === 'number') patch.code_fix_iteration = res.code_fix_iteration;
    if (typeof res.code_review_blocked === 'boolean') patch.code_review_blocked = res.code_review_blocked;
    if (typeof res.code_files_count === 'number') patch.code_files_count = res.code_files_count;
    if (Object.keys(patch).length > 0) metadataPatchHandler?.(patch);

    const rec = get(wsRecovery);
    const busy = get(wsRecoveryBusy);
    if (!dispatchInFlightActive(rec) && !busy) {
      wsRunState.update((s) => ({
        ...s,
        activeRole: null,
        activeRoleStartedAt: null,
        activeRoleMessage: null,
        recoveryStarted: null,
      }));
    }
    if (!busy) wsRecoveryError.set(null);
  } catch (e) {
    const msg = (e as Error).message || 'failed to load recovery status';
    const busy = get(wsRecoveryBusy);
    const started = get(wsRunState).recoveryStarted;
    if (!busy && !started) wsRecoveryError.set(msg);
  } finally {
    wsRecoveryLoading.set(false);
    recoveryLoadInFlight = false;
    if (recoveryLoadPending) {
      recoveryLoadPending = false;
      void wsLoadRecoveryNow(projectId);
    }
  }
}

export function scheduleLoadRecovery(
  projectId: string,
  immediate = false,
  force = false
): void {
  if (!projectId) return;
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
