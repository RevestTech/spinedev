<!--
  Spine Hub SPA — Master Roles panel (V3 Wave 3 part 2, Squad SPA2).

  Surfaces backend at shared/api/routes/registry.py:
    GET /api/v2/registry/roles  → { ok, items: RoleEntry[] }

  Per design decisions:
    - #3 one of the 9 enumerated Hub surfaces
    - #8 two-tier role hierarchy (master / project) — this panel filters
         to tier === 'master' and shows project roles as a secondary list

  Backend gap (filed to report): the panel scope asks for per-role
  `status` (active/idle/paused), `last_decision_card_pushed`, and
  `current_responsibility`. registry.py currently exposes only static
  catalog metadata (name, tier, description, charter_ref, feature_flag).
  The panel renders those fields today and leaves visual slots for the
  runtime fields Wave 4 must add.

  Responsive: single-column < md; 2-col @ md; 3-col @ lg.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { api } from '$lib/api/client';
  import type { RoleEntry, RoleList } from '$lib/api/types';

  let loading = true;
  let error: string | null = null;
  let roles: RoleEntry[] = [];
  let showProjectRoles = false;

  async function load() {
    loading = true;
    error = null;
    try {
      const res = await api.get<RoleList>('/api/v2/registry/roles');
      roles = res.items ?? [];
    } catch (err) {
      error = (err as Error).message || 'failed to load roles';
      roles = [];
    } finally {
      loading = false;
    }
  }

  onMount(load);

  $: masterRoles = roles.filter((r) => r.tier === 'master');
  $: projectRoles = roles.filter((r) => r.tier === 'project');

  // Placeholder runtime fields until Wave 4 adds them backend-side.
  // Today these render as "unknown" badges; the slot is wired so once
  // /api/v2/registry/roles starts returning status/last_decision/etc.,
  // the panel surfaces them without further markup churn.
  function statusBadge(_r: RoleEntry): { label: string; tone: string } {
    return { label: 'unknown', tone: 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200' };
  }
</script>

<PanelHeader title="Master roles" subtitle="Two-tier hierarchy per design decision #8 — master directors + project roles">
  <label class="flex items-center gap-2 text-xs">
    <input type="checkbox" bind:checked={showProjectRoles} data-testid="toggle-project-roles" />
    <span class="text-surface-700 dark:text-surface-200">Show project roles</span>
  </label>
  <button
    type="button"
    class="btn-ghost"
    on:click={load}
    aria-label="Refresh role registry"
    data-testid="refresh-roles"
  >
    Refresh
  </button>
</PanelHeader>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading roles" /></div>
{:else if roles.length === 0}
  <EmptyState
    title="No roles registered"
    message="The active bundle did not advertise any roles. Check shared/api/routes/registry.py."
  />
{:else}
  <section aria-label="Master roles" class="mb-6">
    <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-surface-700 dark:text-surface-200">
      Master directors ({masterRoles.length})
    </h2>
    {#if masterRoles.length === 0}
      <p class="text-sm text-surface-700 dark:text-surface-200">No master-tier roles in the active bundle.</p>
    {:else}
      <ul
        class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
        data-testid="master-roles-list"
      >
        {#each masterRoles as r (r.name)}
          {@const badge = statusBadge(r)}
          <li
            class="panel-card flex flex-col gap-2"
            data-testid="role-card"
            data-role-name={r.name}
            data-role-tier={r.tier}
          >
            <header class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
                  master
                </div>
                <h3 class="mt-1 break-words text-base font-semibold text-surface-900 dark:text-surface-50">
                  {r.name}
                </h3>
              </div>
              <span class="rounded-full px-2 py-0.5 text-xs {badge.tone}" title="Runtime status — backend gap, Wave 4">
                {badge.label}
              </span>
            </header>

            {#if r.description}
              <p class="text-sm text-surface-700 dark:text-surface-200">{r.description}</p>
            {/if}

            <dl class="mt-auto grid grid-cols-1 gap-1 text-xs text-surface-700 dark:text-surface-200">
              <div class="flex justify-between gap-2">
                <dt>Last decision pushed</dt>
                <dd class="font-mono opacity-70">—</dd>
              </div>
              <div class="flex justify-between gap-2">
                <dt>Current responsibility</dt>
                <dd class="font-mono opacity-70">—</dd>
              </div>
              {#if r.charter_ref}
                <div class="flex justify-between gap-2">
                  <dt>Charter</dt>
                  <dd class="truncate font-mono">{r.charter_ref}</dd>
                </div>
              {/if}
              {#if r.feature_flag}
                <div class="flex justify-between gap-2">
                  <dt>Flag</dt>
                  <dd class="truncate font-mono">{r.feature_flag}</dd>
                </div>
              {/if}
            </dl>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  {#if showProjectRoles}
    <section aria-label="Project roles" data-testid="project-roles-section">
      <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-surface-700 dark:text-surface-200">
        Project roles ({projectRoles.length})
      </h2>
      <ul class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {#each projectRoles as r (r.name)}
          <li
            class="panel-card flex flex-col gap-2"
            data-testid="role-card"
            data-role-name={r.name}
            data-role-tier={r.tier}
          >
            <div class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
              project
            </div>
            <h3 class="break-words text-base font-semibold text-surface-900 dark:text-surface-50">
              {r.name}
            </h3>
            {#if r.description}
              <p class="text-sm text-surface-700 dark:text-surface-200">{r.description}</p>
            {/if}
            {#if r.feature_flag}
              <span class="self-start rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.65rem] text-surface-700 dark:bg-surface-700 dark:text-surface-200">
                flag: {r.feature_flag}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}
{/if}
