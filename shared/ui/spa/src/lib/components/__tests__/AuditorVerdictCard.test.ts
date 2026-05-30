/** Tests for AuditorVerdictCard.svelte (Path A T17). */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import AuditorVerdictCard from '$lib/components/AuditorVerdictCard.svelte';
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

function evt(overrides: Partial<ProjectEvent> = {}): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'auditor_verdict',
    project_id: 'proj-aud',
    occurred_at: new Date().toISOString(),
    actor: 'auditor',
    verdict: 'ok',
    citation_count: 2,
    summary: 'verdict summary',
    payload: { audit_id: 'audit-1' },
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

describe('AuditorVerdictCard', () => {
  it('renders empty state when no auditor events', () => {
    const { getByTestId } = render(AuditorVerdictCard, {
      props: { projectId: 'p-empty' },
    });
    expect(getByTestId('title').textContent).toMatch(/No auditor activity/i);
  });

  it('renders verdict + citation count', async () => {
    const { getByTestId } = render(AuditorVerdictCard, {
      props: { projectId: 'p-v' },
    });
    fake!.emit(
      'auditor_verdict',
      evt({ summary: 'looks good', citation_count: 3 }),
    );
    await new Promise((r) => setTimeout(r, 5));
    expect(getByTestId('title').textContent).toMatch(/looks good/);
    expect(getByTestId('citation-count').textContent).toMatch(/3 citations/);
  });

  it('expands why-denied for refusal events', async () => {
    const { container, getByTestId } = render(AuditorVerdictCard, {
      props: { projectId: 'p-r' },
    });
    fake!.emit(
      'auditor_refusal',
      evt({
        event_type: 'auditor_refusal',
        verdict: 'refusal',
        citation_count: 0,
        summary: 'refused',
        payload: { audit_id: 'audit-99', refusal_reason: 'no_citations' },
      }),
    );
    await new Promise((r) => setTimeout(r, 5));

    expect(container.querySelector('[data-testid="why-denied"]')).toBe(null);
    await fireEvent.click(getByTestId('why-denied-toggle'));
    await new Promise((r) => setTimeout(r, 5));

    const expanded = container.querySelector('[data-testid="why-denied"]');
    expect(expanded?.textContent).toMatch(/no_citations/);
  });

  it('pairs ledger reasons with the matching audit_id', async () => {
    const { container, getByTestId } = render(AuditorVerdictCard, {
      props: { projectId: 'p-paired' },
    });
    fake!.emit(
      'auditor_refusal',
      evt({
        event_type: 'auditor_refusal',
        verdict: 'refusal',
        citation_count: 0,
        summary: 'refused',
        payload: { audit_id: 'audit-paired', refusal_reason: 'thin_evidence' },
      }),
    );
    fake!.emit('ledger_append', {
      event_id: crypto.randomUUID(),
      event_type: 'ledger_append',
      project_id: 'p-paired',
      occurred_at: new Date().toISOString(),
      actor: 'auditor',
      verdict: 'denied',
      citation_count: 0,
      summary: 'ledger',
      payload: {
        run_id: 'audit-paired',
        promotion_tier: 'production',
        promotion_reasons: ['freshness_stale', 'replay_failed'],
      },
    });
    await new Promise((r) => setTimeout(r, 5));
    await fireEvent.click(getByTestId('why-denied-toggle'));
    await new Promise((r) => setTimeout(r, 5));

    const why = container.querySelector('[data-testid="why-denied"]');
    expect(why?.textContent).toMatch(/freshness_stale/);
    expect(why?.textContent).toMatch(/replay_failed/);
  });
});
