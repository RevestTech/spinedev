// Spine Hub SPA — decision-queue store (V3 Wave 3 part 2, Squad SPA1).
//
// Owns the in-memory list + SSE subscription handle so multiple panels
// (decision-queue page + status footer chip) stay in sync without each
// opening its own /api/v2/decisions/subscribe stream.

import { derived, writable, get } from 'svelte/store';
import { api, subscribeSse, type SseSubscription } from '$lib/api/client';
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

export const decisions = {
  subscribe: state.subscribe,
  /** Initial GET of the queue. */
  async load(statusFilter: DecisionStatus = 'pending'): Promise<void> {
    state.update((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await api.get<DecisionList>(`/api/v2/decisions?status=${statusFilter}`);
      state.update((s) => ({ ...s, items: res.items, loading: false }));
    } catch (err) {
      state.update((s) => ({
        ...s,
        loading: false,
        error: (err as Error).message || 'failed to load decisions'
      }));
    }
  },
  /** Subscribe to the live stream (idempotent). */
  connect(): void {
    if (sseHandle) return;
    sseHandle = subscribeSse<DecisionSseEvent>(
      '/api/v2/decisions/subscribe',
      {
        onOpen: () => state.update((s) => ({ ...s, liveConnected: true })),
        onError: (err) =>
          state.update((s) => ({
            ...s,
            liveConnected: false,
            error: (err as Error)?.message || 'sse disconnected'
          })),
        onEvent: ({ data }) => {
          const evt = data as DecisionSseEvent;
          if (!evt?.card) return;
          state.update((s) => {
            const next = s.items.filter((c) => c.decision_id !== evt.card!.decision_id);
            if (evt.card!.status === 'pending') next.unshift(evt.card!);
            return { ...s, items: next };
          });
        }
      },
      { body: {} }
    );
  },
  /** Tear down the live stream — call on component unmount. */
  disconnect(): void {
    sseHandle?.close();
    sseHandle = null;
    state.update((s) => ({ ...s, liveConnected: false }));
  },
  async ack(id: string): Promise<DecisionActionResponse> {
    const res = await api.post<DecisionActionResponse>(`/api/v2/decisions/${id}/ack`);
    state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
    return res;
  },
  async reject(id: string): Promise<DecisionActionResponse> {
    const res = await api.post<DecisionActionResponse>(`/api/v2/decisions/${id}/reject`);
    state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
    return res;
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
