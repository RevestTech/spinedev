// Spine Hub SPA — Integrations panel test (V3 Wave 3 part 2, Squad SPA2).

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
  return { page: readable({ url: new URL('http://localhost/panels/integrations') }) };
});
vi.mock('$app/environment', () => ({ browser: true }));

import { api } from '$lib/api/client';
import { ApiError } from '$lib/api/types';
import Page from '../+page.svelte';

const LIST = {
  ok: true,
  items: [
    { name: 'github', kind: 'scm', status: 'configured', vault_path: 'spine/integrations/github/token', feature_flag: 'integration_github' },
    { name: 'slack', kind: 'comms', status: 'unconfigured', vault_path: 'spine/integrations/slack/bot_token', feature_flag: 'channel_slack' }
  ]
};

describe('Integrations page', () => {
  beforeEach(() => {
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.post as ReturnType<typeof vi.fn>).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it('lists every integration with its status badge', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(LIST);
    render(Page);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/v2/integrations'));
    const cards = await screen.findAllByTestId('integration-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute('data-status', 'configured');
    expect(cards[1]).toHaveAttribute('data-status', 'unconfigured');
  });

  it('runs probe after confirm and records status as failing on unhealthy response', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(LIST);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      name: 'github',
      healthy: false,
      detail: "vault secret missing at 'spine/integrations/github/token'",
      actor: 'khash@khash.com',
      audit_event_uuid: 'uuid-probe'
    });

    render(Page);
    const [first] = await screen.findAllByTestId('probe-button');
    await fireEvent.click(first);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/v2/integrations/github/test-connection')
    );
    // After an unhealthy probe the badge must flip to "failing" via the
    // reactive statusByName derivation (regression guard for the prior
    // {@const}-non-reactivity bug).
    await waitFor(() => {
      const card = screen
        .getAllByTestId('integration-card')
        .find((el) => el.getAttribute('data-integration-name') === 'github');
      expect(card).toHaveAttribute('data-status', 'failing');
    });
    await waitFor(() =>
      expect(screen.getByText(/vault secret missing/i)).toBeInTheDocument()
    );
    confirmSpy.mockRestore();
  });

  it('marks the integration disabled when probe returns 402 feature-flag error', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(LIST);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (api.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(402, { error_code: 'feature_disabled', message: 'requires flag', upgrade_path: '/hub/settings/license' })
    );
    render(Page);
    const [first] = await screen.findAllByTestId('probe-button');
    await fireEvent.click(first);
    // 402 → panel stores probes[name] = { disabled: true, detail: 'requires flag', ... }.
    // Badge must flip to "disabled" (regression guard for the prior
    // {@const}-non-reactivity bug) and the detail cell must surface the
    // upgrade-path message.
    await waitFor(() => {
      const card = screen
        .getAllByTestId('integration-card')
        .find((el) => el.getAttribute('data-integration-name') === 'github');
      expect(card).toHaveAttribute('data-status', 'disabled');
    });
    await waitFor(() =>
      expect(screen.getByText(/requires flag/i)).toBeInTheDocument()
    );
  });

  it('cancelling the confirm does not POST', async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(LIST);
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(Page);
    const [first] = await screen.findAllByTestId('probe-button');
    await fireEvent.click(first);
    expect(api.post).not.toHaveBeenCalled();
  });
});
