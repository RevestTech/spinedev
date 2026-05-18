<!--
  Spine Hub SPA — Integrations panel (V3 Wave 3 part 2, Squad SPA2).

  Surfaces backend at shared/api/routes/integrations.py:
    GET  /api/v2/integrations                         → IntegrationListResponse
    POST /api/v2/integrations/{name}/test-connection  → TestConnectionResponse (hub-admin)

  Per design decisions:
    - #3 one of the 9 enumerated Hub surfaces
    - #9 vault PATHS only, never VALUES
    - #11 hub-admin gates the test-connection probe
    - #23 feature-flag licensing — backend returns 402 with upgrade_path
         when a flag is disabled; we surface that via the ErrorBanner

  Notes:
    - Backend currently exposes 'configured' / 'unconfigured' / 'error' but
      not the "disabled-by-feature-flag" status the panel scope mentions.
      We infer "disabled" client-side when feature_flag is set AND a probe
      returns 402 (caught + remapped). Flagged in the report.
    - Probe responses are stored per-name so the row reflects the most
      recent test outcome without a full reload.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { api } from '$lib/api/client';
  import { ApiError } from '$lib/api/types';
  import type {
    IntegrationDetail,
    IntegrationListResponse,
    TestConnectionResponse
  } from '$lib/api/types';

  let loading = true;
  let error: string | null = null;
  let items: IntegrationDetail[] = [];
  let probing: string | null = null;
  let probes: Record<string, { healthy: boolean; detail: string; ts: string; disabled?: boolean }> = {};

  async function load() {
    loading = true;
    error = null;
    try {
      const res = await api.get<IntegrationListResponse>('/api/v2/integrations');
      items = res.items ?? [];
    } catch (err) {
      error = (err as Error).message || 'failed to load integrations';
      items = [];
    } finally {
      loading = false;
    }
  }

  async function probe(name: string) {
    if (typeof window !== 'undefined' && !window.confirm(`Run a connectivity probe against "${name}"? This call is audit-logged.`)) {
      return;
    }
    probing = name;
    try {
      const res = await api.post<TestConnectionResponse>(`/api/v2/integrations/${encodeURIComponent(name)}/test-connection`);
      probes = {
        ...probes,
        [name]: { healthy: res.healthy, detail: res.detail, ts: new Date().toISOString() }
      };
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        probes = {
          ...probes,
          [name]: {
            healthy: false,
            detail: typeof err.detail === 'object' ? (err.detail.message ?? 'feature flag disabled') : String(err.detail),
            ts: new Date().toISOString(),
            disabled: true
          }
        };
      } else {
        probes = {
          ...probes,
          [name]: { healthy: false, detail: (err as Error).message || 'probe failed', ts: new Date().toISOString() }
        };
      }
    } finally {
      probing = null;
    }
  }

  function effectiveStatus(it: IntegrationDetail): 'configured' | 'unconfigured' | 'failing' | 'disabled' {
    const last = probes[it.name];
    if (last?.disabled) return 'disabled';
    if (last && !last.healthy) return 'failing';
    if (it.status === 'configured') return 'configured';
    return 'unconfigured';
  }

  const STATUS_TONE: Record<'configured' | 'unconfigured' | 'failing' | 'disabled', string> = {
    configured: 'bg-severity-info text-white',
    unconfigured: 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200',
    failing: 'bg-severity-critical text-white',
    disabled: 'bg-severity-warning text-white'
  };

  onMount(load);
</script>

<PanelHeader title="Integrations" subtitle="External systems wired into this Hub — GitHub, Linear, Slack, PagerDuty, Vanta, …">
  <button type="button" class="btn-ghost" on:click={load} data-testid="reload-integrations">
    Refresh
  </button>
</PanelHeader>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading integrations" /></div>
{:else if items.length === 0}
  <EmptyState
    title="No integrations registered"
    message="The bundle did not advertise any integrations under /api/v2/integrations."
  />
{:else}
  <ul
    class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
    data-testid="integrations-list"
  >
    {#each items as it (it.name)}
      {@const eff = effectiveStatus(it)}
      {@const last = probes[it.name]}
      <li
        class="panel-card flex flex-col gap-2"
        data-testid="integration-card"
        data-integration-name={it.name}
        data-status={eff}
      >
        <header class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <h2 class="break-words text-base font-semibold text-surface-900 dark:text-surface-50">
              {it.name}
            </h2>
            <span class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
              {it.kind}
            </span>
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium {STATUS_TONE[eff]}"
            data-testid="integration-status"
          >
            {eff}
          </span>
        </header>

        <dl class="grid grid-cols-1 gap-1 text-xs text-surface-700 dark:text-surface-200">
          {#if it.vault_path}
            <div class="flex justify-between gap-2">
              <dt>Vault path</dt>
              <dd class="truncate font-mono" title={it.vault_path}>{it.vault_path}</dd>
            </div>
          {/if}
          {#if it.feature_flag}
            <div class="flex justify-between gap-2">
              <dt>Feature flag</dt>
              <dd class="truncate font-mono">{it.feature_flag}</dd>
            </div>
          {/if}
          {#if last}
            <div class="flex justify-between gap-2">
              <dt>Last probe</dt>
              <dd class="truncate font-mono">{new Date(last.ts).toLocaleString()}</dd>
            </div>
            <div class="flex justify-between gap-2">
              <dt>Detail</dt>
              <dd class="truncate" title={last.detail}>{last.detail}</dd>
            </div>
          {/if}
        </dl>

        <footer class="mt-auto flex items-center justify-end gap-2 border-t border-surface-200 pt-3 dark:border-surface-700">
          <button
            type="button"
            class="btn-primary"
            on:click={() => probe(it.name)}
            disabled={probing === it.name}
            data-testid="probe-button"
          >
            {probing === it.name ? 'Probing…' : 'Test connection'}
          </button>
        </footer>
      </li>
    {/each}
  </ul>
{/if}
