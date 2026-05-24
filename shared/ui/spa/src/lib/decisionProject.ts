// Resolve which project (if any) a decision card belongs to.
import type { DecisionCard } from '$lib/api/types';

export type DecisionScope = 'project' | 'hub';

export interface DecisionProjectRef {
  scope: DecisionScope;
  /** Human-readable project name or hub-wide label. */
  label: string;
  /** Route segment for /projects/{linkId} — uuid or numeric id. */
  linkId: string | null;
}

/** Extract project name from titles like "Approve CODE output — Sample Website". */
function nameFromTitle(title: string): string | null {
  const idx = title.indexOf(' — ');
  if (idx < 0) return null;
  const tail = title.slice(idx + 3).trim();
  return tail || null;
}

export function decisionProjectRef(card: DecisionCard): DecisionProjectRef {
  const meta = card.metadata ?? {};
  const metaName =
    typeof meta.project_name === 'string' ? meta.project_name.trim() : '';
  const metaUuid =
    typeof meta.project_uuid === 'string' ? meta.project_uuid.trim() : '';
  const pid = card.project_id?.trim() || null;
  const titleName =
    card.decision_class !== 'briefing' ? nameFromTitle(card.title) : null;
  const name = metaName || titleName || null;
  const linkId = pid || metaUuid || null;

  if (linkId || name) {
    return {
      scope: 'project',
      label: name || 'Project',
      linkId,
    };
  }

  if (card.decision_class === 'briefing') {
    const count = meta.project_count;
    const label =
      typeof count === 'number' && count > 0
        ? `Hub-wide · ${count} active project${count === 1 ? '' : 's'}`
        : 'Hub-wide briefing';
    return { scope: 'hub', label, linkId: null };
  }

  return { scope: 'hub', label: 'Hub-wide', linkId: null };
}

export function sortDecisionsByProject(items: DecisionCard[]): DecisionCard[] {
  return [...items].sort((a, b) => {
    const aProject = decisionProjectRef(a).scope === 'project' ? 0 : 1;
    const bProject = decisionProjectRef(b).scope === 'project' ? 0 : 1;
    if (aProject !== bProject) return aProject - bProject;
    return b.created_at - a.created_at;
  });
}

export interface DecisionPartition {
  projectItems: DecisionCard[];
  hubItems: DecisionCard[];
}

/** Split queue into project-scoped approvals vs hub-wide briefings. */
export function partitionDecisions(items: DecisionCard[]): DecisionPartition {
  const projectItems: DecisionCard[] = [];
  const hubItems: DecisionCard[] = [];
  for (const card of items) {
    if (decisionProjectRef(card).scope === 'project') {
      projectItems.push(card);
    } else {
      hubItems.push(card);
    }
  }
  const byNewest = (a: DecisionCard, b: DecisionCard) => b.created_at - a.created_at;
  projectItems.sort(byNewest);
  hubItems.sort(byNewest);
  return { projectItems, hubItems };
}
