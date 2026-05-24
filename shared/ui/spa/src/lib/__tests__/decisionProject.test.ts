import { describe, expect, it } from 'vitest';
import { decisionProjectRef, sortDecisionsByProject } from '../decisionProject';
import type { DecisionCard } from '../api/types';

function card(partial: Partial<DecisionCard>): DecisionCard {
  return {
    decision_id: 'dec-1',
    decision_class: 'approval',
    title: 'Test',
    body: '',
    severity: 'info',
    actions: ['ack', 'reject'],
    status: 'pending',
    created_at: 1,
    metadata: {},
    ...partial,
  };
}

describe('decisionProjectRef', () => {
  it('resolves project from metadata', () => {
    const ref = decisionProjectRef(
      card({
        project_id: '9',
        metadata: { project_name: 'Sample Website', project_uuid: 'uuid-9' },
      })
    );
    expect(ref.scope).toBe('project');
    expect(ref.label).toBe('Sample Website');
    expect(ref.linkId).toBe('9');
  });

  it('falls back to title suffix for project name', () => {
    const ref = decisionProjectRef(
      card({
        project_id: 'uuid-abc',
        title: 'Approve CODE output — Sample Website 145200',
      })
    );
    expect(ref.label).toBe('Sample Website 145200');
    expect(ref.linkId).toBe('uuid-abc');
  });

  it('labels briefings as hub-wide', () => {
    const ref = decisionProjectRef(
      card({
        decision_class: 'briefing',
        title: 'Daily briefing — Security + compliance posture',
        metadata: { project_count: 3 },
      })
    );
    expect(ref.scope).toBe('hub');
    expect(ref.label).toBe('Hub-wide · 3 active projects');
    expect(ref.linkId).toBeNull();
  });
});

describe('sortDecisionsByProject', () => {
  it('sorts project-scoped cards before hub-wide briefings', () => {
    const items = sortDecisionsByProject([
      card({ decision_id: 'b', decision_class: 'briefing', created_at: 10 }),
      card({
        decision_id: 'a',
        project_id: '9',
        metadata: { project_name: 'Site' },
        created_at: 1,
      }),
    ]);
    expect(items.map((c) => c.decision_id)).toEqual(['a', 'b']);
  });
});
