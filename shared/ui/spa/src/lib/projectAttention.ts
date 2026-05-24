import type { DecisionCard } from '$lib/api/types';
import { PIPELINE_COPY } from '$lib/projectPipelineCopy';

export interface HubProjectRow {
  project_id: string;
  project_uuid?: string;
  name: string;
  project_type: string;
  current_phase: string;
  status: string;
  owner?: string;
  updated_at?: string;
}

export interface StuckSummary {
  project_id: string;
  project_uuid?: string;
  reasons?: string[];
  pending_decisions?: number;
}

export const SDLC_PHASES = ['intake', 'plan', 'build', 'verify', 'release'] as const;

const TERMINAL_PHASES = new Set(['released', 'retro', 'terminated', 'release', 'operate']);

export function filterUserProjects(
  projects: HubProjectRow[],
  showAutomated = false
): HubProjectRow[] {
  return projects.filter((p) => {
    if (showAutomated) return p.status !== 'terminated';
    const isSmokeOwner = p.owner === 'smoke-harness';
    const isSmokeName = p.name?.startsWith('smoke-') ?? false;
    return !isSmokeOwner && !isSmokeName && p.status !== 'terminated';
  });
}

export function cardProjectKeys(card: DecisionCard): string[] {
  const keys = new Set<string>();
  if (card.project_id) keys.add(String(card.project_id).trim());
  const metaUuid = card.metadata?.project_uuid;
  if (metaUuid != null && String(metaUuid).trim()) keys.add(String(metaUuid).trim());
  return [...keys];
}

export function pendingForProject(p: HubProjectRow, cards: DecisionCard[]): number {
  const pKeys = new Set<string>([p.project_id]);
  if (p.project_uuid) pKeys.add(p.project_uuid);
  return cards.filter((c) => {
    const cKeys = cardProjectKeys(c);
    if (cKeys.length === 0) return false;
    return cKeys.some((k) => pKeys.has(k));
  }).length;
}

export function stuckForProject(
  p: HubProjectRow,
  stuckByProject: Record<string, StuckSummary>
): StuckSummary | undefined {
  return (
    stuckByProject[p.project_id] ??
    (p.project_uuid ? stuckByProject[p.project_uuid] : undefined)
  );
}

export function projectNeedsAttention(
  p: HubProjectRow,
  cards: DecisionCard[],
  stuckByProject: Record<string, StuckSummary> = {}
): boolean {
  return pendingForProject(p, cards) > 0 || stuckForProject(p, stuckByProject) != null;
}

export function attentionHint(
  p: HubProjectRow,
  cards: DecisionCard[],
  stuckByProject: Record<string, StuckSummary> = {}
): string | null {
  const pending = pendingForProject(p, cards);
  if (pending > 0) {
    return PIPELINE_COPY.attention.decisionsReview(pending);
  }
  if (stuckForProject(p, stuckByProject)) return PIPELINE_COPY.attention.paused;
  return null;
}

export function isTerminalProject(p: HubProjectRow): boolean {
  const phase = (p.current_phase ?? '').toLowerCase();
  return TERMINAL_PHASES.has(phase) || p.status === 'terminated' || p.status === 'paused';
}

export type ProjectBucket = 'attention' | 'live' | 'idle';

export function bucketProject(
  p: HubProjectRow,
  cards: DecisionCard[],
  stuckByProject: Record<string, StuckSummary>
): ProjectBucket {
  if (projectNeedsAttention(p, cards, stuckByProject)) return 'attention';
  if (isTerminalProject(p)) return 'idle';
  if (p.status === 'active') return 'live';
  return 'idle';
}

export function phaseIndex(phase: string | undefined): number {
  if (!phase) return -1;
  const p = phase.toLowerCase();
  if (p === 'intake') return 0;
  if (p.startsWith('plan')) return 1;
  if (p.startsWith('build')) return 2;
  if (p.startsWith('verify') || p === 'acceptance') return 3;
  if (p === 'released' || p === 'release' || p === 'operate' || p === 'retro') return 4;
  return -1;
}

export function phaseClass(phase: string, current: string): string {
  const idx = SDLC_PHASES.indexOf(phase as (typeof SDLC_PHASES)[number]);
  const cur = phaseIndex(current);
  if (idx < 0 || cur < 0) {
    return 'bg-surface-700 text-surface-300';
  }
  if (idx < cur) return 'bg-sky-600/80 text-white';
  if (idx === cur) return 'bg-accent text-white';
  return 'bg-surface-700/80 text-surface-400';
}

export function cycleLabel(phase: string | undefined): string {
  if (!phase) return 'Unknown';
  const p = phase.toLowerCase();
  if (p === 'intake') return 'Intake';
  if (p.startsWith('plan')) return 'Planning';
  if (p.startsWith('build')) return 'Building';
  if (p.startsWith('verify') || p === 'acceptance') return 'Verify';
  if (p === 'released' || p === 'release' || p === 'operate') return 'Released';
  if (p === 'retro') return 'Retro';
  if (p === 'terminated') return 'Terminated';
  return phase.replace(/_/g, ' ');
}

export function relTime(iso: string | undefined): string {
  if (!iso) return '';
  const dt = new Date(iso).getTime();
  if (Number.isNaN(dt)) return iso;
  const sec = Math.round((Date.now() - dt) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

export type StatusTone = 'attention' | 'running' | 'active' | 'idle';

export interface ProjectStatusLine {
  tone: StatusTone;
  label: string;
  detail?: string;
}

export function projectStatusLine(
  p: HubProjectRow,
  cards: DecisionCard[],
  stuckByProject: Record<string, StuckSummary>,
  activeRole?: { role: string; startedAt: number }
): ProjectStatusLine {
  const pending = pendingForProject(p, cards);
  if (pending > 0) {
    return {
      tone: 'attention',
      label: 'Awaiting your approval',
      detail: `${pending} decision${pending === 1 ? '' : 's'}`
    };
  }
  if (stuckForProject(p, stuckByProject)) {
    return { tone: 'attention', label: PIPELINE_COPY.attention.paused, detail: cycleLabel(p.current_phase) };
  }
  if (activeRole) {
    const roleLabel =
      PIPELINE_COPY.roles[activeRole.role as keyof typeof PIPELINE_COPY.roles]?.label ??
      activeRole.role;
    return { tone: 'running', label: `${roleLabel} in progress`, detail: cycleLabel(p.current_phase) };
  }
  if (isTerminalProject(p)) {
    return { tone: 'idle', label: cycleLabel(p.current_phase), detail: p.status };
  }
  if (p.status === 'active') {
    return { tone: 'active', label: cycleLabel(p.current_phase), detail: p.project_type };
  }
  return { tone: 'idle', label: p.status || 'Idle', detail: cycleLabel(p.current_phase) };
}

export function statusToneClass(tone: StatusTone): string {
  switch (tone) {
    case 'attention':
      return 'border-amber-500/50 bg-amber-500/15 text-amber-100';
    case 'running':
      return 'border-accent/50 bg-accent/15 text-accent';
    case 'active':
      return 'border-sky-500/40 bg-sky-500/10 text-sky-200';
    default:
      return 'border-surface-600/50 bg-surface-700/50 text-surface-400';
  }
}

export function hubWidePendingCount(cards: DecisionCard[]): number {
  return cards.filter((c) => cardProjectKeys(c).length === 0).length;
}

export function projectsWithPending(
  projects: HubProjectRow[],
  cards: DecisionCard[]
): Array<{ project: HubProjectRow; count: number }> {
  return projects
    .map((project) => ({ project, count: pendingForProject(project, cards) }))
    .filter((row) => row.count > 0);
}

export function groupProjects(
  projects: HubProjectRow[],
  cards: DecisionCard[],
  stuckByProject: Record<string, StuckSummary>
): Record<ProjectBucket, HubProjectRow[]> {
  const groups: Record<ProjectBucket, HubProjectRow[]> = {
    attention: [],
    live: [],
    idle: []
  };
  for (const p of projects) {
    groups[bucketProject(p, cards, stuckByProject)].push(p);
  }
  const byRecency = (a: HubProjectRow, b: HubProjectRow) =>
    (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
  groups.attention.sort(byRecency);
  groups.live.sort(byRecency);
  groups.idle.sort(byRecency);
  return groups;
}
