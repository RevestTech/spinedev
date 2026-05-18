// Spine Hub SPA — Audit panel test (V3 Wave 3 part 2, Squad SPA2).

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
  return { page: readable({ url: new URL('http://localhost/panels/audit') }) };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

const SAMPLE = {
  ok: true,
  limit: 500,
  project_id: 'proj-1',
  items: [
    JSON.stringify({
      event_id: 1,
      event_uuid: 'uuid-1',
      ts: '2026-05-18T10:00:00Z',
      project_id: 'proj-1',
      role: 'architect',
      subsystem: 'plan',
      action: 'review',
      subject_type: 'epic',
      subject_id: 'EPIC-1',
      actor: 'khash@khash.com',
      content_hash: 'aaa',
      prev_content_hash: null
    }),
    JSON.stringify({
      event_id: 2,
      event_uuid: 'uuid-2',
      ts: '2026-05-18T10:05:00Z',
      project_id: 'proj-1',
      role: 'qa',
      subsystem: 'verify',
      action: 'cite_or_refuse',
      subject_type: 'tool_call',
      subject_id: 'tc-9',
      actor: 'khash@khash.com',
      content_hash: 'bbb',
      prev_content_hash: 'aaa'
    })
  ]
};

describe('Audit page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('renders an empty state until a scope key is provided', () => {
    render(Page);
    expect(screen.getByText(/requires at least one scope key/i)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });

  it('loads audit rows once a project_id is set and Load is clicked', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(SAMPLE);
    render(Page);
    const projInput = screen.getByTestId('filter-project') as HTMLInputElement;
    await fireEvent.input(projInput, { target: { value: 'proj-1' } });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const call = (api.get as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(call).toContain('/api/v2/audit?');
    expect(call).toContain('project_id=proj-1');
    const rows = await screen.findAllByTestId('audit-row');
    expect(rows).toHaveLength(2);
  });

  it('applies client-side subsystem filter', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(SAMPLE);
    render(Page);
    await fireEvent.input(screen.getByTestId('filter-project'), { target: { value: 'proj-1' } });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await screen.findAllByTestId('audit-row');
    const subFilter = screen.getByTestId('filter-subsystem') as HTMLSelectElement;
    await fireEvent.change(subFilter, { target: { value: 'verify' } });
    const remaining = screen.getAllByTestId('audit-row');
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toHaveAttribute('data-subsystem', 'verify');
  });

  it('opens a detail modal on row click', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(SAMPLE);
    render(Page);
    await fireEvent.input(screen.getByTestId('filter-project'), { target: { value: 'proj-1' } });
    await fireEvent.click(screen.getByTestId('audit-load'));
    const [first] = await screen.findAllByTestId('audit-row');
    await fireEvent.click(first);
    expect(await screen.findByTestId('audit-detail')).toBeInTheDocument();
  });

  it('export buttons prompt for confirmation before navigating', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(SAMPLE);
    render(Page);
    await fireEvent.input(screen.getByTestId('filter-project'), { target: { value: 'proj-1' } });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await screen.findAllByTestId('audit-row');
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await fireEvent.click(screen.getByTestId('export-csv'));
    expect(confirmSpy).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
