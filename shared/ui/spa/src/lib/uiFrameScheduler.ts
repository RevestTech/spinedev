/**
 * Coalesce store commits onto animation frames so SSE bursts cannot monopolize
 * the main thread. Each frame runs at most MAX_JOBS_PER_FRAME callbacks; excess
 * work rolls to the next frame (browser stays responsive).
 */

type FrameJob = () => void;

const MAX_JOBS_PER_FRAME = 6;
const pending: FrameJob[] = [];
let frameScheduled = false;
let syncImmediate = false;

export function __testSetSyncFrameCommits(enabled: boolean): void {
  syncImmediate = enabled;
}

/** Drain pending jobs synchronously — vitest seam. */
export function __testFlushFrameCommits(): void {
  while (pending.length > 0) {
    const batch = pending.splice(0, MAX_JOBS_PER_FRAME);
    for (const job of batch) job();
  }
  frameScheduled = false;
}

export function scheduleFrameCommit(job: FrameJob): void {
  pending.push(job);
  if (syncImmediate) {
    __testFlushFrameCommits();
    return;
  }
  if (frameScheduled) return;
  frameScheduled = true;
  requestAnimationFrame(() => {
    frameScheduled = false;
    const batch = pending.splice(0, MAX_JOBS_PER_FRAME);
    for (const j of batch) j();
    if (pending.length > 0) scheduleFrameCommit(() => {});
  });
}

/** Wait until pending rAF store commits drain — use after boot-time recovery GET. */
export function flushFrameCommitsForBoot(): Promise<void> {
  return new Promise((resolve) => {
    if (syncImmediate) {
      __testFlushFrameCommits();
      resolve();
      return;
    }
    if (pending.length === 0 && !frameScheduled) {
      resolve();
      return;
    }
    scheduleFrameCommit(() => resolve());
  });
}
