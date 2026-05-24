import { describe, expect, it } from 'vitest';
import { isHubInboxCard, isProjectDecisionCard } from '$lib/decisionScope';
import type { DecisionCard } from '$lib/api/types';

function card(partial: Partial<DecisionCard> & Pick<DecisionCard, 'decision_id' | 'title'>): DecisionCard {
  return {
    decision_class: 'approval',
    body: '',
    severity: 'info',
    actions: ['ack', 'reject'],
    status: 'pending',
    created_at: 1,
    metadata: {},
    ...partial
  };
}

describe('decisionScope', () => {
  it('treats master_daily_briefing as hub inbox', () => {
    const c = card({
      decision_id: 'b1',
      decision_class: 'briefing',
      title: 'Security briefing',
      metadata: { kind: 'master_daily_briefing' }
    });
    expect(isHubInboxCard(c)).toBe(true);
    expect(isProjectDecisionCard(c)).toBe(false);
  });

  it('treats project-tied cards as project decisions', () => {
    const c = card({
      decision_id: 'p1',
      title: 'Approve PRD',
      project_id: '9',
      metadata: { project_uuid: 'uuid-9' }
    });
    expect(isHubInboxCard(c)).toBe(false);
    expect(isProjectDecisionCard(c)).toBe(true);
  });

  it('treats orphan briefings without project keys as hub inbox', () => {
    const c = card({
      decision_id: 'b2',
      decision_class: 'briefing',
      title: 'Daily rollup'
    });
    expect(isHubInboxCard(c)).toBe(true);
  });
});
