// Spine Hub SPA — KG Search panel test (V3 Wave 3 part 2, Squad SPA3).
//
// Asserts: search submit hits /api/v2/kg/search, results render with
// citation chips, click → loads /api/v2/kg/node/{id}, action buttons
// dispatch the right backend endpoints.

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
    page: readable({ url: new URL('http://localhost/panels/kg-search') })
  };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import Page from '../+page.svelte';

describe('KgSearch page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.post as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  function mockProjects() {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [{ project_id: 'demo', name: 'spine' }]
    });
  }

  it('runs a search and renders KG-node citation chips on each result', async () => {
    mockProjects();
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      query: 'executor',
      total: 2,
      query_latency_ms: 42,
      citations: [
        { type: 'kg_node', ref: 'node-1' },
        { type: 'kg_node', ref: 'node-2' }
      ],
      results: [
        { node_id: 'node-1', name: 'executor.run', node_type: 'Function',
          path: 'lib/executor.sh:42', score: 0.91, rationale: 'name match' },
        { node_id: 'node-2', name: 'Executor', node_type: 'Class',
          path: 'lib/executor.sh:1', score: 0.55, rationale: 'neighbour' }
      ]
    });
    render(Page);
    await waitFor(() => expect(screen.getByTestId('project-id')).toHaveValue('demo'));
    await fireEvent.input(screen.getByTestId('search-input'), { target: { value: 'executor' } });
    await fireEvent.click(screen.getByTestId('search-submit'));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/v2/kg/search?q=executor'))
    );
    const rows = await screen.findAllByTestId('result-row');
    expect(rows.length).toBe(2);
    expect(rows[0]).toHaveAttribute('data-node-id', 'node-1');
    // Per #12 — kg_node citation chips appear inline (>=2: one per row).
    const chips = await screen.findAllByText(/node-1|node-2/);
    expect(chips.length).toBeGreaterThanOrEqual(2);
  });

  it('loads node detail on result click', async () => {
    mockProjects();
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      query: 'x',
      total: 1,
      query_latency_ms: 1,
      citations: [{ type: 'kg_node', ref: 'n-1' }],
      results: [{ node_id: 'n-1', name: 'foo', node_type: 'Function', path: 'a.py:1',
                  score: 0.5, rationale: '' }]
    });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      node_id: 'n-1',
      node: { node_id: 'n-1', name: 'foo', node_type: 'Function', path: 'a.py:1', score: 0 },
      neighbors: [
        { node_id: 'n-2', name: 'bar', node_type: 'Function', path: 'a.py:10', score: 0 }
      ],
      edges: [{ from_node_id: 'n-1', to_node_id: 'n-2', edge_type: 'CALLS' }],
      citations: [
        { type: 'kg_node', ref: 'n-1' },
        { type: 'kg_node', ref: 'n-2' }
      ]
    });
    render(Page);
    await waitFor(() => expect(screen.getByTestId('project-id')).toHaveValue('demo'));
    await fireEvent.input(screen.getByTestId('search-input'), { target: { value: 'x' } });
    await fireEvent.click(screen.getByTestId('search-submit'));
    const row = await screen.findByTestId('result-row');
    await fireEvent.click(row);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/v2/kg/node/n-1'))
    );
    expect(await screen.findByTestId('node-detail')).toBeInTheDocument();
    expect(screen.getByTestId('neighbor-list')).toHaveTextContent(/bar/);
  });

  it('dispatches the impact_radius action', async () => {
    mockProjects();
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true, query: 'y', total: 1, query_latency_ms: 1, citations: [],
      results: [{ node_id: 'n-9', name: 'thing', node_type: 'Function', path: 'lib/x.py:1',
                  score: 1, rationale: '' }]
    });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true, node_id: 'n-9', node: null, neighbors: [], edges: [], citations: []
    });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      target: 'lib/x.py:1',
      impacted: [{ node_id: 'n-99', node_type: 'TestCase', path: 't.py',
                   impact_distance: 1, impact_kind: 'test' }],
      direct_caller_count: 0, direct_test_count: 1,
      importer_count: 0, total_impact: 1,
      citations: [{ type: 'kg_node', ref: 'n-99' }]
    });
    render(Page);
    await waitFor(() => expect(screen.getByTestId('project-id')).toHaveValue('demo'));
    await fireEvent.input(screen.getByTestId('search-input'), { target: { value: 'y' } });
    await fireEvent.click(screen.getByTestId('search-submit'));
    const row = await screen.findByTestId('result-row');
    await fireEvent.click(row);
    await waitFor(() => expect(screen.getByTestId('node-detail')).toBeInTheDocument());
    await fireEvent.click(screen.getByTestId('action-impact'));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/v2/kg/impact/'))
    );
    expect(await screen.findByTestId('impact-result')).toBeInTheDocument();
  });
});
