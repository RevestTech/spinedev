/**
 * Realtime project event store (Path B T10).
 *
 * Subscribes to `/api/v2/projects/{id}/events` SSE; exposes the live
 * tail as a Svelte readable buffer + per-type filtered readables for
 * consumers that only care about ledger / audit / instinct / etc.
 *
 * Buffer is capped at MAX_EVENTS so a long-lived workspace doesn't
 * grow unbounded in memory.
 */
import { derived, get, writable } from 'svelte/store';
import type { Readable, Writable } from 'svelte/store';

/** Closed set mirroring shared/api/realtime/event_schema.py. */
export type ProjectEventType =
  | 'ledger_append'
  | 'directive_complete'
  | 'instinct_recorded'
  | 'auditor_verdict'
  | 'auditor_refusal'
  | 'audit_event'
  | 'charter_eval_run'
  | 'operate_plane_status'
  | 'envelope_warning';

export interface ProjectEvent {
  event_id: string;
  event_type: ProjectEventType;
  project_id: string;
  occurred_at: string;
  actor: string;
  verdict: string | null;
  citation_count: number;
  summary: string | null;
  payload: Record<string, unknown>;
}

/** Newest-first cap. Anything older rolls off. */
export const MAX_EVENTS = 200;

interface StoreState {
  events: ProjectEvent[];
  /** Connection state — used by the component to render a status pip. */
  status: 'idle' | 'connecting' | 'open' | 'closed' | 'error';
  /** Project the store is currently bound to; null when idle. */
  projectId: string | null;
}

const _initial: StoreState = {
  events: [],
  status: 'idle',
  projectId: null,
};

const _state: Writable<StoreState> = writable(_initial);

let _eventSource: EventSource | null = null;

/** Public read-only handle. */
export const projectEvents: Readable<StoreState> = {
  subscribe: _state.subscribe,
};

/** Derived: just the events array. */
export const projectEventList: Readable<ProjectEvent[]> = derived(
  _state,
  ($s) => $s.events,
);

/** Build a derived store filtered to one event type. */
export function projectEventsOf(
  type: ProjectEventType,
): Readable<ProjectEvent[]> {
  return derived(_state, ($s) => $s.events.filter((e) => e.event_type === type));
}

/** Snapshot for debugging / tests. */
export function snapshot(): StoreState {
  return get(_state);
}

/** Reset to initial state (test helper). */
export function reset(): void {
  if (_eventSource) {
    try {
      _eventSource.close();
    } catch {
      /* swallow */
    }
    _eventSource = null;
  }
  _state.set({ ..._initial });
}

/**
 * Open an SSE connection for ``projectId``. Idempotent — calling
 * again with the same id is a no-op; calling with a different id
 * closes the previous stream first.
 *
 * ``factory`` lets tests inject a fake EventSource implementation.
 */
export function connect(
  projectId: string,
  factory: (url: string) => EventSource = (url) => new EventSource(url),
): void {
  const current = get(_state);
  if (current.projectId === projectId && _eventSource) {
    return;
  }
  if (_eventSource) {
    try {
      _eventSource.close();
    } catch {
      /* swallow */
    }
    _eventSource = null;
  }

  const url = `/api/v2/projects/${encodeURIComponent(projectId)}/events`;
  _state.set({ events: [], status: 'connecting', projectId });

  const es = factory(url);
  _eventSource = es;

  es.onopen = () => {
    _state.update((s) => ({ ...s, status: 'open' }));
  };
  es.onerror = () => {
    _state.update((s) => ({ ...s, status: 'error' }));
  };

  // The server emits typed events; rather than registering nine
  // separate listeners, we register one per known type so the
  // EventSource impl routes the right .data through.
  const types: ProjectEventType[] = [
    'ledger_append',
    'directive_complete',
    'instinct_recorded',
    'auditor_verdict',
    'auditor_refusal',
    'audit_event',
    'charter_eval_run',
    'operate_plane_status',
    'envelope_warning',
  ];
  const handler = (evt: MessageEvent) => {
    try {
      const data = JSON.parse(evt.data) as ProjectEvent;
      _state.update((s) => {
        const next = [data, ...s.events];
        if (next.length > MAX_EVENTS) {
          next.length = MAX_EVENTS;
        }
        return { ...s, events: next };
      });
    } catch {
      // ignore malformed payload — server should never emit invalid
      // json, but be defensive
    }
  };
  for (const type of types) {
    es.addEventListener(type, handler as EventListener);
  }
}

/** Close the SSE stream and clear the store. */
export function disconnect(): void {
  reset();
}
