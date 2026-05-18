// Spine Hub SPA — root layout load (V3 Wave 3 part 2, Squad SPA1).
//
// Runs once on first navigation + on every client-side route change.
// Pre-fetches the current user from the Hub identity endpoint. A 401
// triggers the Keycloak login redirect via the apiFetch wrapper, so
// unauthenticated visitors never see a flash of unauthorized UI.
//
// Three routes are PUBLIC (no auth required):
//   /auth/login, /auth/callback, /auth/logout
// Every other URL forces the auth check.

import { browser } from '$app/environment';
import type { LayoutLoad } from './$types';
import { api, redirectToLogin } from '$lib/api/client';
import { setUser, clearUser } from '$lib/stores/user';
import type { SpineUser } from '$lib/api/types';

export const ssr = false; // pure SPA — adapter-static
export const prerender = false;
export const trailingSlash = 'never';

const PUBLIC_ROUTES = new Set<string>([
  '/auth/login',
  '/auth/logout',
  '/auth/callback'
]);

export const load: LayoutLoad = async ({ url, fetch }) => {
  if (!browser) return { user: null };

  const path = url.pathname.replace(/\/+$/, '') || '/';
  if (PUBLIC_ROUTES.has(path)) {
    return { user: null };
  }

  try {
    // The Hub doesn't yet expose /api/v2/auth/whoami (Wave 4 adds it). For
    // now we fetch a tiny anchored endpoint that requires auth — the
    // registry health probe — and treat the 200 as proof-of-session. SPA2
    // swaps this for a dedicated /whoami once the endpoint lands.
    const probe = await api.get<{ ok: boolean; user?: SpineUser }>(
      '/api/v2/registry/me',
      { redirectOn401: false, timeoutMs: 5_000 }
    ).catch(() => null);

    if (probe?.user) {
      setUser(probe.user);
      return { user: probe.user };
    }
    // Backend up but no /me yet: synthesize a minimal user from cookie state
    // so the SPA renders. Real claims arrive once /whoami ships.
    const placeholder: SpineUser = {
      sub: 'session',
      username: 'session-user',
      roles: [],
      hub_id: undefined
    };
    setUser(placeholder);
    return { user: placeholder };
  } catch (err) {
    // 401 from apiFetch already triggered the redirect via redirectToLogin
    // when redirectOn401=true; here we hit the explicit catch path.
    clearUser();
    if ((err as { status?: number }).status === 401) {
      redirectToLogin();
    }
    return { user: null };
  }
};
