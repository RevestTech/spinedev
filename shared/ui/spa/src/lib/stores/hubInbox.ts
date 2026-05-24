// Hub message center — master briefings + portfolio notices (not project approvals).

import { derived, writable, get } from 'svelte/store';
import { api } from '$lib/api/client';
import type {
  DecisionCard,
  DecisionList,
  DecisionActionResponse,
  DecisionStatus
} from '$lib/api/types';

interface HubInboxState {
  items: DecisionCard[];
  loading: boolean;
  error: string | null;
}

const initial: HubInboxState = {
  items: [],
  loading: false,
  error: null
};

const state = writable<HubInboxState>(initial);

export const hubInbox = {
  subscribe: state.subscribe,
  async load(statusFilter: DecisionStatus = 'pending'): Promise<void> {
    state.update((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await api.get<DecisionList>(`/api/v2/hub/inbox?status=${statusFilter}`);
      state.update((s) => ({ ...s, items: res.items, loading: false }));
    } catch (err) {
      state.update((s) => ({
        ...s,
        loading: false,
        error: (err as Error).message || 'failed to load hub inbox'
      }));
    }
  },
  upsert(card: DecisionCard): void {
    state.update((s) => {
      const next = s.items.filter((c) => c.decision_id !== card.decision_id);
      if (card.status === 'pending') next.unshift(card);
      return { ...s, items: next };
    });
  },
  remove(id: string): void {
    state.update((s) => ({ ...s, items: s.items.filter((c) => c.decision_id !== id) }));
  },
  async ack(id: string): Promise<DecisionActionResponse> {
    const path = `/api/v2/decisions/${encodeURIComponent(id)}/ack`;
    try {
      const res = await api.post<DecisionActionResponse>(path, {});
      hubInbox.remove(id);
      return res;
    } catch (err) {
      await hubInbox.load('pending');
      throw err;
    }
  },
  async reject(id: string): Promise<DecisionActionResponse> {
    const path = `/api/v2/decisions/${encodeURIComponent(id)}/reject`;
    try {
      const res = await api.post<DecisionActionResponse>(path, {});
      hubInbox.remove(id);
      return res;
    } catch (err) {
      await hubInbox.load('pending');
      throw err;
    }
  },
  __setItems(items: DecisionCard[]): void {
    state.update((s) => ({ ...s, items }));
  }
};

export const hubInboxCount = derived(state, ($s) => $s.items.length);

export function hubInboxSnapshot(): HubInboxState {
  return get(state);
}
