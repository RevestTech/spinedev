<!--
  Spine Hub SPA — Projects list.

  All projects in the Hub, sortable by recency, with their current SDLC
  phase and status. Click any row → workspace.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import { api } from '$lib/api/client';

  interface ProjectRow {
    project_id: string;
    name: string;
    project_type: string;
    current_phase: string;
    status: string;
    owner?: string;
    created_at?: string;
    updated_at?: string;
  }

  const PHASES = ['intake', 'plan', 'build', 'verify', 'release'] as const;

  let projects: ProjectRow[] = [];
  let loading = true;
  let error: string | null = null;
  let pollHandle: number | null = null;

  async function load() {
    try {
      const res = await api.get<{ items: (string | ProjectRow)[] }>(
        '/api/v2/projects?limit=200'
      );
      const parsed = (res.items ?? []).map((it) =>
        typeof it === 'string' ? (JSON.parse(it) as ProjectRow) : it
      );
      parsed.sort((a, b) =>
        (b.updated_at ?? '').localeCompare(a.updated_at ?? '')
      );
      projects = parsed;
      error = null;
    } catch (e) {
      error = (e as Error).message || 'failed to load projects';
    } finally {
      loading = false;
    }
  }

  function phaseClass(phase: string, current: string): string {
    const idx = PHASES.indexOf(phase as any);
    const cur = PHASES.indexOf(current as any);
    if (idx < 0 || cur < 0) return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
    if (idx < cur) return 'bg-severity-info text-white';
    if (idx === cur) return 'bg-accent text-white';
    return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
  }

  function statusBadge(s: string): string {
    if (s === 'active') return 'bg-severity-info text-white';
    if (s === 'paused') return 'bg-severity-warning text-white';
    if (s === 'terminated') return 'bg-severity-critical text-white';
    return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
  }

  function relTime(iso: string | undefined): string {
    if (!iso) return '';
    const dt = new Date(iso).getTime();
    if (Number.isNaN(dt)) return iso;
    const sec = Math.round((Date.now() - dt) / 1000);
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
    return `${Math.round(sec / 86400)}d ago`;
  }

  onMount(() => {
    load();
    pollHandle = window.setInterval(load, 5000) as unknown as number;
  });

  onDestroy(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
  });
</script>

<PanelHeader
  title="Projects"
  subtitle={projects.length > 0 ? `${projects.length} project${projects.length === 1 ? '' : 's'} in this Hub` : 'No projects yet'}
>
  <a href="{base}/" class="btn-primary text-sm">+ New project</a>
</PanelHeader>

{#if error}
  <div class="mb-4">
    <ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} />
  </div>
{/if}

{#if loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading projects" /></div>
{:else if projects.length === 0}
  <section class="panel-card text-center">
    <p class="mb-3 text-sm text-surface-700 dark:text-surface-200">
      No projects in this Hub yet.
    </p>
    <a href="{base}/" class="btn-primary text-sm">Start your first project →</a>
  </section>
{:else}
  <section class="panel-card overflow-hidden p-0">
    <table class="w-full text-sm">
      <thead class="bg-surface-100 text-left text-xs uppercase tracking-wide text-surface-700/80 dark:bg-surface-700 dark:text-surface-200/80">
        <tr>
          <th class="px-3 py-2">Project</th>
          <th class="px-3 py-2">Type</th>
          <th class="px-3 py-2">SDLC pipeline</th>
          <th class="px-3 py-2">Status</th>
          <th class="px-3 py-2">Owner</th>
          <th class="px-3 py-2 text-right">Updated</th>
        </tr>
      </thead>
      <tbody>
        {#each projects as p (p.project_id)}
          <tr class="border-t border-surface-200 hover:bg-surface-50 dark:border-surface-700 dark:hover:bg-surface-700">
            <td class="px-3 py-2">
              <a
                href="{base}/projects/{p.project_id}"
                class="font-medium text-accent hover:underline"
              >
                {p.name}
              </a>
            </td>
            <td class="px-3 py-2 text-surface-700 dark:text-surface-200">{p.project_type}</td>
            <td class="px-3 py-2">
              <div class="flex flex-wrap items-center gap-1 text-[0.65rem]">
                {#each PHASES as ph, i (ph)}
                  <span class="rounded-full px-2 py-0.5 {phaseClass(ph, p.current_phase)}">
                    {ph}
                  </span>
                  {#if i < PHASES.length - 1}
                    <span class="text-surface-700/40 dark:text-surface-200/40" aria-hidden="true">→</span>
                  {/if}
                {/each}
              </div>
            </td>
            <td class="px-3 py-2">
              <span class="rounded-full px-2 py-0.5 text-xs {statusBadge(p.status)}">
                {p.status}
              </span>
            </td>
            <td class="px-3 py-2 text-xs text-surface-700/80 dark:text-surface-200/80">{p.owner ?? ''}</td>
            <td class="px-3 py-2 text-right text-xs text-surface-700/80 dark:text-surface-200/80">
              {relTime(p.updated_at)}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}
