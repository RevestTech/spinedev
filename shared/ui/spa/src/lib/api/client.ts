// Spine Hub SPA — typed fetch wrapper (V3 Wave 3 part 2, Squad SPA1).
//
// Cookie-based auth (per shared/api/middleware/oidc.py): every request
// includes credentials so the signed `spine_sid` cookie travels with the
// call. The middleware translates the cookie into an Authorization Bearer
// header before the dependency graph runs, so the SPA never holds the
// access token itself.
//
// On 401: redirect to /api/v2/auth/login so Keycloak (per #25) drives the
// auth-code flow; on success Keycloak posts back to /api/v2/auth/callback
// which sets the cookie and 302s back to the SPA root.
//
// SSE: `subscribeSse` opens an EventSource against a POST endpoint — note
// EventSource only supports GET, so we use fetch + ReadableStream parsing
// to handle the backend's POST /api/v2/decisions/subscribe contract.

import { ApiError, type ApiErrorDetail } from './types';

const DEFAULT_BASE = ''; // same-origin; SPA + API served by Hub container.

/** Override only for tests / Storybook / non-default deployment shapes. */
let API_BASE = DEFAULT_BASE;

export function setApiBase(base: string): void {
  API_BASE = base.replace(/\/+$/, '');
}

export function getApiBase(): string {
  return API_BASE;
}

export interface FetchOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  /** When false, do NOT redirect to /auth/login on a 401. Default: true. */
  redirectOn401?: boolean;
  /** Per-call timeout in milliseconds. Default 30s. */
  timeoutMs?: number;
}

/** Build the absolute URL for an API path. */
function urlFor(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  if (!path.startsWith('/')) path = '/' + path;
  return `${API_BASE}${path}`;
}

/**
 * Redirect the browser to the Keycloak login flow.
 *
 * Exposed as a separate function so tests can stub it and the 401 path can
 * be exercised without navigating the test runner away.
 */
export function redirectToLogin(): void {
  // Preserve the pre-auth path so the SPA can deep-link back after login.
  // (Wave 3 part 2 keeps it client-side via sessionStorage; Wave 4 wires
  // the `state` param through the Keycloak round-trip.)
  if (typeof window !== 'undefined') {
    try {
      sessionStorage.setItem('spine.post_login_target', window.location.pathname + window.location.search);
    } catch {
      // best-effort; private mode may block storage.
    }
    window.location.assign(`${API_BASE}/api/v2/auth/login`);
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: ApiErrorDetail | string;
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    detail = (body && typeof body === 'object' && 'detail' in body)
      ? (body.detail as ApiErrorDetail | string)
      : (body as ApiErrorDetail);
  } catch {
    detail = text || response.statusText;
  }
  return new ApiError(response.status, detail);
}

/** Human-readable message for store error banners. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/** True for intentional fetch/SSE aborts (timeout, navigation, reconnect). */
export function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const e = err as { name?: string; message?: string };
  if (e.name === 'AbortError') return true;
  const msg = e.message ?? '';
  return /aborted/i.test(msg);
}

/**
 * Core fetch wrapper. Returns parsed JSON on 2xx; throws `ApiError` on >= 400.
 *
 * On 401 (when redirectOn401 is true, the default): triggers the Keycloak
 * login redirect BEFORE the promise rejects, so the calling component never
 * has to handle the unauth case explicitly.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const {
    body,
    headers: extraHeaders,
    redirectOn401 = true,
    timeoutMs = 30_000,
    ...rest
  } = options;

  const controller = new AbortController();
  const timer = (typeof setTimeout !== 'undefined')
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null;

  const headers = new Headers(extraHeaders ?? {});
  let payload: BodyInit | undefined;
  if (body !== undefined && body !== null) {
    if (body instanceof FormData || body instanceof Blob || typeof body === 'string') {
      payload = body as BodyInit;
    } else {
      payload = JSON.stringify(body);
      if (!headers.has('content-type')) headers.set('content-type', 'application/json');
    }
  }
  if (!headers.has('accept')) headers.set('accept', 'application/json');

  let response: Response;
  try {
    response = await fetch(urlFor(path), {
      ...rest,
      headers,
      body: payload,
      credentials: 'include', // ship the signed spine_sid cookie
      signal: rest.signal ?? controller.signal
    });
  } catch (err) {
    if (isAbortError(err)) {
      throw new ApiError(408, {
        error_code: 'request_timeout',
        message: 'Request timed out — if you just started a role, check Live activity and refresh.',
      });
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (response.status === 401) {
    if (redirectOn401) redirectToLogin();
    throw new ApiError(401, 'unauthorized');
  }
  if (!response.ok) throw await parseError(response);

  if (response.status === 204) return undefined as T;
  const ct = response.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

// ---------------------------------------------------------------------------
// Convenience verb wrappers
// ---------------------------------------------------------------------------

export const api = {
  get: <T>(path: string, opts?: FetchOptions) =>
    apiFetch<T>(path, { ...opts, method: 'GET' }),
  post: <T>(path: string, body?: unknown, opts?: FetchOptions) =>
    apiFetch<T>(path, { ...opts, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, opts?: FetchOptions) =>
    apiFetch<T>(path, { ...opts, method: 'PATCH', body }),
  delete: <T>(path: string, opts?: FetchOptions) =>
    apiFetch<T>(path, { ...opts, method: 'DELETE' })
};

// ---------------------------------------------------------------------------
// SSE: POST /api/v2/decisions/subscribe
// ---------------------------------------------------------------------------

export interface SseSubscription {
  close(): void;
}

export interface SseHandlers<E = unknown> {
  onEvent: (event: { type: string; data: E }) => void;
  onError?: (err: unknown) => void;
  /** Fired when the server closes the stream without an error (or after EOF). */
  onClose?: () => void;
  onOpen?: () => void;
}

/**
 * Open a POST-driven SSE stream. EventSource forces GET, so we hand-parse
 * the `text/event-stream` frames over fetch + ReadableStream.
 *
 * Returns a subscription handle whose `close()` aborts the underlying
 * request — every panel that subscribes MUST call close on unmount.
 */
export function subscribeSse<E = unknown>(
  path: string,
  handlers: SseHandlers<E>,
  options: { body?: unknown; redirectOn401?: boolean } = {}
): SseSubscription {
  const controller = new AbortController();
  let closed = false;
  const headers = new Headers({ accept: 'text/event-stream' });
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    body = JSON.stringify(options.body);
    headers.set('content-type', 'application/json');
  }

  (async () => {
    try {
      const resp = await fetch(urlFor(path), {
        method: 'POST',
        headers,
        body,
        credentials: 'include',
        signal: controller.signal
      });
      if (resp.status === 401) {
        if (options.redirectOn401 !== false) redirectToLogin();
        throw new ApiError(401, 'unauthorized');
      }
      if (!resp.ok || !resp.body) {
        throw await parseError(resp);
      }
      handlers.onOpen?.();
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line.
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const parsed = parseSseFrame<E>(frame);
          if (parsed) handlers.onEvent(parsed);
        }
      }
      if (!closed) handlers.onClose?.();
    } catch (err) {
      if (closed || isAbortError(err)) return;
      handlers.onError?.(err);
    }
  })();

  return {
    close: () => {
      closed = true;
      controller.abort('close');
    }
  };
}

function parseSseFrame<E>(frame: string): { type: string; data: E } | null {
  let type = 'message';
  const dataLines: string[] = [];
  for (const raw of frame.split('\n')) {
    const line = raw.trimEnd();
    if (!line || line.startsWith(':')) continue;
    const sep = line.indexOf(':');
    const field = sep === -1 ? line : line.slice(0, sep);
    const value = sep === -1 ? '' : line.slice(sep + 1).replace(/^ /, '');
    if (field === 'event') type = value;
    else if (field === 'data') dataLines.push(value);
  }
  if (dataLines.length === 0) return null;
  const joined = dataLines.join('\n');
  try {
    return { type, data: JSON.parse(joined) as E };
  } catch {
    return { type, data: joined as unknown as E };
  }
}
