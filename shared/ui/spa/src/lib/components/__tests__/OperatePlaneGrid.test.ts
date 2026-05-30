/** Tests for OperatePlaneGrid.svelte (Path A T21). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import OperatePlaneGrid from '$lib/components/OperatePlaneGrid.svelte';
import { disconnect, type ProjectEvent } from '$lib/stores/projectEvents';

class FakeES {
  url: string;
  private l = new Map<string, EventListener[]>();
  constructor(url: string) {
    this.url = url;
  }
  addEventListener(t: string, h: EventListener) {
    const a = this.l.get(t) ?? [];
    a.push(h);
    this.l.set(t, a);
  }
  emit(t: string, d: unknown) {
    const e = new MessageEvent(t, { data: JSON.stringify(d) });
    for (const h of this.l.get(t) ?? []) h(e);
  }
  close() {}
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
}

function evt(
  plane: string,
  status: string,
  occurredAt: string,
  overrides: Partial<ProjectEvent> = {},
): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'operate_plane_status',
    project_id: 'proj-op',
    occurred_at: occurredAt,
    actor: 'operate',
    verdict: status,
    citation_count: 0,
    summary: `operate: ${plane} → ${status}`,
    payload: { plane, status },
    ...overrides,
  };
}

let fake: FakeES | null = null;

beforeEach(() => {
  fake = null;
  (globalThis as unknown as { EventSource: typeof EventSource }).EventSource =
    function (url: string) {
      fake = new FakeES(url);
      return fake as unknown as EventSource;
    } as unknown as typeof EventSource;
});

afterEach(() => disconnect());

describe('OperatePlaneGrid', () => {
  it('renders all 8 planes as unknown initially', () => {
    const { container } = render(OperatePlaneGrid, {
      props: { projectId: 'p-empty' },
    });
    const cells = container.querySelectorAll('[data-testid="plane-cell"]');
    expect(cells).toHaveLength(8);
    for (const cell of Array.from(cells)) {
      expect(cell.getAttribute('data-status')).toBe('unknown');
    }
  });

  it('updates a plane status from a published event', async () => {
    const { container } = render(OperatePlaneGrid, {
      props: { projectId: 'p-update' },
    });
    fake!.emit('operate_plane_status', evt('database', 'active', '2026-05-30T12:00:00+00:00'));
    await new Promise((r) => setTimeout(r, 5));
    const db = container.querySelector(
      '[data-testid="plane-cell"][data-plane="database"]',
    );
    expect(db?.getAttribute('data-status')).toBe('active');
  });

  it('honours newest-first for the per-plane snapshot', async () => {
    const { container } = render(OperatePlaneGrid, {
      props: { projectId: 'p-fresh' },
    });
    fake!.emit('operate_plane_status', evt('alerting', 'error', '2026-05-30T11:00:00+00:00'));
    fake!.emit('operate_plane_status', evt('alerting', 'active', '2026-05-30T12:00:00+00:00'));
    await new Promise((r) => setTimeout(r, 5));
    const alerting = container.querySelector(
      '[data-testid="plane-cell"][data-plane="alerting"]',
    );
    expect(alerting?.getAttribute('data-status')).toBe('active');
  });

  it('surfaces plane errors when present', async () => {
    const { container } = render(OperatePlaneGrid, {
      props: { projectId: 'p-err' },
    });
    fake!.emit(
      'operate_plane_status',
      evt('monitoring', 'error', '2026-05-30T12:00:00+00:00', {
        payload: {
          plane: 'monitoring',
          status: 'error',
          error: 'Prometheus unreachable',
        },
      }),
    );
    await new Promise((r) => setTimeout(r, 5));
    const cell = container.querySelector(
      '[data-testid="plane-cell"][data-plane="monitoring"]',
    );
    expect(cell?.querySelector('[data-testid="plane-error"]')?.textContent).toMatch(
      /Prometheus unreachable/,
    );
  });

  it('invokes onInvoke with plane + action', async () => {
    const handler = vi.fn();
    const { container } = render(OperatePlaneGrid, {
      props: { projectId: 'p-inv', onInvoke: handler },
    });
    fake!.emit('operate_plane_status', evt('database', 'active', '2026-05-30T12:00:00+00:00'));
    await new Promise((r) => setTimeout(r, 5));
    const db = container.querySelector(
      '[data-testid="plane-cell"][data-plane="database"]',
    );
    const btn = db?.querySelector('[data-testid="invoke"]') as HTMLElement;
    await fireEvent.click(btn);
    expect(handler).toHaveBeenCalledWith('database', 'status');
  });
});
