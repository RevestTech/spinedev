import type { DecisionCard } from '$lib/api/types';
import { cardProjectKeys } from '$lib/projectAttention';

export const HUB_INBOX_KIND = 'master_daily_briefing';

export function isHubInboxCard(card: DecisionCard): boolean {
  const kind = card.metadata?.kind;
  if (kind === HUB_INBOX_KIND) return true;
  if (card.decision_class === 'briefing' && cardProjectKeys(card).length === 0) return true;
  return false;
}

export function isProjectDecisionCard(card: DecisionCard): boolean {
  return !isHubInboxCard(card);
}
