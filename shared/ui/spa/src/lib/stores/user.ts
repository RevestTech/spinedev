// Spine Hub SPA — current-user store (V3 Wave 3 part 2, Squad SPA1).
//
// Hydrated by src/routes/+layout.ts on first page load; refreshed after
// /auth/callback completes. Components subscribe via `$user` in templates
// or `get(user)` in code.

import { writable } from 'svelte/store';
import type { SpineUser } from '$lib/api/types';

export const user = writable<SpineUser | null>(null);

export function setUser(u: SpineUser | null): void {
  user.set(u);
}

export function clearUser(): void {
  user.set(null);
}
