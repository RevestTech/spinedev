/** Tests for the projectEvents Svelte store. */
import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import {
  connect,
  disconnect,
  MAX_EVENTS,
  projectEventList,
  projectEventsOf,
  snapshot,
} from '$lib/stores/projectEvents';
import type { ProjectEvent } from '$lib/stores/projectEvents';

/** Minimal EventSource fake — captures listeners + lets tests inject data. */
class FakeEventSource {
  url: string;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  private listeners = new Map<string, EventListener[]>();
  closed = false;

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, handler: EventListener): void {
    const list = this.listeners.get(type) ?? [];
    list.push(handler);
    this.listeners.set(type, list);
  }

  /** Simulate an SSE event of a typed kind. */
  emit(type: string, data: unknown): void {
    const evt = new MessageEvent(type, { data: JSON.stringify(data) });
    const list = this.listeners.get(type) ?? [];
    for (const handler of list) {
      handler(evt);
    }
  }

  close(): void {
    this.closed = true;
  }
}

function buildEvent(overrides: Partial<ProjectEvent> = {}): ProjectEvent {
  return {
    event_id: '00000000-0000-0000-0000-000000000000',
    event_type: 'ledger_append',
    project_id: 'proj-test',
    occurred_at: '2026-05-30T12:00:00+00:00',
    actor: 'conductor',
    verdict: 'allowed',
    citation_count: 0,
    summary: 'test',
    payload: {},
    ...overrides,
  };
}

afterEach(() => {
  disconnect();
});

describe('projectEvents store', () => {
  it('starts idle', () => {
    const state = snapshot();
    expect(state.status).toBe('idle');
    expect(state.projectId).toBe(null);
    expect(state.events).toEqual([]);
  });

  it('opens an SSE connection and transitions to open', () => {
    let fake: FakeEventSource | null = null;
    connect('proj-1', (url) => {
      fake = new FakeEventSource(url);
      return fake as unknown as EventSource;
    });

    expect(snapshot().status).toBe('connecting');
    expect(snapshot().projectId).toBe('proj-1');

    fake!.onopen?.(new Event('open'));
    expect(snapshot().status).toBe('open');
  });

  it('buffers received events newest-first', () => {
    let fake: FakeEventSource | null = null;
    connect('proj-2', (url) => {
      fake = new FakeEventSource(url);
      return fake as unknown as EventSource;
    });

    fake!.emit('ledger_append', buildEvent({ summary: 'one' }));
    fake!.emit('auditor_refusal', buildEvent({
      event_type: 'auditor_refusal',
      summary: 'two',
    }));

    const events = get(projectEventList);
    expect(events).toHaveLength(2);
    expect(events[0].summary).toBe('two'); // newest first
    expect(events[1].summary).toBe('one');
  });

  it('filters with projectEventsOf', () => {
    let fake: FakeEventSource | null = null;
    connect('proj-3', (url) => {
      fake = new FakeEventSource(url);
      return fake as unknown as EventSource;
    });

    fake!.emit('ledger_append', buildEvent({ summary: 'ledger-1' }));
    fake!.emit('audit_event', buildEvent({
      event_type: 'audit_event',
      summary: 'audit-1',
    }));
    fake!.emit('ledger_append', buildEvent({ summary: 'ledger-2' }));

    const ledger = get(projectEventsOf('ledger_append'));
    expect(ledger.map((e) => e.summary)).toEqual(['ledger-2', 'ledger-1']);

    const audit = get(projectEventsOf('audit_event'));
    expect(audit.map((e) => e.summary)).toEqual(['audit-1']);
  });

  it('caps the buffer at MAX_EVENTS', () => {
    let fake: FakeEventSource | null = null;
    connect('proj-cap', (url) => {
      fake = new FakeEventSource(url);
      return fake as unknown as EventSource;
    });

    for (let i = 0; i < MAX_EVENTS + 50; i++) {
      fake!.emit('ledger_append', buildEvent({ summary: String(i) }));
    }
    const events = get(projectEventList);
    expect(events.length).toBe(MAX_EVENTS);
    // The newest event (MAX_EVENTS + 49) is at the head.
    expect(events[0].summary).toBe(String(MAX_EVENTS + 49));
    // The oldest event still in the buffer is event 50 (events
    // 0..49 should have rolled off).
    expect(events[events.length - 1].summary).toBe('50');
  });

  it('closes the previous stream when reconnecting to a different project', () => {
    const fakes: FakeEventSource[] = [];
    const factory = (url: string) => {
      const f = new FakeEventSource(url);
      fakes.push(f);
      return f as unknown as EventSource;
    };

    connect('proj-A', factory);
    connect('proj-B', factory);

    expect(fakes).toHaveLength(2);
    expect(fakes[0].closed).toBe(true);
    expect(snapshot().projectId).toBe('proj-B');
  });

  it('is idempotent for repeated connect calls to the same project', () => {
    const fakes: FakeEventSource[] = [];
    const factory = (url: string) => {
      const f = new FakeEventSource(url);
      fakes.push(f);
      return f as unknown as EventSource;
    };

    connect('proj-X', factory);
    connect('proj-X', factory);

    expect(fakes).toHaveLength(1);
  });
});
