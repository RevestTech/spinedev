/**
 * Project-scoped decision list — filters the hub-wide queue without forcing
 * the project +page to re-render on unrelated card SSE events.
 */

import { derived, writable } from 'svelte/store';
import type { DecisionCard } from '$lib/api/types';
import { decisions } from '$lib/stores/decisions';

/** Match keys for the open project (uuid, numeric id, etc.). Set once per project load. */
export const projectDecisionKeys = writable<string[]>([]);

function cardMatchesKeys(card: DecisionCard, keys: Set<string>): boolean {
  if (keys.size === 0) return false;
  const pid = card.project_id;
  if (pid && keys.has(String(pid))) return true;
  const metaUuid = card.metadata?.project_uuid;
  return metaUuid != null && keys.has(String(metaUuid));
}

let cachedItems: DecisionCard[] | null = null;
let cachedKeySig = '';
let cachedResult: DecisionCard[] = [];

export const projectScopedDecisions = derived(
  [decisions, projectDecisionKeys],
  ([$decisions, keys]) => {
    const items = $decisions.items ?? [];
    const keySig = keys.filter(Boolean).join('\0');
    if (items === cachedItems && keySig === cachedKeySig) {
      return cachedResult;
    }
    cachedItems = items;
    cachedKeySig = keySig;
    const keySet = new Set(keys.filter(Boolean));
    if (keySet.size === 0) {
      cachedResult = [];
      return cachedResult;
    }
    cachedResult = items.filter((c) => cardMatchesKeys(c, keySet));
    return cachedResult;
  }
);

export const projectScopedDecisionCount = derived(
  projectScopedDecisions,
  ($cards) => $cards.length
);
