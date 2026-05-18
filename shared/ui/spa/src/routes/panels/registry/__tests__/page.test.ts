// Spine Hub SPA — Registry panel test (V3 Wave 3 part 2, Squad SPA2).

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
  return { page: readable({ url: new URL('http://localhost/panels/registry') }) };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

const ROLES = {
  ok: true,
  items: [
    { name: 'architect', tier: 'project', description: 'System architecture', charter_ref: 'lib/role-prompts/architect.md' },
    { name: 'director_engineering', tier: 'master', description: 'Master eng director' }
  ]
};
const INTEGS = {
  ok: true,
  items: [
    { name: 'github', kind: 'scm', description: 'GitHub repo + Actions', requires_vault_path: 'spine/integrations/github/token', feature_flag: 'integration_github' },
    { name: 'slack', kind: 'comms', description: 'Slack notifications', requires_vault_path: 'spine/integrations/slack/bot_token', feature_flag: 'channel_slack' }
  ]
};

describe('Registry page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('loads both endpoints and renders combined catalog', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(ROLES)
      .mockResolvedValueOnce(INTEGS);
    render(Page);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/v2/registry/roles');
      expect(api.get).toHaveBeenCalledWith('/api/v2/registry/integrations');
    });
    const items = await screen.findAllByTestId('registry-item');
    expect(items).toHaveLength(4);
  });

  it('filters by category — integrations hides role entries', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(ROLES)
      .mockResolvedValueOnce(INTEGS);
    render(Page);
    await screen.findAllByTestId('registry-item');
    const cat = screen.getByTestId('registry-category') as HTMLSelectElement;
    await fireEvent.change(cat, { target: { value: 'integrations' } });
    expect(screen.queryByTestId('roles-section')).toBeNull();
    const items = screen.getAllByTestId('registry-item');
    expect(items.every((el) => el.getAttribute('data-entry-kind') === 'integration')).toBe(true);
  });

  it('search narrows to matching entries', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(ROLES)
      .mockResolvedValueOnce(INTEGS);
    render(Page);
    await screen.findAllByTestId('registry-item');
    const search = screen.getByTestId('registry-search') as HTMLInputElement;
    await fireEvent.input(search, { target: { value: 'github' } });
    const items = screen.getAllByTestId('registry-item');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent(/github/i);
  });

  it('never renders raw vault secret values — only paths', async () => {
    (api.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(ROLES)
      .mockResolvedValueOnce(INTEGS);
    const { container } = render(Page);
    await screen.findAllByTestId('registry-item');
    // Vault paths render with the "vault:" prefix; no key=value pairs.
    expect(container.textContent).toContain('vault: spine/integrations/github/token');
    expect(container.textContent).not.toMatch(/ghp_[A-Za-z0-9]+/);
  });
});
