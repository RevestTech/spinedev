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

const initial: DecisionStoreState = {
  items: [],
  loading: false,
  error: null,
  liveConnected: false
};

const state = writable<DecisionStoreState>(initial);
let sseHandle: SseSubscription | null = null;
/** Bumped on disconnect so stale reconnect timers no-op. */
let connectGeneration = 0;

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
      const res = await api.get<DecisionList>(`/api/v2/decisions?status=${statusFilter}&scope=project`);
      state.update((s) => ({ ...s, items: res.items, loading: false }));
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
          if (!evt?.card) return;
          const card = evt.card;
          if (isHubInboxCard(card)) {
            if (card.status === 'pending') hubInbox.upsert(card);
            else hubInbox.remove(card.decision_id);
            return;
          }
          state.update((s) => {
            const next = s.items.filter((c) => c.decision_id !== card.decision_id);
            if (card.status === 'pending') next.unshift(card);
            return { ...s, items: next };
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
    state.update((s) => ({ ...s, liveConnected: false }));
  },
  async ack(id: string): Promise<DecisionActionResponse> {
    const path = `/api/v2/decisions/${encodeURIComponent(id)}/ack`;
    try {
      const res = await api.post<DecisionActionResponse>(path, {});
      state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
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
      return res;
    } catch (err) {
      await decisions.load('pending');
      throw err;
    }
  },
  /** Test seam: replace the items array directly. */
  __setItems(items: DecisionCard[]): void {
    state.update((s) => ({ ...s, items }));
  }
};

export const pendingCount = derived(state, ($s) => $s.items.length);

export function snapshot(): DecisionStoreState {
  return get(state);
}
