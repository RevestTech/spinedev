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
import { normalizePathname } from '$lib/navActive';
import { ApiError, type SpineUser } from '$lib/api/types';

export const ssr = false; // pure SPA — adapter-static
export const prerender = false;
export const trailingSlash = 'never';

const PUBLIC_ROUTES = new Set<string>([
  '/auth/login',
  '/auth/logout',
  '/auth/callback'
]);

async function resolveHubId(): Promise<string | undefined> {
  const stat = await api
    .get<{ local_hub_id?: string }>('/api/v2/federation/status', {
      redirectOn401: false,
      timeoutMs: 5_000
    })
    .catch(() => null);
  return stat?.local_hub_id;
}

function userFromProbe(raw: Record<string, unknown>): SpineUser {
  return {
    sub: String(raw.sub ?? ''),
    username: String(raw.username ?? raw.email ?? 'user'),
    email: raw.email != null ? String(raw.email) : undefined,
    roles: Array.isArray(raw.roles) ? raw.roles.map(String) : [],
    hub_id: raw.hub_id != null ? String(raw.hub_id) : undefined
  };
}

export const load: LayoutLoad = async ({ url }) => {
  if (!browser) return { user: null };

  const path = normalizePathname(url.pathname.replace(/\/+$/, '') || '/');
  if (PUBLIC_ROUTES.has(path)) {
    return { user: null };
  }

  try {
    const probe = await api.get<{ ok: boolean; user: Record<string, unknown> }>(
      '/api/v2/auth/whoami',
      { redirectOn401: false, timeoutMs: 5_000 }
    );

    if (!probe?.ok || !probe.user) {
      clearUser();
      redirectToLogin();
      return { user: null };
    }

    let sessionUser = userFromProbe(probe.user);
    if (!sessionUser.hub_id) {
      const hubId = await resolveHubId();
      if (hubId) sessionUser = { ...sessionUser, hub_id: hubId };
    }

    setUser(sessionUser);
    return { user: sessionUser };
  } catch (err) {
    clearUser();
    if (err instanceof ApiError && err.status === 401) {
      redirectToLogin();
    }
    return { user: null };
  }
};
