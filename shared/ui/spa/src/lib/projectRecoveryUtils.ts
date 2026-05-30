/** Shared recovery / dispatch helpers for project workspace UI. */

export interface RecoveryActionSpec {
  action: string;
  label: string;
  description: string;
}

export interface RecoveryStatus {
  stuck: boolean;
  reasons: string[];
  pending_decisions: number;
  recommended_action?: string | null;
  last_role_failure?: { role?: string; error?: string; retry_action?: string } | null;
  dispatch_in_flight?: { dispatch_kind?: string; action?: string; started_at?: string } | null;
  actions: RecoveryActionSpec[];
  code_fix_iteration?: number;
  max_code_fix_iterations?: number;
  fix_loop_exhausted?: boolean;
  code_review_blocked?: boolean;
  current_phase?: string;
}

const DISPATCH_STALE_MS = 5 * 60 * 1000;

export function isDispatchStale(
  inflight: RecoveryStatus['dispatch_in_flight']
): boolean {
  if (!inflight?.started_at) return true;
  const started = Date.parse(String(inflight.started_at).replace('Z', '+00:00'));
  if (Number.isNaN(started)) return true;
  return Date.now() - started > DISPATCH_STALE_MS;
}

export function dispatchInFlightActive(rec: RecoveryStatus | null): boolean {
  const inflight = rec?.dispatch_in_flight;
  return Boolean(inflight && !isDispatchStale(inflight));
}

export function primaryStuckReason(reasons: string[]): string {
  const order = [
    'fix_loop_exhausted',
    'code_review_blocked',
    'last_role_failed',
    'workspace_empty_stale_metadata',
    'workspace_empty_no_code',
    'no_pending_decisions',
  ];
  for (const r of order) {
    if (reasons.includes(r)) return r;
  }
  return reasons[0] ?? 'no_pending_decisions';
}
