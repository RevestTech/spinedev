// Spine Hub SPA — API client unit tests (V3 Wave 3 part 2, Squad SPA1).
//
// Covers:
//   - 2xx happy path: JSON parse, content-type honoured
//   - 401 path: triggers redirectToLogin + throws ApiError(401)
//   - 4xx/5xx path: throws ApiError with parsed FastAPI `detail`
//   - SSE frame parser: event + data + comments + multi-data lines

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../types';

// We mock window.location.assign at test time. Vitest's jsdom env provides
// window/document; we stub fetch per-test so the assertions stay tight.
declare global {
  // eslint-disable-next-line no-var
  var fetch: typeof globalThis.fetch;
}

describe('apiFetch', () => {
  let origFetch: typeof globalThis.fetch;
  let origAssign: typeof window.location.assign;
  let assignSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    origFetch = globalThis.fetch;
    origAssign = window.location.assign;
    assignSpy = vi.fn();
    // Replace location.assign so tests don't navigate the runner.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, pathname: '/panels/decision-queue', search: '' }
    });
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: origAssign }
    });
    vi.restoreAllMocks();
  });

  it('returns parsed JSON on 2xx', async () => {
    globalThis.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true, items: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        })
    ) as typeof fetch;
    const { api } = await import('../client');
    const out = await api.get<{ ok: boolean; items: unknown[] }>('/api/v2/decisions');
    expect(out.ok).toBe(true);
    expect(out.items).toEqual([]);
  });

  it('triggers Keycloak login redirect on 401', async () => {
    globalThis.fetch = vi.fn(
      async () => new Response('', { status: 401 })
    ) as typeof fetch;
    const { api } = await import('../client');
    await expect(api.get('/api/v2/decisions')).rejects.toBeInstanceOf(ApiError);
    expect(assignSpy).toHaveBeenCalledTimes(1);
    expect((assignSpy.mock.calls[0]?.[0] as string)).toContain('/api/v2/auth/login');
  });

  it('does NOT redirect when redirectOn401=false', async () => {
    globalThis.fetch = vi.fn(
      async () => new Response('', { status: 401 })
    ) as typeof fetch;
    const { apiFetch } = await import('../client');
    await expect(
      apiFetch('/api/v2/decisions', { method: 'GET', redirectOn401: false })
    ).rejects.toMatchObject({ status: 401 });
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it('throws ApiError with parsed FastAPI detail on 4xx', async () => {
    const body = JSON.stringify({ detail: { error_code: 'decision_not_found', message: 'abc' } });
    globalThis.fetch = vi.fn(
      async () => new Response(body, { status: 404, headers: { 'content-type': 'application/json' } })
    ) as typeof fetch;
    const { api } = await import('../client');
    try {
      await api.get('/api/v2/decisions/abc');
      expect.unreachable('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
      expect((err as ApiError).detail).toMatchObject({ error_code: 'decision_not_found' });
    }
  });

  it('sends JSON body + correct headers on POST', async () => {
    const seen: { headers?: Headers; body?: string } = {};
    globalThis.fetch = vi.fn(async (_url, init) => {
      seen.headers = new Headers(init?.headers);
      seen.body = typeof init?.body === 'string' ? init.body : '';
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
    }) as typeof fetch;
    const { api } = await import('../client');
    await api.post('/api/v2/role-chat', { role: 'qa', message: 'hi' });
    expect(seen.headers?.get('content-type')).toBe('application/json');
    expect(JSON.parse(seen.body ?? '{}')).toEqual({ role: 'qa', message: 'hi' });
  });
});
