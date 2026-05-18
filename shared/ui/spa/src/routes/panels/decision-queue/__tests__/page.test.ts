// Spine Hub SPA — Decision-queue panel test (V3 Wave 3 part 2, Squad SPA1).
//
// Component-level smoke test: mocks the API client and asserts the panel
// renders the right shapes for empty / populated states + that ack/reject
// dispatch the right HTTP verbs. Heavier user-flow assertions live in the
// Wave 4 Playwright suite (SPA4 deliverable).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';

// Mock the API client BEFORE importing the page component.
vi.mock('$lib/api/client', () => {
  const subscribeSse = vi.fn(() => ({ close: vi.fn() }));
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn()
  };
  return {
    api: apiMock,
    subscribeSse,
    apiFetch: vi.fn(),
    redirectToLogin: vi.fn(),
    setApiBase: vi.fn(),
    getApiBase: vi.fn(() => '')
  };
});

// $app/stores stub: minimal page store so layout-aware components don't fail.
vi.mock('$app/stores', () => {
  const { readable } = require('svelte/store');
  return {
    page: readable({ url: new URL('http://localhost/panels/decision-queue') })
  };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('DecisionQueue page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.post as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('shows empty state when no decisions are pending', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: true, items: [], total: 0 });
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/api/v2/decisions?status=pending'
    ));
    expect(await screen.findByText(/Inbox zero/i)).toBeInTheDocument();
  });

  it('renders pending decision cards', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      total: 1,
      items: [
        {
          decision_id: 'dec-1',
          decision_class: 'approval',
          title: 'Approve refactor of executor.sh',
          body: 'Engineer proposes splitting executor.sh into 3 modules.',
          severity: 'warning',
          actions: ['ack', 'reject'],
          status: 'pending',
          created_at: Math.floor(Date.now() / 1000),
          metadata: {}
        }
      ]
    });
    render(Page);
    const card = await screen.findByTestId('decision-card');
    expect(card).toHaveAttribute('data-decision-id', 'dec-1');
    expect(card).toHaveAttribute('data-severity', 'warning');
    expect(card).toHaveTextContent(/Approve refactor/i);
  });

  it('dispatches POST /ack when the ack button is clicked', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      total: 1,
      items: [
        {
          decision_id: 'dec-9',
          decision_class: 'release',
          title: 'Cut v1.4.5',
          body: '',
          severity: 'info',
          actions: ['ack', 'reject'],
          status: 'pending',
          created_at: Math.floor(Date.now() / 1000),
          metadata: {}
        }
      ]
    });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      decision_id: 'dec-9',
      status: 'acked',
      actor: 'khash@khash.com',
      audit_event_uuid: '00000000-0000-0000-0000-000000000001'
    });
    render(Page);
    const ackBtn = await screen.findByTestId('decision-ack');
    await fireEvent.click(ackBtn);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/v2/decisions/dec-9/ack')
    );
  });

  it('renders Citation chips when metadata.citations is populated (per #12)', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      total: 1,
      items: [
        {
          decision_id: 'dec-cite',
          decision_class: 'policy_change',
          title: 'Adopt cite-or-refuse',
          body: 'Per #12.',
          severity: 'info',
          actions: ['ack', 'reject'],
          status: 'pending',
          created_at: Math.floor(Date.now() / 1000),
          metadata: {
            citations: [
              { type: 'kg_node', ref: 'node:abc123' },
              { type: 'audit_hash', ref: 'deadbeef' }
            ]
          }
        }
      ]
    });
    render(Page);
    await screen.findByTestId('decision-card');
    const chips = await screen.findAllByText(/node:abc123|deadbeef/);
    expect(chips.length).toBeGreaterThanOrEqual(2);
  });
});
