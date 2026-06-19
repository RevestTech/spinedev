import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import {
  wsBind,
  wsUnbind,
  wsFeed,
  wsRunState,
  wsRecovery,
  wsRecoveryLoading,
  wsTerminal,
  __testQueueActivityEvent,
  __testSetWorkspaceActivityReady,
  __testApplyRecoveryResponse,
} from '../projectWorkspace';
import type { DecisionActivityEvent } from '../decisions';
import { __testSetSyncFrameCommits, __testFlushFrameCommits } from '../../uiFrameScheduler';

vi.mock('$lib/yieldMainThread', () => ({
  yieldMainThread: () => Promise.resolve(),
}));

function roleStartedEvent(i: number): DecisionActivityEvent {
  return {
    type: 'role_started',
    project_uuid: 'proj-1',
    role: 'engineer',
    message: `event ${i}`,
    ts: i,
  };
}

describe('projectWorkspace SSE batching', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    __testSetSyncFrameCommits(true);
    wsBind('proj-1');
    __testSetWorkspaceActivityReady(true);
  });

  afterEach(() => {
    wsUnbind();
    __testSetSyncFrameCommits(false);
    vi.useRealTimers();
  });

  it('does not synchronously flood wsFeed when many events are queued', () => {
    for (let i = 0; i < 20; i++) {
      __testQueueActivityEvent(roleStartedEvent(i));
    }
    expect(get(wsFeed).length).toBe(0);
    expect(get(wsRunState).activeRole).toBeNull();
  });

  it('processes queued activity in timed batches instead of one synchronous burst', async () => {
    for (let i = 0; i < 12; i++) {
      __testQueueActivityEvent(roleStartedEvent(i));
    }

    await vi.advanceTimersByTimeAsync(200);
    __testFlushFrameCommits();
    expect(get(wsFeed).length).toBe(12);

    await vi.advanceTimersByTimeAsync(200);
    __testFlushFrameCommits();
    expect(get(wsFeed).length).toBe(12);
  });

  it('ignores events for other projects before queueing', async () => {
    for (let i = 0; i < 30; i++) {
      __testQueueActivityEvent({
        type: 'role_started',
        project_uuid: 'other-project',
        role: 'engineer',
        message: `skip ${i}`,
        ts: i,
      });
    }

    await vi.advanceTimersByTimeAsync(500);
    expect(get(wsFeed).length).toBe(0);
  });

  it('applies recovery GET after wsBind sets boundProjectId', () => {
    __testApplyRecoveryResponse('proj-1', {
      stuck: true,
      reasons: ['code_review_blocked'],
      pending_decisions: 0,
      recommended_action: 'reset_fix_loop',
      last_role_failure: null,
      dispatch_in_flight: null,
      actions: [{ action: 'reset_fix_loop', label: 'Reset', description: 'Reset loop' }],
      fix_loop_exhausted: true,
      code_review_blocked: true,
    });
    expect(get(wsRecovery)?.stuck).toBe(true);
    expect(get(wsRecovery)?.actions?.length).toBe(1);
  });

  it('applies recovery_pulse for bound project', async () => {
    __testQueueActivityEvent({
      type: 'recovery_pulse',
      project_uuid: 'proj-1',
      stuck: true,
      actions: [{ action: 'resume', label: 'Resume', description: 'Go' }],
    });

    await vi.advanceTimersByTimeAsync(350);
    __testFlushFrameCommits();
    expect(get(wsRecovery)?.stuck).toBe(true);
    expect(get(wsRecovery)?.actions?.length).toBe(1);
  });

  it('clears recovery loading when an in-flight GET is invalidated by wsUnbind', async () => {
    wsRecoveryLoading.set(true);
    wsUnbind();
    expect(get(wsRecoveryLoading)).toBe(false);
  });
});
