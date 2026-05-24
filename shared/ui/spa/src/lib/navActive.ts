import { base } from '$app/paths';

/** Absolute in-app URL including SPA base prefix (e.g. `/spa/projects`). */
export function navHref(href: string): string {
  const root = base || '';
  if (href === '/') return `${root}/`;
  return `${root}${href}`;
}

/**
 * Normalize the current URL pathname for nav highlighting.
 * Handles both `/panels/foo` (SvelteKit internal) and `/spa/panels/foo` (browser URL).
 */
export function normalizePathname(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, '') || '/';
  if (!base) return trimmed;
  if (trimmed === base) return '/';
  if (trimmed.startsWith(`${base}/`)) return trimmed.slice(base.length) || '/';
  return trimmed;
}

function matchNavPath(path: string, href: string): boolean {
  const p = path.replace(/\/+$/, '') || '/';
  if (href === '/') return p === '/';
  if (href === '/projects') {
    return p === '/projects' || p.startsWith('/projects/');
  }
  return p === href || p.startsWith(`${href}/`);
}

/**
 * True when `href` is the active app route.
 * Uses SvelteKit `$page.route.id` + `$page.url.pathname` — both update on client-side nav.
 * Do NOT read `window.location`; it is not reactive and can lag behind the page store.
 */
export function isNavItemActive(
  pathname: string,
  href: string,
  routeId?: string | null,
): boolean {
  if (routeId && matchNavPath(routeId, href)) return true;
  return matchNavPath(normalizePathname(pathname), href);
}
