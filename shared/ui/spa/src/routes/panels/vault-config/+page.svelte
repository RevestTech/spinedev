<!--
  Spine Hub SPA — Vault config panel (V3 Wave 3 part 2, Squad SPA2).

  Surfaces backend at shared/api/routes/vault_config.py (NOTE: backend
  prefix is /api/v2/vault, not /api/v2/vault-config — the panel slug
  /panels/vault-config maps to the surface label, not the API path):

    GET  /api/v2/vault/status            → VaultStatusResponse
    GET  /api/v2/vault/secrets?prefix=   → VaultSecretList  (hub-admin)
    POST /api/v2/vault/rotate            → RotateResponse   (hub-admin)

  Per design decisions:
    - #3 one of the 9 enumerated Hub surfaces
    - #9 vault-only secrets — VAULT PATHS ONLY, never VALUES
    - #11 hub-admin only for mutating actions

  WARN banner if the adapter kind looks like an InMemoryAdapter. The
  backend reports adapter kind via `type(adapter).__name__`, so we
  pattern-match on common dev / test names.

  Backend gap (filed to report): /vault/status does not expose
  last-rotation timestamps per vault path. The panel renders a "—" until
  the backend adds that field.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { api } from '$lib/api/client';
  import type {
    VaultStatusResponse,
    VaultSecretList,
    RotateResponse,
    RotateRequest
  } from '$lib/api/types';

  let loadingStatus = true;
  let loadingPaths = true;
  let statusError: string | null = null;
  let pathsError: string | null = null;

  let status: VaultStatusResponse | null = null;
  let paths: string[] = [];
  let prefix = '';

  let rotating: string | null = null;
  let lastRotation: Record<string, string> = {};

  function isInMemory(kind: string): boolean {
    const k = kind.toLowerCase();
    return k.includes('inmemory') || k.includes('memory') || k === 'dict';
  }

  async function loadStatus() {
    loadingStatus = true;
    statusError = null;
    try {
      status = await api.get<VaultStatusResponse>('/api/v2/vault/status');
    } catch (err) {
      statusError = (err as Error).message || 'failed to load vault status';
      status = null;
    } finally {
      loadingStatus = false;
    }
  }

  async function loadPaths() {
    loadingPaths = true;
    pathsError = null;
    try {
      const qp = prefix ? `?prefix=${encodeURIComponent(prefix)}` : '';
      const res = await api.get<VaultSecretList>(`/api/v2/vault/secrets${qp}`);
      paths = res.paths ?? [];
    } catch (err) {
      pathsError = (err as Error).message || 'failed to list vault paths';
      paths = [];
    } finally {
      loadingPaths = false;
    }
  }

  async function rotate(path: string) {
    const reason = typeof window === 'undefined'
      ? 'manual rotation via SPA'
      : (window.prompt(`Rotation reason for ${path}?`) ?? '');
    if (!reason) return;
    if (typeof window !== 'undefined' && !window.confirm(`Rotate ${path}? This is audit-logged.`)) return;
    rotating = path;
    try {
      const body: RotateRequest = { path, reason };
      const res = await api.post<RotateResponse>('/api/v2/vault/rotate', body);
      lastRotation = { ...lastRotation, [path]: res.rotated_at };
    } catch (err) {
      pathsError = `rotate failed: ${(err as Error).message}`;
    } finally {
      rotating = null;
    }
  }

  onMount(() => {
    loadStatus();
    loadPaths();
  });
</script>

<PanelHeader title="Vault config" subtitle="Inspect the active SecretAdapter; rotate vault-managed secrets (hub-admin only)">
  <button type="button" class="btn-ghost" on:click={loadStatus} data-testid="reload-status">
    Reload status
  </button>
  <button type="button" class="btn-ghost" on:click={loadPaths} data-testid="reload-paths">
    Reload paths
  </button>
</PanelHeader>

{#if statusError}
  <div class="mb-4"><ErrorBanner kind="error" message={statusError} onDismiss={() => (statusError = null)} /></div>
{/if}

{#if loadingStatus}
  <div class="mb-4 flex items-center justify-center py-6"><LoadingSpinner label="Loading vault status" /></div>
{:else if status}
  {#if isInMemory(status.adapter_kind)}
    <div class="mb-4" data-testid="inmemory-warning">
      <ErrorBanner
        kind="warning"
        message={`InMemoryAdapter detected (${status.adapter_kind}). This is dev-only — production deployments MUST use a real vault adapter per design decision #9.`}
      />
    </div>
  {/if}

  <section class="panel-card mb-6" aria-label="Vault adapter status" data-testid="status-card">
    <header class="mb-3 flex items-center justify-between gap-2">
      <h2 class="text-base font-semibold text-surface-900 dark:text-surface-50">Adapter status</h2>
      <span
        class="rounded-full px-2 py-0.5 text-xs font-medium text-white"
        class:bg-severity-info={status.healthy}
        class:bg-severity-critical={!status.healthy}
        data-testid="status-health"
      >
        {status.healthy ? 'healthy' : 'unhealthy'}
      </span>
    </header>
    <dl class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
      <div>
        <dt class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">Adapter kind</dt>
        <dd class="font-mono">{status.adapter_kind}</dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">Endpoint</dt>
        <dd class="break-all font-mono">{status.endpoint ?? '—'}</dd>
      </div>
      {#if status.last_error}
        <div class="sm:col-span-2">
          <dt class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">Last error</dt>
          <dd class="text-severity-critical">{status.last_error}</dd>
        </div>
      {/if}
    </dl>
  </section>
{/if}

{#if pathsError}
  <div class="mb-4"><ErrorBanner kind="error" message={pathsError} onDismiss={() => (pathsError = null)} /></div>
{/if}

<section aria-label="Vault path inventory">
  <header class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <h2 class="text-base font-semibold text-surface-900 dark:text-surface-50">
      Vault path inventory
      <span class="ml-1 text-xs font-normal text-surface-700 dark:text-surface-200">(paths only — values never displayed per #9)</span>
    </h2>
    <form class="flex items-end gap-2" on:submit|preventDefault={loadPaths}>
      <label class="flex flex-col gap-1 text-xs">
        <span class="text-surface-700 dark:text-surface-200">Path prefix</span>
        <input
          type="text"
          bind:value={prefix}
          placeholder="spine/"
          class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
          data-testid="path-prefix"
        />
      </label>
      <button type="submit" class="btn-ghost">Apply</button>
    </form>
  </header>

  {#if loadingPaths}
    <div class="flex items-center justify-center py-6"><LoadingSpinner label="Loading vault paths" /></div>
  {:else if paths.length === 0}
    <EmptyState
      title="No vault paths"
      message="The active adapter returned no paths under this prefix. Confirm the adapter is reachable and the prefix is correct."
    />
  {:else}
    <ul class="divide-y divide-surface-200 rounded-md border border-surface-200 bg-white dark:divide-surface-700 dark:border-surface-700 dark:bg-surface-800" data-testid="paths-list">
      {#each paths as p (p)}
        <li class="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:justify-between" data-testid="path-row">
          <div class="min-w-0 flex-1">
            <code class="block break-all font-mono text-sm">{p}</code>
            {#if lastRotation[p]}
              <span class="text-xs text-surface-700 dark:text-surface-200">
                rotated at {lastRotation[p]}
              </span>
            {:else}
              <span class="text-xs text-surface-700/60 dark:text-surface-200/60">
                last rotation: — (backend gap)
              </span>
            {/if}
          </div>
          <button
            type="button"
            class="btn-ghost self-start sm:self-auto"
            on:click={() => rotate(p)}
            disabled={rotating === p}
            data-testid="rotate-button"
          >
            {rotating === p ? 'Rotating…' : 'Rotate'}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>
