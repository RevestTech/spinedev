/** Tests for InstinctBadge.svelte (Path A T18). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import InstinctBadge from '$lib/components/InstinctBadge.svelte';
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
  fingerprint: string,
  actor: string,
  overrides: Partial<ProjectEvent> = {},
): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'instinct_recorded',
    project_id: 'proj-inst',
    occurred_at: new Date().toISOString(),
    actor,
    verdict: null,
    citation_count: 0,
    summary: 'instinct',
    payload: {
      fingerprint,
      pattern: 'engineer completed directive',
      trigger: 'auth implementation',
      confidence: 0.3,
    },
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

describe('InstinctBadge', () => {
  it('renders empty state initially', () => {
    const { getByTestId } = render(InstinctBadge, {
      props: { projectId: 'p-empty' },
    });
    expect(getByTestId('instinct-title').textContent).toMatch(/No instincts/i);
  });

  it('aggregates by fingerprint and shows the most-corroborated', async () => {
    const { getByTestId } = render(InstinctBadge, {
      props: { projectId: 'p-aggr' },
    });
    fake!.emit('instinct_recorded', evt('fp-1', 'engineer'));
    fake!.emit('instinct_recorded', evt('fp-1', 'engineer'));
    fake!.emit('instinct_recorded', evt('fp-1', 'qa'));
    fake!.emit('instinct_recorded', evt('fp-2', 'engineer'));
    await new Promise((r) => setTimeout(r, 5));

    // fp-1 has 2 distinct actors; fp-2 has 1. fp-1 wins.
    expect(getByTestId('actor-count').textContent).toMatch(/2 actors/);
  });

  it('shows promote button only after threshold reached', async () => {
    const { container } = render(InstinctBadge, {
      props: { projectId: 'p-prom', promotionThreshold: 2 },
    });
    fake!.emit('instinct_recorded', evt('fp-1', 'engineer'));
    await new Promise((r) => setTimeout(r, 5));
    expect(container.querySelector('[data-testid="promote"]')).toBe(null);

    fake!.emit('instinct_recorded', evt('fp-1', 'qa'));
    await new Promise((r) => setTimeout(r, 5));
    expect(container.querySelector('[data-testid="promote"]')).not.toBe(null);
  });

  it('invokes onPromote with the top fingerprint', async () => {
    const handler = vi.fn();
    const { getByTestId } = render(InstinctBadge, {
      props: { projectId: 'p-cb', promotionThreshold: 2, onPromote: handler },
    });
    fake!.emit('instinct_recorded', evt('fp-target', 'engineer'));
    fake!.emit('instinct_recorded', evt('fp-target', 'qa'));
    await new Promise((r) => setTimeout(r, 5));
    await fireEvent.click(getByTestId('promote'));
    expect(handler).toHaveBeenCalledWith('fp-target');
  });
});
