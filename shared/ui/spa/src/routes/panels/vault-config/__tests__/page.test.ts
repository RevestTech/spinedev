// Spine Hub SPA — Vault Config panel test (V3 Wave 3 part 2, Squad SPA2).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';

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
  return { page: readable({ url: new URL('http://localhost/panels/vault-config') }) };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('VaultConfig page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.post as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('loads status and paths, renders both sections', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, adapter_kind: 'VaultAdapter', endpoint: 'https://vault.local:8200', healthy: true })
      .mockResolvedValueOnce({ ok: true, paths: ['spine/postgres/password', 'license/vendor_signing_key'], prefix: '' });
    render(Page);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/v2/vault/status');
      expect(api.get).toHaveBeenCalledWith('/api/v2/vault/secrets');
    });
    expect(await screen.findByTestId('status-card')).toBeInTheDocument();
    const rows = await screen.findAllByTestId('path-row');
    expect(rows).toHaveLength(2);
  });

  it('shows the InMemoryAdapter warning in non-prod adapters', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, adapter_kind: 'InMemoryAdapter', endpoint: null, healthy: true })
      .mockResolvedValueOnce({ ok: true, paths: [], prefix: '' });
    render(Page);
    expect(await screen.findByTestId('inmemory-warning')).toBeInTheDocument();
  });

  it('requires confirm + reason before POSTing rotate', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, adapter_kind: 'VaultAdapter', endpoint: null, healthy: true })
      .mockResolvedValueOnce({ ok: true, paths: ['spine/postgres/password'], prefix: '' });
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('quarterly rotation');
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      path: 'spine/postgres/password',
      rotated_at: '2026-05-18T11:00:00Z',
      actor: 'khash@khash.com',
      audit_event_uuid: 'uuid-rot'
    });

    render(Page);
    const btn = await screen.findByTestId('rotate-button');
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(promptSpy).toHaveBeenCalled();
      expect(confirmSpy).toHaveBeenCalled();
      expect(api.post).toHaveBeenCalledWith('/api/v2/vault/rotate', {
        path: 'spine/postgres/password',
        reason: 'quarterly rotation'
      });
    });
    promptSpy.mockRestore();
    confirmSpy.mockRestore();
  });

  it('does not call rotate if the user cancels confirm', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, adapter_kind: 'VaultAdapter', endpoint: null, healthy: true })
      .mockResolvedValueOnce({ ok: true, paths: ['spine/postgres/password'], prefix: '' });
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('quarterly rotation');
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(Page);
    const btn = await screen.findByTestId('rotate-button');
    await fireEvent.click(btn);
    expect(api.post).not.toHaveBeenCalled();
    promptSpy.mockRestore();
    confirmSpy.mockRestore();
  });
});
