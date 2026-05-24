// Spine Hub SPA — Federation panel test (V3 Wave 3 part 2, Squad SPA3).
//
// Mocks the API client and asserts the panel renders parent/peer/child
// rows + register-child form + consent buttons + audit citation chips.

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
    page: readable({ url: new URL('http://localhost/panels/federation') })
  };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('Federation page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.post as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  function mockLoad(hubs: unknown[], posture: unknown, projects: unknown[] = []) {
    (api.get as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/api/v2/federation/hubs') {
        return Promise.resolve({ ok: true, local_hub_id: 'hub-local', items: hubs });
      }
      if (path === '/api/v2/federation/status') {
        return Promise.resolve(posture);
      }
      if (path === '/api/v2/projects?limit=200') {
        return Promise.resolve({ items: projects });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
  }

  it('renders the local Hub posture even with no peers', async () => {
    mockLoad([], { ok: true, local_hub_id: 'hub-local', children_count: 0, peers_count: 0 });
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    expect(await screen.findByTestId('local-hub')).toBeInTheDocument();
    expect(screen.getByText(/No federated Hubs yet/i)).toBeInTheDocument();
  });

  it('renders parent / peer / child tiers with consent badges', async () => {
    mockLoad(
      [
        { hub_id: 'hub-parent', name: 'Parent', role: 'parent', consent: 'accepted' },
        { hub_id: 'hub-peer', name: 'Peer', role: 'peer', consent: 'pending' },
        { hub_id: 'hub-child', name: 'Child', role: 'child', consent: 'pending',
          url: 'https://child.example' }
      ],
      { ok: true, local_hub_id: 'hub-local', parent_hub_id: 'hub-parent',
        children_count: 1, peers_count: 1 }
    );
    render(Page);
    await waitFor(() => expect(screen.getAllByTestId('hub-node').length).toBe(3));
    const nodes = screen.getAllByTestId('hub-node');
    expect(nodes[0]).toHaveAttribute('data-role', 'parent');
    expect(nodes[1]).toHaveAttribute('data-role', 'peer');
    expect(nodes[2]).toHaveAttribute('data-role', 'child');
    // Pending consents surface the approve/reject buttons for peers + cascade for children.
    expect(screen.getByTestId('consent-accept')).toBeInTheDocument();
    expect(screen.getByTestId('cascade-approve')).toBeInTheDocument();
  });

  it('submits the register-child form and surfaces the audit citation', async () => {
    mockLoad([], { ok: true, local_hub_id: 'hub-local', children_count: 0, peers_count: 0 });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      hub_id: 'hub-new',
      actor: 'khash@khash.com',
      audit_event_uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    });
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    await fireEvent.click(screen.getByTestId('toggle-register'));
    await fireEvent.input(screen.getByTestId('form-hub-id'), { target: { value: 'hub-new' } });
    await fireEvent.input(screen.getByTestId('form-name'), { target: { value: 'New Hub' } });
    await fireEvent.input(screen.getByTestId('form-url'), { target: { value: 'https://new.example' } });
    await fireEvent.input(screen.getByTestId('form-rationale'), { target: { value: 'why' } });

    // Second load() after submit triggers two more api.get calls.
    mockLoad([], { ok: true, local_hub_id: 'hub-local', children_count: 1, peers_count: 0 });
    await fireEvent.click(screen.getByTestId('form-submit'));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/api/v2/federation/register-child',
        expect.objectContaining({ hub_id: 'hub-new', rationale: 'why' })
      )
    );
    // Per #12 — audit_event_uuid renders as a CitationChip.
    await waitFor(() =>
      expect(screen.getByText(/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/)).toBeInTheDocument()
    );
  });
});
