import { describe, expect, it } from 'vitest';
import {
  bucketProject,
  groupProjects,
  isTerminalProject,
  type HubProjectRow
} from '../projectAttention';

function project(partial: Partial<HubProjectRow>): HubProjectRow {
  return {
    project_id: '1',
    name: 'Test',
    project_type: 'feature',
    current_phase: 'build_in_progress',
    status: 'active',
    updated_at: '2026-05-23T00:00:00Z',
    ...partial
  };
}

describe('projectAttention', () => {
  it('buckets attention before live', () => {
    const groups = groupProjects(
      [
        project({ project_id: '1', project_uuid: 'uuid-1', current_phase: 'build_in_progress' }),
        project({ project_id: '2', current_phase: 'released', status: 'active' })
      ],
      [
        {
          decision_id: 'd1',
          decision_class: 'approval',
          project_id: null,
          title: 'Approve CODE output — Test',
          body: '',
          severity: 'info',
          actions: ['ack'],
          status: 'pending',
          created_at: 1,
          metadata: { project_uuid: 'uuid-1' }
        }
      ],
      {}
    );
    expect(groups.attention.map((p) => p.project_id)).toEqual(['1']);
    expect(groups.idle.map((p) => p.project_id)).toEqual(['2']);
  });

  it('marks released projects as idle', () => {
    expect(isTerminalProject(project({ current_phase: 'released' }))).toBe(true);
    expect(bucketProject(project({ current_phase: 'released' }), [], {})).toBe('idle');
  });

  it('marks active pipeline projects as live', () => {
    expect(bucketProject(project({ current_phase: 'plan_in_progress' }), [], {})).toBe('live');
  });
});
