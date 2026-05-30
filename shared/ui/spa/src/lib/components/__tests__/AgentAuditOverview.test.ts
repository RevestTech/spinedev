/** Tests for AgentAuditOverview.svelte (Path A T20). */
import { describe, expect, it, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import AgentAuditOverview from '$lib/components/AgentAuditOverview.svelte';
import type {
  AgentAuditReport,
  LayerFinding,
} from '$lib/components/AgentAuditOverview.svelte';

function finding(overrides: Partial<LayerFinding> = {}): LayerFinding {
  return {
    layer: 'L01_system_prompt',
    status: 'clean',
    summary: 'all good',
    severity: 'low',
    evidence: [],
    next_actions: [],
    ...overrides,
  };
}

function report(
  overall: AgentAuditReport['overall_status'],
  findings: LayerFinding[],
): AgentAuditReport {
  return { overall_status: overall, findings };
}

describe('AgentAuditOverview', () => {
  it('renders empty when no report supplied', () => {
    const { getByTestId } = render(AgentAuditOverview, { props: {} });
    expect(getByTestId('empty').textContent).toMatch(/No audit report/i);
  });

  it('renders one row per finding + overall badge', () => {
    const { container, getByTestId } = render(AgentAuditOverview, {
      props: {
        report: report('warning', [
          finding({ layer: 'L01_system_prompt', status: 'clean' }),
          finding({
            layer: 'L10_transport',
            status: 'warning',
            summary: 'SPA bypasses envelope',
            severity: 'medium',
          }),
        ]),
      },
    });
    expect(container.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(2);
    expect(getByTestId('overall').textContent).toMatch(/warning/);
  });

  it('expands a finding on click', async () => {
    const { container } = render(AgentAuditOverview, {
      props: {
        report: report('regressed', [
          finding({
            layer: 'L09_answer_shaping',
            status: 'regressed',
            severity: 'critical',
            evidence: ['summary missing', 'next_actions missing'],
            next_actions: ['restore B2 envelope fields'],
          }),
        ]),
      },
    });
    const row = container.querySelector('[data-testid="finding-row"]') as HTMLElement;
    expect(
      container.querySelector('[data-testid="finding-expanded"]'),
    ).toBe(null);
    await fireEvent.click(row);
    await new Promise((r) => setTimeout(r, 5));
    const expanded = container.querySelector('[data-testid="finding-expanded"]');
    expect(expanded?.textContent).toMatch(/summary missing/);
    expect(expanded?.textContent).toMatch(/restore B2 envelope fields/);
  });

  it('calls the loader on refresh click', async () => {
    const loader = vi.fn().mockResolvedValue(
      report('clean', [finding({ layer: 'L01_system_prompt' })]),
    );
    const { getByTestId } = render(AgentAuditOverview, {
      props: { loader, report: report('clean', []) },
    });
    await fireEvent.click(getByTestId('refresh'));
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
