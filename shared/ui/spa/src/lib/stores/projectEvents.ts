/**
 * Realtime project event store (Path B T10 — refactored 2026-05-30
 * after the user hit page-freezes from singleton SSE thrash).
 *
 * Subscribes to `/api/v2/projects/{id}/events` SSE. Supports **multiple
 * concurrent subscriptions** keyed by project id — when N components on
 * the same page subscribe to the same id, they share ONE EventSource via
 * refcount; subscriptions to different ids open separate streams in
 * parallel.
 *
 * Public API is structured around `subscribe(projectId)` returning a
 * scoped handle. The previous singleton `connect/disconnect/projectEventsOf`
 * surface is kept as thin wrappers for the existing component code paths
 * but operates on its own internal stream.
 */
import { derived, get, writable, type Readable, type Writable } from 'svelte/store';

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

/** Newest-first cap per stream. Anything older rolls off. */
export const MAX_EVENTS = 200;

/** Per-stream state record. */
interface StreamState {
  projectId: string;
  events: ProjectEvent[];
  status: 'idle' | 'connecting' | 'open' | 'closed' | 'error';
}

/** Internal record stored per project id (refcounted). */
interface StreamRecord {
  store: Writable<StreamState>;
  eventSource: EventSource;
  refCount: number;
}

const _streams = new Map<string, StreamRecord>();

const _EVENT_TYPES: ProjectEventType[] = [
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

/** Scoped handle returned by `subscribe(projectId)`. */
export interface ProjectStream {
  projectId: string;
  state: Readable<StreamState>;
  events: Readable<ProjectEvent[]>;
  eventsOf(type: ProjectEventType): Readable<ProjectEvent[]>;
  disconnect(): void;
}

function _openStream(
  projectId: string,
  factory: (url: string) => EventSource,
): StreamRecord {
  const initial: StreamState = {
    projectId,
    events: [],
    status: 'connecting',
  };
  const store: Writable<StreamState> = writable(initial);
  const url = `/api/v2/projects/${encodeURIComponent(projectId)}/events`;
  const es = factory(url);

  es.onopen = () => {
    store.update((s) => ({ ...s, status: 'open' }));
  };
  es.onerror = () => {
    store.update((s) => ({ ...s, status: 'error' }));
  };

  const handler = (evt: MessageEvent) => {
    try {
      const data = JSON.parse(evt.data) as ProjectEvent;
      store.update((s) => {
        const next = [data, ...s.events];
        if (next.length > MAX_EVENTS) {
          next.length = MAX_EVENTS;
        }
        return { ...s, events: next };
      });
    } catch {
      // ignore — server should never emit non-json
    }
  };
  for (const type of _EVENT_TYPES) {
    es.addEventListener(type, handler as EventListener);
  }

  return { store, eventSource: es, refCount: 0 };
}

/**
 * Subscribe to project events for ``projectId``. Returns a scoped
 * handle whose ``events`` / ``eventsOf(type)`` readables are filtered
 * to that project's stream only.
 *
 * Multiple subscribers to the SAME id share one EventSource via
 * refcount. Multiple subscribers to DIFFERENT ids open separate
 * concurrent streams.
 *
 * ``factory`` lets tests inject a fake EventSource.
 */
export function subscribe(
  projectId: string,
  factory: (url: string) => EventSource = (url) => new EventSource(url),
): ProjectStream {
  let record = _streams.get(projectId);
  if (!record) {
    record = _openStream(projectId, factory);
    _streams.set(projectId, record);
  }
  record.refCount += 1;
  const rec = record;

  const state: Readable<StreamState> = { subscribe: rec.store.subscribe };
  const events: Readable<ProjectEvent[]> = derived(
    rec.store,
    ($s) => $s.events,
  );
  const eventsOf = (type: ProjectEventType): Readable<ProjectEvent[]> =>
    derived(rec.store, ($s) =>
      $s.events.filter((e) => e.event_type === type),
    );

  let released = false;
  const disconnect = (): void => {
    if (released) return;
    released = true;
    const live = _streams.get(projectId);
    if (!live) return;
    live.refCount -= 1;
    if (live.refCount <= 0) {
      try {
        live.eventSource.close();
      } catch {
        /* swallow */
      }
      _streams.delete(projectId);
    }
  };

  return { projectId, state, events, eventsOf, disconnect };
}

/** Diagnostic — snapshot of open streams + their refcounts. */
export function snapshotStreams(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [pid, rec] of _streams) {
    out[pid] = rec.refCount;
  }
  return out;
}

/** Force-close every open stream. Test helper. */
export function resetAllStreams(): void {
  for (const [, rec] of _streams) {
    try {
      rec.eventSource.close();
    } catch {
      /* swallow */
    }
  }
  _streams.clear();
}

// ─── Backwards-compatible singleton wrappers ──────────────────────
//
// The original API used module-level `connect/disconnect/projectEventsOf`
// against a single hidden stream. New components migrating to the
// multi-stream model use `subscribe()` directly; the wrappers below let
// any leftover singleton callers keep working without page-breaking
// regressions.

let _singletonStream: ProjectStream | null = null;

export const projectEvents: Readable<StreamState> = {
  subscribe(run, invalidate) {
    if (!_singletonStream) {
      const idle: StreamState = {
        projectId: '',
        events: [],
        status: 'idle',
      };
      return writable(idle).subscribe(run, invalidate);
    }
    return _singletonStream.state.subscribe(run, invalidate);
  },
};

export const projectEventList: Readable<ProjectEvent[]> = {
  subscribe(run, invalidate) {
    if (!_singletonStream) {
      return writable<ProjectEvent[]>([]).subscribe(run, invalidate);
    }
    return _singletonStream.events.subscribe(run, invalidate);
  },
};

/** Filtered derived for a type — backwards-compat singleton wrapper. */
export function projectEventsOf(
  type: ProjectEventType,
): Readable<ProjectEvent[]> {
  return {
    subscribe(run, invalidate) {
      if (!_singletonStream) {
        return writable<ProjectEvent[]>([]).subscribe(run, invalidate);
      }
      return _singletonStream.eventsOf(type).subscribe(run, invalidate);
    },
  };
}

export function snapshot(): StreamState {
  if (!_singletonStream) {
    return { projectId: '', events: [], status: 'idle' };
  }
  return get(_singletonStream.state);
}

export function reset(): void {
  if (_singletonStream) {
    _singletonStream.disconnect();
    _singletonStream = null;
  }
}

export function connect(
  projectId: string,
  factory: (url: string) => EventSource = (url) => new EventSource(url),
): void {
  if (_singletonStream && _singletonStream.projectId === projectId) {
    return;
  }
  if (_singletonStream) {
    _singletonStream.disconnect();
    _singletonStream = null;
  }
  _singletonStream = subscribe(projectId, factory);
}

export function disconnect(): void {
  reset();
}
