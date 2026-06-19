// Spine Hub SPA — decision-queue store (V3 Wave 3 part 2, Squad SPA1).
//
// Owns the in-memory list + SSE subscription handle so multiple panels
// (decision-queue page + status footer chip) stay in sync without each
// opening its own /api/v2/decisions/subscribe stream.

import { derived, writable, get } from 'svelte/store';
import {
  api,
  subscribeSse,
  isAbortError,
  apiErrorMessage,
  type SseSubscription
} from '$lib/api/client';
import { scheduleFrameCommit } from '$lib/uiFrameScheduler';
import { isHubInboxCard } from '$lib/decisionScope';
import { hubInbox } from '$lib/stores/hubInbox';
import type {
  DecisionCard,
  DecisionList,
  DecisionActionResponse,
  DecisionSseEvent,
  DecisionStatus
} from '$lib/api/types';

interface DecisionStoreState {
  items: DecisionCard[];
  loading: boolean;
  error: string | null;
  liveConnected: boolean;
}

/** Non-card SSE payloads (role_log, role_started, …) for project workspace feeds. */
export type DecisionActivityEvent = DecisionSseEvent & {
  type: string;
  project_uuid?: string;
  role?: string;
  message?: string;
  ts?: number;
  artifact_chars?: number;
  files_written?: number;
  install_ok?: boolean;
  error?: string;
  formatted?: string;
  refresh_artifacts?: boolean;
  dispatch_in_flight?: boolean;
  dispatch_kind?: string;
  current_phase?: string;
  /** recovery_pulse — SSE push of GET /recovery fields */
  stuck?: boolean;
  reasons?: string[];
  pending_decisions?: number;
  recommended_action?: string | null;
  last_role_failure?: { role?: string; error?: string; retry_action?: string } | null;
  actions?: { action: string; label: string; description: string }[];
  code_fix_iteration?: number;
  max_code_fix_iterations?: number;
  fix_loop_exhausted?: boolean;
  workspace_files_on_disk?: number;
  code_review_blocked?: boolean;
  code_files_count?: number;
};

const initial: DecisionStoreState = {
  items: [],
  loading: false,
  error: null,
  liveConnected: false
};

const state = writable<DecisionStoreState>(initial);
const activity = writable<DecisionActivityEvent | null>(null);
/** Batched role_log lines — avoids one activity.set per stdout line during engineer runs. */
const roleLogBatch = writable<DecisionActivityEvent[]>([]);
const bodyCache = writable<Record<string, string>>({});
let sseHandle: SseSubscription | null = null;
/** Bumped on disconnect so stale reconnect timers no-op. */
let connectGeneration = 0;

const ROLE_LOG_BATCH_MS = 250;
const ROLE_LOG_BATCH_MAX = 20;
const ROLE_LOG_BUFFER_CAP = 400;
let pendingRoleLogs: DecisionActivityEvent[] = [];
let roleLogFlushTimer: ReturnType<typeof setTimeout> | null = null;

function flushRoleLogBatch(): void {
  roleLogFlushTimer = null;
  if (pendingRoleLogs.length === 0) return;
  const batch = pendingRoleLogs.splice(0, ROLE_LOG_BATCH_MAX);
  roleLogBatch.set(batch);
  if (pendingRoleLogs.length > 0) {
    roleLogFlushTimer = setTimeout(flushRoleLogBatch, ROLE_LOG_BATCH_MS);
  }
}

function enqueueRoleLog(evt: DecisionActivityEvent): void {
  pendingRoleLogs.push(evt);
  if (pendingRoleLogs.length > ROLE_LOG_BUFFER_CAP) {
    pendingRoleLogs.splice(0, pendingRoleLogs.length - ROLE_LOG_BUFFER_CAP);
  }
  if (roleLogFlushTimer === null) {
    roleLogFlushTimer = setTimeout(flushRoleLogBatch, ROLE_LOG_BATCH_MS);
  }
}

function emitActivity(evt: DecisionActivityEvent): void {
  if (evt.type === 'role_log') {
    enqueueRoleLog(evt);
    return;
  }
  scheduleFrameCommit(() => activity.set(evt));
}

function scheduleReconnect(generation: number): void {
  window.setTimeout(() => {
    if (generation !== connectGeneration) return;
    decisions.connect();
  }, 3000);
}

function handleSseDrop(generation: number, err?: unknown): void {
  if (generation !== connectGeneration) return;
  sseHandle = null;
  state.update((s) => ({
    ...s,
    liveConnected: false,
    error: err
      ? apiErrorMessage(err, 'sse disconnected')
      : s.error
  }));
  scheduleReconnect(generation);
}

export const decisions = {
  subscribe: state.subscribe,
  /** Initial GET of the queue. */
  async load(statusFilter: DecisionStatus = 'pending'): Promise<void> {
    state.update((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await api.get<DecisionList>(
        `/api/v2/decisions?status=${statusFilter}&scope=project&include_body=false`
      );
      state.update((s) => ({ ...s, items: res.items ?? [], loading: false }));
    } catch (err) {
      state.update((s) => ({
        ...s,
        loading: false,
        error: apiErrorMessage(err, 'failed to load decisions')
      }));
    }
  },
  /** Subscribe to the live stream (idempotent). */
  connect(): void {
    if (sseHandle) return;
    const generation = connectGeneration;
    sseHandle = subscribeSse<DecisionSseEvent>(
      '/api/v2/decisions/subscribe',
      {
        onOpen: () => state.update((s) => ({ ...s, liveConnected: true, error: null })),
        onClose: () => handleSseDrop(generation),
        onError: (err) => {
          if (isAbortError(err)) return;
          handleSseDrop(generation, err);
        },
        onEvent: ({ data }) => {
          const evt = data as DecisionSseEvent;
          if (!evt?.type) return;
          emitActivity(evt as DecisionActivityEvent);
          if (!evt.card) return;
          const card = evt.card;
          if (isHubInboxCard(card)) {
            scheduleFrameCommit(() => {
              if (card.status === 'pending') hubInbox.upsert(card);
              else hubInbox.remove(card.decision_id);
            });
            return;
          }
          scheduleFrameCommit(() => {
            state.update((s) => {
              const next = s.items.filter((c) => c.decision_id !== card.decision_id);
              if (card.status === 'pending') next.unshift(card);
              return { ...s, items: next };
            });
          });
        }
      },
      { body: {} }
    );
  },
  /** Tear down the live stream — call on component unmount. */
  disconnect(): void {
    connectGeneration += 1;
    sseHandle?.close();
    sseHandle = null;
    pendingRoleLogs = [];
    if (roleLogFlushTimer !== null) {
      clearTimeout(roleLogFlushTimer);
      roleLogFlushTimer = null;
    }
    roleLogBatch.set([]);
    state.update((s) => ({ ...s, liveConnected: false }));
  },
  async ack(id: string): Promise<DecisionActionResponse> {
    const path = `/api/v2/decisions/${encodeURIComponent(id)}/ack`;
    try {
      const res = await api.post<DecisionActionResponse>(path, {});
      state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
      bodyCache.update((c) => {
        const next = { ...c };
        delete next[id];
        return next;
      });
      return res;
    } catch (err) {
      await decisions.load('pending');
      throw err;
    }
  },
  async reject(id: string): Promise<DecisionActionResponse> {
    const path = `/api/v2/decisions/${encodeURIComponent(id)}/reject`;
    try {
      const res = await api.post<DecisionActionResponse>(path, {});
      state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
      bodyCache.update((c) => {
        const next = { ...c };
        delete next[id];
        return next;
      });
      return res;
    } catch (err) {
      await decisions.load('pending');
      throw err;
    }
  },
  /** Fetch full card body on demand (list/SSE omit bodies for performance). */
  async fetchBody(id: string): Promise<string> {
    const cached = get(bodyCache)[id];
    if (cached !== undefined) return cached;
    const card = await api.get<DecisionCard>(`/api/v2/decisions/${encodeURIComponent(id)}`);
    const body = card.body || '';
    bodyCache.update((c) => ({ ...c, [id]: body }));
    state.update((s) => ({
      ...s,
      items: s.items.map((c) => (c.decision_id === id ? { ...c, body } : c))
    }));
    return body;
  },
  /** Test seam: replace the items array directly. */
  __setItems(items: DecisionCard[]): void {
    state.update((s) => ({ ...s, items }));
  }
};

export const pendingCount = derived(state, ($s) => $s.items.length);

/** Live role / terminal events from the shared layout SSE connection. */
export const decisionActivity = {
  subscribe: activity.subscribe
};

/** Batched stdout/stderr lines (see emitActivity role_log path). */
export const decisionRoleLogBatch = {
  subscribe: roleLogBatch.subscribe
};

export function snapshot(): DecisionStoreState {
  return get(state);
}
