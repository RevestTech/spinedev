/** Tests for CharterEvalReport.svelte (Path A T19). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import CharterEvalReport from '$lib/components/CharterEvalReport.svelte';
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
  role: string,
  overall: boolean,
  perEval: Array<{
    eval_name: string;
    trials: number;
    passed: number;
    pass_rate: number;
    target_pass_rate: number;
    meets_target: boolean;
  }>,
): ProjectEvent {
  return {
    event_id: crypto.randomUUID(),
    event_type: 'charter_eval_run',
    project_id: `charter:${role}`,
    occurred_at: new Date().toISOString(),
    actor: role,
    verdict: overall ? 'passed' : 'failed',
    citation_count: 0,
    summary: `${role} charter eval`,
    payload: {
      role,
      overall_meets_target: overall,
      per_eval: perEval,
    },
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

describe('CharterEvalReport', () => {
  it('renders empty until first run arrives', () => {
    const { getByTestId } = render(CharterEvalReport, {
      props: { role: 'engineer' },
    });
    expect(getByTestId('empty').textContent).toMatch(/No eval run/i);
  });

  it('renders per-eval rows + overall badge on pass', async () => {
    const { container, getByTestId } = render(CharterEvalReport, {
      props: { role: 'engineer' },
    });
    fake!.emit(
      'charter_eval_run',
      evt('engineer', true, [
        {
          eval_name: 'engineer-cites-req',
          trials: 5,
          passed: 5,
          pass_rate: 1.0,
          target_pass_rate: 0.8,
          meets_target: true,
        },
        {
          eval_name: 'engineer-search-first',
          trials: 5,
          passed: 4,
          pass_rate: 0.8,
          target_pass_rate: 0.8,
          meets_target: true,
        },
      ]),
    );
    await new Promise((r) => setTimeout(r, 5));

    const rows = container.querySelectorAll('[data-testid="eval-row"]');
    expect(rows).toHaveLength(2);
    expect(getByTestId('overall').textContent).toMatch(/pass/i);
  });

  it('marks overall fail if any eval regresses', async () => {
    const { getByTestId } = render(CharterEvalReport, {
      props: { role: 'architect' },
    });
    fake!.emit(
      'charter_eval_run',
      evt('architect', false, [
        {
          eval_name: 'architect-cites-kg',
          trials: 5,
          passed: 1,
          pass_rate: 0.2,
          target_pass_rate: 0.8,
          meets_target: false,
        },
      ]),
    );
    await new Promise((r) => setTimeout(r, 5));
    expect(getByTestId('overall').textContent).toMatch(/fail/i);
  });

  it('invokes onRunEvals with the role on button click', async () => {
    const handler = vi.fn();
    const { getByTestId } = render(CharterEvalReport, {
      props: { role: 'qa', onRunEvals: handler },
    });
    await fireEvent.click(getByTestId('run-evals'));
    expect(handler).toHaveBeenCalledWith('qa');
  });
});
