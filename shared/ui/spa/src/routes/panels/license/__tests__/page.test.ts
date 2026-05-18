// Spine Hub SPA — License panel test (V3 Wave 3 part 2, Squad SPA3).
//
// Asserts the tier/bundle/signature rendering + per-flag matrix + the
// upgrade-tier CTA + citation chip per #12.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api/client', () => {
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn()
  };
  return {
    api: apiMock,
    subscribeSse: vi.fn(() => ({ close: vi.fn() })),
    apiFetch: vi.fn(),
    redirectToLogin: vi.fn(),
    setApiBase: vi.fn(),
    getApiBase: vi.fn(() => '')
  };
});

vi.mock('$app/stores', () => {
  const { readable } = require('svelte/store');
  return {
    page: readable({ url: new URL('http://localhost/panels/license') })
  };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('License page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  function mockLoad(summary: unknown, usage: unknown) {
    (api.get as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/api/v2/license') return Promise.resolve(summary);
      if (path === '/api/v2/license/usage') return Promise.resolve(usage);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
  }

  it('renders tier + bundle + signature status + flag rows', async () => {
    mockLoad(
      {
        ok: true,
        tier: 'team',
        bundle_id: 'bundle-xyz',
        expires_at: '2027-01-01T00:00:00Z',
        signed: false,
        flags: [
          { flag: 'federation', enabled: true },
          { flag: 'role_release_manager', enabled: false }
        ],
        citation: 'shared/api/routes/license.py:_TIER'
      },
      {
        ok: true,
        items: [
          { flag: 'federation', count: 4 },
          { flag: 'role_release_manager', count: 0 }
        ],
        citation: 'shared/api/routes/license.py:license_usage'
      }
    );
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId('tier-label')).toHaveTextContent(/team/i);
    expect(screen.getByTestId('signature-status')).toHaveTextContent(/unverified/i);
    const rows = screen.getAllByTestId('flag-row');
    expect(rows.length).toBe(2);
    // First row enabled, second row disabled & shows upgrade CTA.
    expect(rows[0]).toHaveAttribute('data-enabled', 'true');
    expect(rows[1]).toHaveAttribute('data-enabled', 'false');
    expect(screen.getByTestId('upgrade-cta')).toHaveAttribute(
      'href',
      expect.stringMatching(/mailto:sales@spine\.app/)
    );
  });

  it('renders a CitationChip for the bundle reference (per #12)', async () => {
    mockLoad(
      {
        ok: true,
        tier: 'free',
        bundle_id: 'bundle-stub',
        expires_at: '2027-01-01T00:00:00Z',
        signed: true,
        flags: [{ flag: 'federation', enabled: false }],
        citation: 'shared/api/routes/license.py:42'
      },
      { ok: true, items: [{ flag: 'federation', count: 0 }], citation: null }
    );
    render(Page);
    await waitFor(() => expect(screen.getByTestId('signature-status')).toBeInTheDocument());
    // Citation ref is rendered inside the chip.
    expect(await screen.findByText(/shared\/api\/routes\/license\.py:42/)).toBeInTheDocument();
  });
});
