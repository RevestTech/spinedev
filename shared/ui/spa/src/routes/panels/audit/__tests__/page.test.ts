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

function mockProjectsSeed(projectId = 'proj-1') {
  (api.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url.includes('/api/v2/projects')) {
      return Promise.resolve({
        items: [{ project_id: '9', project_uuid: projectId }]
      });
    }
    if (url.includes('/api/v2/audit')) {
      return Promise.resolve(SAMPLE);
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe('Audit page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('seeds project_id from the projects API on mount', async () => {
    mockProjectsSeed('seed-proj');
    render(Page);
    const projInput = screen.getByTestId('filter-project') as HTMLInputElement;
    await waitFor(() => expect(projInput.value).toBe('seed-proj'));
    expect(api.get).toHaveBeenCalledWith('/api/v2/projects?limit=1');
  });

  it('loads audit rows once Load is clicked with a project_id', async () => {
    mockProjectsSeed('proj-1');
    render(Page);
    await waitFor(() => {
      expect((screen.getByTestId('filter-project') as HTMLInputElement).value).toBe('proj-1');
    });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await waitFor(() =>
      expect((api.get as ReturnType<typeof vi.fn>).mock.calls.some((c) =>
        String(c[0]).includes('/api/v2/audit?')
      )).toBe(true)
    );
    const auditCall = (api.get as ReturnType<typeof vi.fn>).mock.calls.find((c) =>
      String(c[0]).includes('/api/v2/audit?')
    )?.[0] as string;
    expect(auditCall).toContain('project_id=proj-1');
    const rows = await screen.findAllByTestId('audit-row');
    expect(rows).toHaveLength(2);
  });

  it('applies client-side subsystem filter', async () => {
    mockProjectsSeed('proj-1');
    render(Page);
    await waitFor(() => {
      expect((screen.getByTestId('filter-project') as HTMLInputElement).value).toBe('proj-1');
    });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await screen.findAllByTestId('audit-row');
    const subFilter = screen.getByTestId('filter-subsystem') as HTMLSelectElement;
    await fireEvent.change(subFilter, { target: { value: 'verify' } });
    const remaining = screen.getAllByTestId('audit-row');
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toHaveAttribute('data-subsystem', 'verify');
  });

  it('opens a detail modal on row click', async () => {
    mockProjectsSeed('proj-1');
    render(Page);
    await waitFor(() => {
      expect((screen.getByTestId('filter-project') as HTMLInputElement).value).toBe('proj-1');
    });
    await fireEvent.click(screen.getByTestId('audit-load'));
    const [first] = await screen.findAllByTestId('audit-row');
    await fireEvent.click(first);
    expect(await screen.findByTestId('audit-detail')).toBeInTheDocument();
  });

  it('export buttons prompt for confirmation before navigating', async () => {
    mockProjectsSeed('proj-1');
    render(Page);
    await waitFor(() => {
      expect((screen.getByTestId('filter-project') as HTMLInputElement).value).toBe('proj-1');
    });
    await fireEvent.click(screen.getByTestId('audit-load'));
    await screen.findAllByTestId('audit-row');
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await fireEvent.click(screen.getByTestId('export-csv'));
    expect(confirmSpy).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
