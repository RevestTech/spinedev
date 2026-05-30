/** Tests for EnvelopeSummary.svelte (Path A T16). */
import { describe, expect, it, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import EnvelopeSummary from '$lib/components/EnvelopeSummary.svelte';
import type { EnvelopeLike } from '$lib/components/EnvelopeSummary.svelte';

function envelope(overrides: Partial<EnvelopeLike> = {}): EnvelopeLike {
  return {
    status: 'ok',
    summary: 'envelope summary',
    next_actions: [],
    artifacts: [],
    ...overrides,
  };
}

describe('EnvelopeSummary', () => {
  it('renders the status + summary', () => {
    const { getByTestId } = render(EnvelopeSummary, {
      props: { envelope: envelope() },
    });
    expect(getByTestId('status').textContent).toMatch(/ok/i);
    expect(getByTestId('summary').textContent).toMatch(/envelope summary/);
  });

  it('renders next_actions as chips', () => {
    const { getAllByTestId } = render(EnvelopeSummary, {
      props: {
        envelope: envelope({
          next_actions: ['approve', 'retry_engineer_remediate'],
        }),
      },
    });
    const chips = getAllByTestId('next-action-chip');
    expect(chips).toHaveLength(2);
    expect(chips.map((c) => c.textContent?.trim())).toEqual([
      'approve',
      'retry_engineer_remediate',
    ]);
  });

  it('invokes onNextAction when a chip is clicked', async () => {
    const handler = vi.fn();
    const { getAllByTestId } = render(EnvelopeSummary, {
      props: {
        envelope: envelope({ next_actions: ['retry'] }),
        onNextAction: handler,
      },
    });
    const [chip] = getAllByTestId('next-action-chip');
    await fireEvent.click(chip);
    expect(handler).toHaveBeenCalledWith('retry');
  });

  it('renders chips as non-interactive when no handler supplied', () => {
    const { getAllByTestId } = render(EnvelopeSummary, {
      props: {
        envelope: envelope({ next_actions: ['inert'] }),
      },
    });
    const [chip] = getAllByTestId('next-action-chip');
    // Without a handler, the chip renders as a span — no click would
    // dispatch. Confirm by tag name.
    expect(chip.tagName).toBe('SPAN');
  });

  it('renders artifacts grouped by type', () => {
    const { getAllByTestId } = render(EnvelopeSummary, {
      props: {
        envelope: envelope({
          artifacts: [
            { type: 'kg_node', ref: 'node-auth', label: 'auth design' },
            { type: 'run_id', ref: 'run-abc', label: null },
          ],
        }),
      },
    });
    const items = getAllByTestId('artifact');
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute('data-artifact-type')).toBe('kg_node');
    expect(items[0].textContent).toMatch(/auth design/);
    expect(items[1].textContent).toMatch(/run-abc/);
  });

  it('applies refusal tone (red) for refusal status', () => {
    const { container } = render(EnvelopeSummary, {
      props: { envelope: envelope({ status: 'refusal', summary: 'no' }) },
    });
    expect(container.querySelector('article')?.className).toMatch(/bg-red-50/);
  });

  it('applies warning tone (amber) for warning status', () => {
    const { container } = render(EnvelopeSummary, {
      props: { envelope: envelope({ status: 'warning', summary: 'careful' }) },
    });
    expect(container.querySelector('article')?.className).toMatch(/bg-amber-50/);
  });

  it('applies ok tone (emerald) for ok status', () => {
    const { container } = render(EnvelopeSummary, {
      props: { envelope: envelope({ status: 'ok', summary: 'fine' }) },
    });
    expect(container.querySelector('article')?.className).toMatch(/bg-emerald-50/);
  });
});
