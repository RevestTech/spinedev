import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import {
  wsBind,
  wsUnbind,
  wsFeed,
  wsRunState,
  __testQueueActivityEvent,
} from '../projectWorkspace';
import type { DecisionActivityEvent } from '../decisions';

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
    wsBind('proj-1');
  });

  afterEach(() => {
    wsUnbind();
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

    await vi.advanceTimersByTimeAsync(150);
    expect(get(wsFeed).length).toBe(8);

    await vi.advanceTimersByTimeAsync(150);
    expect(get(wsFeed).length).toBe(12);
  });

  it('ignores events for other projects', async () => {
    __testQueueActivityEvent({
      type: 'role_started',
      project_uuid: 'other-project',
      role: 'engineer',
      message: 'skip me',
      ts: 1,
    });

    await vi.advanceTimersByTimeAsync(150);
    expect(get(wsFeed).length).toBe(0);
  });
});
