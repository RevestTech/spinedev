/** Tests for LedgerTimeline.svelte (Path A T15). */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import LedgerTimeline from '$lib/components/LedgerTimeline.svelte';
import {
  disconnect,
  type ProjectEvent,
} from '$lib/stores/projectEvents';

class FakeEventSource {
  url: string;
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
    for (const handler of list) handler(evt);
  }
  close(): void {}
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
}

function buildEvent(overrides: Partial<ProjectEvent> = {}): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'ledger_append',
    project_id: 'proj-ledger',
    occurred_at: new Date().toISOString(),
    actor: 'conductor',
    verdict: 'allowed',
    citation_count: 0,
    summary: 'ledger row',
    payload: {
      promotion_tier: 'internal',
      promotion_reasons: [],
      content_hash: 'h1',
      prev_hash: null,
      candidate_ids: ['conductor:rollout-0'],
    },
    ...overrides,
  };
}

let fakeSource: FakeEventSource | null = null;

beforeEach(() => {
  fakeSource = null;
  (globalThis as unknown as { EventSource: typeof EventSource }).EventSource =
    function MockEventSource(url: string) {
      fakeSource = new FakeEventSource(url);
      return fakeSource as unknown as EventSource;
    } as unknown as typeof EventSource;
});

afterEach(() => {
  disconnect();
});

describe('LedgerTimeline', () => {
  it('renders empty state with chain ok badge by default', () => {
    const { getByTestId } = render(LedgerTimeline, {
      props: { projectId: 'proj-empty' },
    });
    expect(getByTestId('empty').textContent).toMatch(/No ledger entries/i);
    expect(getByTestId('chain-badge').textContent).toMatch(/chain ok/i);
  });

  it('renders one row per ledger_append event with verdict tone', async () => {
    const { container } = render(LedgerTimeline, {
      props: { projectId: 'proj-rows' },
    });
    fakeSource!.emit(
      'ledger_append',
      buildEvent({ verdict: 'allowed', summary: 'allowed-1' }),
    );
    fakeSource!.emit(
      'ledger_append',
      buildEvent({
        verdict: 'denied',
        summary: 'denied-1',
        payload: {
          promotion_tier: 'production',
          promotion_reasons: ['freshness_stale', 'replay_failed'],
          content_hash: 'h2',
          prev_hash: 'h1',
          candidate_ids: ['auditor:refusal'],
        },
      }),
    );
    await new Promise((r) => setTimeout(r, 5));

    const rows = container.querySelectorAll('[data-testid="ledger-row"]');
    expect(rows).toHaveLength(2);
    // Denied row should carry its reasons.
    const deniedRow = container.querySelector(
      '[data-testid="ledger-row"][data-verdict="denied"]',
    );
    expect(deniedRow?.textContent).toMatch(/freshness_stale/);
    expect(deniedRow?.textContent).toMatch(/replay_failed/);
  });

  it('filters by tier', async () => {
    const { container, getByTestId } = render(LedgerTimeline, {
      props: { projectId: 'proj-tier' },
    });
    fakeSource!.emit(
      'ledger_append',
      buildEvent({ summary: 'internal-row', payload: { promotion_tier: 'internal' } }),
    );
    fakeSource!.emit(
      'ledger_append',
      buildEvent({ summary: 'production-row', payload: { promotion_tier: 'production' } }),
    );
    await new Promise((r) => setTimeout(r, 5));
    expect(container.querySelectorAll('[data-testid="ledger-row"]')).toHaveLength(2);

    const sel = getByTestId('tier-filter') as HTMLSelectElement;
    await fireEvent.change(sel, { target: { value: 'production' } });
    await new Promise((r) => setTimeout(r, 5));

    const rows = container.querySelectorAll('[data-testid="ledger-row"]');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toMatch(/production-row/);
  });

  it('enables CSV export only when there is at least one row', async () => {
    const { container, getByTestId } = render(LedgerTimeline, {
      props: { projectId: 'proj-csv' },
    });
    expect((getByTestId('export-csv') as HTMLButtonElement).disabled).toBe(true);

    fakeSource!.emit('ledger_append', buildEvent());
    await new Promise((r) => setTimeout(r, 5));
    expect((getByTestId('export-csv') as HTMLButtonElement).disabled).toBe(false);
  });
});
