/** Tests for LiveLoopActivity.svelte (Path B T11). */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import LiveLoopActivity from '$lib/components/LiveLoopActivity.svelte';
import {
  connect,
  disconnect,
  type ProjectEvent,
} from '$lib/stores/projectEvents';

class FakeEventSource {
  url: string;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  private listeners = new Map<string, EventListener[]>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, handler: EventListener): void {
    const list = this.listeners.get(type) ?? [];
    list.push(handler);
    this.listeners.set(type, list);
  }

  emit(type: string, data: unknown): void {
    const evt = new MessageEvent(type, { data: JSON.stringify(data) });
    const list = this.listeners.get(type) ?? [];
    for (const handler of list) {
      handler(evt);
    }
  }

  close(): void {}
}

function buildEvent(overrides: Partial<ProjectEvent> = {}): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'ledger_append',
    project_id: 'proj-test',
    occurred_at: new Date().toISOString(),
    actor: 'conductor',
    verdict: 'allowed',
    citation_count: 0,
    summary: 'test event',
    payload: { key: 'value' },
    ...overrides,
  };
}

let fakeSource: FakeEventSource | null = null;

beforeEach(() => {
  fakeSource = null;
  // Patch the global EventSource ctor so the store + component use our fake.
  (globalThis as unknown as { EventSource: typeof EventSource }).EventSource =
    function MockEventSource(url: string) {
      fakeSource = new FakeEventSource(url);
      return fakeSource as unknown as EventSource;
    } as unknown as typeof EventSource;
});

afterEach(() => {
  disconnect();
});

describe('LiveLoopActivity', () => {
  it('renders empty state when no events have arrived', () => {
    const { getByText } = render(LiveLoopActivity, {
      props: { projectId: 'proj-empty' },
    });
    expect(getByText(/No live events yet/i)).toBeTruthy();
  });

  it('renders a row per event with correct badge label', async () => {
    const { container, getByText } = render(LiveLoopActivity, {
      props: { projectId: 'proj-rows' },
    });

    // The component mounts and triggers connect(); fakeSource is set.
    fakeSource!.emit(
      'ledger_append',
      buildEvent({ summary: 'ledger added', verdict: 'allowed' }),
    );
    fakeSource!.emit(
      'auditor_refusal',
      buildEvent({
        event_type: 'auditor_refusal',
        verdict: 'refusal',
        summary: 'auditor refused',
      }),
    );

    await new Promise((resolve) => setTimeout(resolve, 5));

    const rows = container.querySelectorAll('li[data-event-type]');
    expect(rows.length).toBe(2);
    expect(getByText(/auditor refused/)).toBeTruthy();
    expect(getByText(/ledger added/)).toBeTruthy();
  });

  it('toggles payload expansion on click', async () => {
    const { container } = render(LiveLoopActivity, {
      props: { projectId: 'proj-toggle' },
    });
    fakeSource!.emit(
      'ledger_append',
      buildEvent({ summary: 'toggle me', payload: { hello: 'world' } }),
    );
    await new Promise((resolve) => setTimeout(resolve, 5));

    const row = container.querySelector('li[data-event-type]') as HTMLElement;
    expect(row).toBeTruthy();

    expect(container.querySelector('[data-testid="expanded-payload"]')).toBe(
      null,
    );

    await fireEvent.click(row);
    await new Promise((resolve) => setTimeout(resolve, 5));
    const expanded = container.querySelector('[data-testid="expanded-payload"]');
    expect(expanded?.textContent).toMatch(/"hello": "world"/);

    await fireEvent.click(row);
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(container.querySelector('[data-testid="expanded-payload"]')).toBe(
      null,
    );
  });

  it('caps rows at the configured maximum', async () => {
    const { container } = render(LiveLoopActivity, {
      props: { projectId: 'proj-cap', maxRows: 3 },
    });

    for (let i = 0; i < 10; i++) {
      fakeSource!.emit(
        'ledger_append',
        buildEvent({ summary: `evt-${i}` }),
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 5));

    const rows = container.querySelectorAll('li[data-event-type]');
    expect(rows.length).toBe(3);
  });
});
