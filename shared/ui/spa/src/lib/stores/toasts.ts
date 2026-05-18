// Spine Hub SPA — transient toast notifications (V3 Wave 3 part 2).
//
// Lightweight pattern — every panel can `toasts.push({...})` and the
// layout's <Toasts /> island renders them. Auto-dismiss after `ttlMs`.

import { writable } from 'svelte/store';

export type ToastKind = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  kind: ToastKind;
  title?: string;
  message: string;
  ttlMs?: number;
}

const items = writable<Toast[]>([]);

function nextId(): string {
  return `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const toasts = {
  subscribe: items.subscribe,
  push(t: Omit<Toast, 'id'>): string {
    const id = nextId();
    const ttl = t.ttlMs ?? 5000;
    items.update((xs) => [...xs, { id, ...t }]);
    if (ttl > 0 && typeof setTimeout !== 'undefined') {
      setTimeout(() => this.dismiss(id), ttl);
    }
    return id;
  },
  dismiss(id: string): void {
    items.update((xs) => xs.filter((x) => x.id !== id));
  },
  clear(): void {
    items.set([]);
  }
};
