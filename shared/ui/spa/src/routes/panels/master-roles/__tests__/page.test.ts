// Spine Hub SPA — Master Roles panel test (V3 Wave 3 part 2, Squad SPA2).
//
// Component-level smoke test mirroring the pattern Squad SPA1 established
// in decision-queue/__tests__/page.test.ts.

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
  return {
    page: readable({ url: new URL('http://localhost/panels/master-roles') })
  };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('MasterRoles page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('loads the registry and renders only master-tier roles by default', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      items: [
        { name: 'director_engineering', tier: 'master', description: 'Master eng director' },
        { name: 'director_devops', tier: 'master', description: 'Master devops director' },
        { name: 'architect', tier: 'project', description: 'System architect' }
      ]
    });
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/v2/registry/roles'));
    const cards = await screen.findAllByTestId('role-card');
    // Only the two master-tier cards should render by default.
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute('data-role-tier', 'master');
    expect(screen.queryByTestId('project-roles-section')).toBeNull();
  });

  it('reveals project roles when the toggle is checked', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      items: [
        { name: 'director_security', tier: 'master', description: 'Master security director' },
        { name: 'qa', tier: 'project', description: 'Quality assurance' }
      ]
    });
    render(Page);
    await screen.findAllByTestId('role-card');
    const toggle = screen.getByTestId('toggle-project-roles');
    await fireEvent.click(toggle);
    expect(await screen.findByTestId('project-roles-section')).toBeInTheDocument();
    const cards = screen.getAllByTestId('role-card');
    expect(cards.length).toBe(2);
  });

  it('shows an error banner when the API call fails', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'));
    render(Page);
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
