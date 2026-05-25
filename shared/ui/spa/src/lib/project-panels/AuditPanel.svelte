<!--
  Spine Hub SPA — Audit panel (V3 Wave 3 part 2, Squad SPA2).

  Surfaces backend at shared/api/routes/audit.py:
    GET /api/v2/audit?project_id=&correlation_id=&limit=  → AuditListResponse
    GET /api/v2/audit/export?project_id=&format=csv|json  → file download

  Scope: backend requires project_id OR correlation_id (filter-or-refuse).
  project_id accepts UUID (Hub default) or numeric lifecycle PK.

  Subsystem / role / action filters are applied client-side over the fetched
  window — a paginated hub-wide timeline endpoint is a known follow-up.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { api, getApiBase } from '$lib/api/client';
  import type { AuditListResponse, AuditRow } from '$lib/api/types';

  export let projectId = '';
  export let projectName = '';

  const SUBSYSTEMS = [
    'plan', 'build', 'verify', 'operate', 'orchestrator',
    'integration', 'identity', 'hub', 'platform'
  ] as const;

  let loading = false;
  let bootstrapping = true;
  let hasLoaded = false;
  let error: string | null = null;
  let rows: AuditRow[] = [];
  let correlationId = '';
  let limit = 500;

  let subsystemFilter = '';
  let roleFilter = '';
  let actionFilter = '';
  let fromTs = '';
  let toTs = '';

  let detailRow: AuditRow | null = null;

  function parseRow(raw: string | AuditRow): AuditRow | null {
    if (typeof raw !== 'string') return raw;
    try {
      return JSON.parse(raw) as AuditRow;
    } catch {
      return null;
    }
  }

  async function load() {
    if (!projectId && !correlationId) {
      error = 'Select a project or enter a correlation ID to load the audit trail.';
      rows = [];
      hasLoaded = false;
      return;
    }
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams();
      if (projectId) params.set('project_id', projectId);
      if (correlationId) params.set('correlation_id', correlationId);
      params.set('limit', String(limit));
      const res = await api.get<AuditListResponse>(`/api/v2/audit?${params.toString()}`);
      rows = (res.items ?? [])
        .map(parseRow)
        .filter((r): r is AuditRow => r !== null);
      hasLoaded = true;
    } catch (err) {
      error = (err as Error).message || 'failed to load audit trail';
      rows = [];
      hasLoaded = true;
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    bootstrapping = false;
    if (projectId || correlationId) {
      await load();
    }
  });

  function confirmExport(fmt: 'csv' | 'json') {
    if (!projectId) {
      error = 'Audit export requires a project (see /api/v2/audit/export contract).';
      return;
    }
    const msg = `Download ${rows.length || 'all'} audit rows for this project as ${fmt.toUpperCase()}?`;
    if (typeof window === 'undefined' || !window.confirm(msg)) return;
    const base = getApiBase();
    const url = `${base}/api/v2/audit/export?project_id=${encodeURIComponent(projectId)}&format=${fmt}`;
    if (typeof window !== 'undefined') window.location.assign(url);
  }

  $: filtered = rows.filter((r) => {
    if (subsystemFilter && r.subsystem !== subsystemFilter) return false;
    if (roleFilter && r.role !== roleFilter) return false;
    if (actionFilter && !(r.action ?? '').toLowerCase().includes(actionFilter.toLowerCase())) return false;
    if (fromTs && r.ts && r.ts < fromTs) return false;
    if (toTs && r.ts && r.ts > toTs) return false;
    return true;
  });

  $: roleOptions = Array.from(new Set(rows.map((r) => r.role).filter((x): x is string => !!x))).sort();
  $: selectedProjectName = projectName || null;
</script>

<PanelHeader
  title="Audit log"
  subtitle={projectName
    ? `Hash-chained ledger for “${projectName}” — role actions, phase transitions, LLM/tool calls`
    : 'Hash-chained append-only ledger — role actions, phase transitions, LLM/tool calls (scoped per project)'}
>
  <button type="button" class="btn-ghost" on:click={() => confirmExport('csv')} data-testid="export-csv">
    Export CSV
  </button>
  <button type="button" class="btn-ghost" on:click={() => confirmExport('json')} data-testid="export-json">
    Export JSON
  </button>
  <button type="button" class="btn-primary" on:click={load} data-testid="audit-load">
    Refresh
  </button>
</PanelHeader>

<p class="mb-4 text-sm text-surface-700 dark:text-surface-200">
  Each row is one immutable audit event from <code>spine_audit.audit_event</code>.
  Events include who acted, which subsystem/role, and the hash chain link to the prior row.
</p>

<form
  class="mb-4 grid grid-cols-1 gap-2 rounded-md border border-surface-200 bg-white p-3 dark:border-surface-700 dark:bg-surface-800 md:grid-cols-3"
  on:submit|preventDefault={load}
  aria-label="Audit filters"
>
  <input type="hidden" value={projectId} data-testid="filter-project" />
  <label class="flex flex-col gap-1 text-xs md:col-span-2">
    <span class="text-surface-700 dark:text-surface-200">Correlation ID (optional)</span>
    <input
      type="text"
      bind:value={correlationId}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
      placeholder="00000000-…"
      data-testid="filter-correlation"
    />
  </label>
  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">Limit (≤ 5000)</span>
    <input
      type="number"
      bind:value={limit}
      min="1"
      max="5000"
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    />
  </label>

  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">Subsystem</span>
    <select
      bind:value={subsystemFilter}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
      data-testid="filter-subsystem"
    >
      <option value="">All</option>
      {#each SUBSYSTEMS as s}<option value={s}>{s}</option>{/each}
    </select>
  </label>
  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">Role</span>
    <select
      bind:value={roleFilter}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    >
      <option value="">All</option>
      {#each roleOptions as r}<option value={r}>{r}</option>{/each}
    </select>
  </label>
  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">Action contains</span>
    <input
      type="text"
      bind:value={actionFilter}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    />
  </label>
  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">From (ts)</span>
    <input
      type="datetime-local"
      bind:value={fromTs}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    />
  </label>
  <label class="flex flex-col gap-1 text-xs">
    <span class="text-surface-700 dark:text-surface-200">To (ts)</span>
    <input
      type="datetime-local"
      bind:value={toTs}
      class="rounded border border-surface-200 px-2 py-1 text-sm dark:border-surface-700 dark:bg-surface-800"
    />
  </label>
</form>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if bootstrapping || loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading audit" /></div>
{:else if !projectId && !correlationId}
  <EmptyState
    title="No project scope"
    message="Open the audit log from a project workspace, or enter a correlation ID above."
  />
{:else if !hasLoaded}
  <EmptyState title="Ready to load" message="Click Refresh to load audit events." />
{:else if rows.length === 0}
  <EmptyState
    title="No audit events yet"
    message={selectedProjectName
      ? `No rows recorded for “${selectedProjectName}”. Events appear as the pipeline runs — create, phase advance, role dispatch, decisions, etc.`
      : 'No rows for this scope. Events appear as the pipeline runs.'}
  />
{:else if filtered.length === 0}
  <EmptyState title="No matches" message="No audit rows match your client-side filters." />
{:else}
  <div class="overflow-x-auto rounded-md border border-surface-200 dark:border-surface-700">
    <table class="min-w-full divide-y divide-surface-200 text-sm dark:divide-surface-700" data-testid="audit-table">
      <thead class="bg-surface-100 dark:bg-surface-800">
        <tr class="text-left text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">
          <th class="px-3 py-2">When</th>
          <th class="hidden px-3 py-2 sm:table-cell">Actor</th>
          <th class="px-3 py-2">Action</th>
          <th class="hidden px-3 py-2 md:table-cell">Subject</th>
          <th class="hidden px-3 py-2 lg:table-cell">Hash</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-surface-200 bg-white dark:divide-surface-700 dark:bg-surface-800">
        {#each filtered as r (r.event_uuid ?? r.event_id)}
          <tr
            class="cursor-pointer hover:bg-surface-100 dark:hover:bg-surface-700"
            on:click={() => (detailRow = r)}
            data-testid="audit-row"
            data-subsystem={r.subsystem ?? ''}
          >
            <td class="whitespace-nowrap px-3 py-2 font-mono text-xs">{r.ts ?? '—'}</td>
            <td class="hidden px-3 py-2 sm:table-cell">{r.actor ?? '—'}</td>
            <td class="px-3 py-2">
              <span class="rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[0.7rem] dark:bg-surface-700">
                {r.subsystem ?? '?'}
              </span>
              <span class="ml-1">{r.action ?? '—'}</span>
            </td>
            <td class="hidden px-3 py-2 md:table-cell">
              <span class="font-mono text-xs">{r.subject_type ?? '?'}</span>
              {#if r.subject_id}
                <span class="ml-1 truncate font-mono text-xs opacity-70">{r.subject_id}</span>
              {/if}
            </td>
            <td class="hidden px-3 py-2 lg:table-cell">
              <span class="truncate font-mono text-xs opacity-70">{r.content_hash ?? r.event_uuid ?? '—'}</span>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <p class="mt-2 text-xs text-surface-700 dark:text-surface-200">
    Showing {filtered.length} of {rows.length} rows{selectedProjectName ? ` for ${selectedProjectName}` : ''} (limit {limit}).
  </p>
{/if}

{#if detailRow}
  <div
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Audit row detail"
    data-testid="audit-detail"
  >
    <div class="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-t-lg bg-white p-4 dark:bg-surface-800 sm:rounded-lg">
      <header class="mb-3 flex items-start justify-between gap-2">
        <h2 class="text-base font-semibold text-surface-900 dark:text-surface-50">
          {detailRow.subsystem ?? '?'} · {detailRow.action ?? '?'}
        </h2>
        <button
          type="button"
          class="btn-ghost"
          on:click={() => (detailRow = null)}
          data-testid="audit-detail-close"
        >
          Close
        </button>
      </header>
      <dl class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        {#each Object.entries(detailRow) as [k, v] (k)}
          <div class="flex flex-col gap-0.5">
            <dt class="text-xs uppercase tracking-wide text-surface-700 dark:text-surface-200">{k}</dt>
            <dd class="break-all font-mono text-xs">
              {typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—')}
            </dd>
          </div>
        {/each}
      </dl>
      {#if detailRow.content_hash || detailRow.prev_content_hash}
        <p class="mt-3 text-xs text-surface-700 dark:text-surface-200">
          Chain link: <code>{detailRow.prev_content_hash ?? '—'}</code> →
          <code>{detailRow.content_hash ?? '—'}</code>
        </p>
      {/if}
    </div>
  </div>
{/if}
