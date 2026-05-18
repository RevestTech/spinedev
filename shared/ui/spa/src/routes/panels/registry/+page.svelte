<!--
  Spine Hub SPA — Registry panel (V3 Wave 3 part 2, Squad SPA2).

  Surfaces backend at shared/api/routes/registry.py:
    GET /api/v2/registry/roles         → { ok, items: RoleEntry[] }
    GET /api/v2/registry/integrations  → { ok, items: RegistryIntegrationEntry[] }

  Read-only catalog browser. Search across name + description; filter by
  category (roles / integrations / role-charters / cloud-targets).

  Per design decisions:
    - #3 one of the 9 enumerated Hub surfaces
    - #9 vault paths only — never values (we show requires_vault_path metadata)

  Notes:
    - "role-charters" is a derived view (roles that carry a charter_ref)
    - "cloud-targets" is a derived view (integrations with kind === 'cloud')
      Today registry.py does not return any cloud-kind integrations; the
      filter renders an EmptyState in that case — flagged in the report.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { api } from '$lib/api/client';
  import type {
    RoleEntry,
    RoleList,
    RegistryIntegrationEntry,
    RegistryIntegrationList
  } from '$lib/api/types';

  type Category = 'all' | 'roles' | 'integrations' | 'role-charters' | 'cloud-targets';

  let loading = true;
  let error: string | null = null;
  let roles: RoleEntry[] = [];
  let integrations: RegistryIntegrationEntry[] = [];
  let query = '';
  let category: Category = 'all';

  async function load() {
    loading = true;
    error = null;
    try {
      const [r, i] = await Promise.all([
        api.get<RoleList>('/api/v2/registry/roles'),
        api.get<RegistryIntegrationList>('/api/v2/registry/integrations')
      ]);
      roles = r.items ?? [];
      integrations = i.items ?? [];
    } catch (err) {
      error = (err as Error).message || 'failed to load registry';
      roles = [];
      integrations = [];
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function matches(haystack: string, q: string): boolean {
    if (!q) return true;
    return haystack.toLowerCase().includes(q.toLowerCase());
  }

  $: filteredRoles = roles.filter((r) => {
    if (category === 'integrations' || category === 'cloud-targets') return false;
    if (category === 'role-charters' && !r.charter_ref) return false;
    return matches(`${r.name} ${r.description}`, query);
  });

  $: filteredIntegrations = integrations.filter((i) => {
    if (category === 'roles' || category === 'role-charters') return false;
    if (category === 'cloud-targets' && i.kind !== 'cloud') return false;
    return matches(`${i.name} ${i.description} ${i.kind}`, query);
  });

  $: totalShown = filteredRoles.length + filteredIntegrations.length;
</script>

<PanelHeader title="Registry" subtitle="Read-only catalog of roles + integrations advertised by the active bundle">
  <input
    type="search"
    placeholder="Search…"
    bind:value={query}
    class="w-full max-w-xs rounded-md border border-surface-200 bg-white px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800 sm:w-auto"
    aria-label="Search registry"
    data-testid="registry-search"
  />
  <select
    bind:value={category}
    class="rounded-md border border-surface-200 bg-white px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    aria-label="Filter category"
    data-testid="registry-category"
  >
    <option value="all">All categories</option>
    <option value="roles">Roles</option>
    <option value="integrations">Integrations</option>
    <option value="role-charters">Role charters</option>
    <option value="cloud-targets">Cloud targets</option>
  </select>
  <button type="button" class="btn-ghost" on:click={load} aria-label="Refresh registry">
    Refresh
  </button>
</PanelHeader>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading registry" /></div>
{:else if totalShown === 0}
  <EmptyState
    title="No matches"
    message={query ? `Nothing matches "${query}" in ${category}.` : `No entries in ${category}.`}
  />
{:else}
  {#if filteredRoles.length > 0}
    <section aria-label="Roles" class="mb-6" data-testid="roles-section">
      <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-surface-700 dark:text-surface-200">
        Roles ({filteredRoles.length})
      </h2>
      <ul class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {#each filteredRoles as r (`role-${r.name}`)}
          <li class="panel-card flex flex-col gap-1" data-testid="registry-item" data-entry-kind="role">
            <header class="flex items-center justify-between gap-2">
              <h3 class="break-words text-base font-semibold text-surface-900 dark:text-surface-50">
                {r.name}
              </h3>
              <span
                class="rounded-full px-2 py-0.5 text-[0.65rem] uppercase tracking-wide text-white"
                class:bg-accent={r.tier === 'master'}
                class:bg-surface-700={r.tier === 'project'}
              >
                {r.tier}
              </span>
            </header>
            {#if r.description}
              <p class="text-sm text-surface-700 dark:text-surface-200">{r.description}</p>
            {/if}
            <div class="mt-1 flex flex-wrap gap-1">
              {#if r.charter_ref}
                <span class="rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.65rem] dark:bg-surface-700">
                  charter: {r.charter_ref}
                </span>
              {/if}
              {#if r.feature_flag}
                <span class="rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.65rem] dark:bg-surface-700">
                  flag: {r.feature_flag}
                </span>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if filteredIntegrations.length > 0}
    <section aria-label="Integrations" data-testid="integrations-section">
      <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-surface-700 dark:text-surface-200">
        Integrations ({filteredIntegrations.length})
      </h2>
      <ul class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {#each filteredIntegrations as i (`integration-${i.name}`)}
          <li class="panel-card flex flex-col gap-1" data-testid="registry-item" data-entry-kind="integration">
            <header class="flex items-center justify-between gap-2">
              <h3 class="break-words text-base font-semibold text-surface-900 dark:text-surface-50">
                {i.name}
              </h3>
              <span class="rounded-full bg-surface-200 px-2 py-0.5 text-[0.65rem] uppercase tracking-wide text-surface-700 dark:bg-surface-700 dark:text-surface-200">
                {i.kind}
              </span>
            </header>
            {#if i.description}
              <p class="text-sm text-surface-700 dark:text-surface-200">{i.description}</p>
            {/if}
            <div class="mt-1 flex flex-wrap gap-1">
              {#if i.requires_vault_path}
                <span
                  class="rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.65rem] dark:bg-surface-700"
                  title="Vault PATH only — values are never displayed (#9)"
                >
                  vault: {i.requires_vault_path}
                </span>
              {/if}
              {#if i.feature_flag}
                <span class="rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.65rem] dark:bg-surface-700">
                  flag: {i.feature_flag}
                </span>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
{/if}
