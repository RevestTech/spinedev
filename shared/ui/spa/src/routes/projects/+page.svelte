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
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import ProjectEditDialog from '$lib/components/ProjectEditDialog.svelte';
  import { api } from '$lib/api/client';
  import { ApiError } from '$lib/api/types';
  import { decisions, decisionActivity } from '$lib/stores/decisions';
  import { toasts } from '$lib/stores/toasts';
  import type { DecisionCard } from '$lib/api/types';
  import { PIPELINE_COPY } from '$lib/projectPipelineCopy';
  import {
    archiveProject,
    deleteProject,
    isArchived,
    projectBrief,
    restoreProject,
    updateProject,
  } from '$lib/projectLifecycle';
  import {
    filterUserProjects,
    pendingForProject,
    stuckForProject,
    type StuckSummary
  } from '$lib/projectAttention';

  interface ProjectRow {
    project_id: string;
    project_uuid?: string;
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
  let showAutomated = false;
  let showArchived = false;

  type ConfirmKind = 'archive' | 'delete' | 'restore';
  let confirmOpen = false;
  let confirmKind: ConfirmKind = 'archive';
  let confirmTarget: ProjectRow | null = null;
  let confirmBusy = false;

  let editOpen = false;
  let editTarget: ProjectRow | null = null;
  let editName = '';
  let editDescription = '';
  let editBusy = false;
  let editError: string | null = null;

  $: filteredProjects = filterUserProjects(projects, showAutomated, showArchived);

  // Live per-project role tracking via SSE.
  let activeByProject: Record<string, { role: string; startedAt: number }> = {};
  let stuckByProject: Record<string, StuckSummary> = {};
  let activityUnsub: (() => void) | null = null;
  let nowTick = Date.now();
  let nowInterval: number | null = null;

  function formatErr(e: unknown, fallback: string): string {
    if (e instanceof ApiError) return e.message;
    if (e instanceof Error && e.message) return e.message;
    return fallback;
  }

  function sseProjectKey(ev: {
    project_uuid?: string;
    project_id?: string;
    card?: { project_id?: string; metadata?: { project_uuid?: string } };
  }): string | null {
    const pid =
      ev.project_uuid ??
      ev.project_id ??
      ev.card?.project_id ??
      ev.card?.metadata?.project_uuid;
    return pid ? String(pid) : null;
  }

  function projectNeedsAttention(p: ProjectRow, cards: DecisionCard[]): boolean {
    return pendingForProject(p, cards) > 0 || stuckForProject(p, stuckByProject) != null;
  }

  function attentionHint(p: ProjectRow, cards: DecisionCard[]): string | null {
    const pending = pendingForProject(p, cards);
    if (pending > 0) {
      return PIPELINE_COPY.attention.decisionsReview(pending);
    }
    if (stuckForProject(p, stuckByProject)) return PIPELINE_COPY.attention.paused;
    return null;
  }

  function activeForProject(p: ProjectRow): { role: string; startedAt: number } | undefined {
    return (
      activeByProject[p.project_id] ??
      (p.project_uuid ? activeByProject[p.project_uuid] : undefined)
    );
  }

  $: sortedProjects = [...filteredProjects].sort((a, b) => {
    const aNeeds = projectNeedsAttention(a, $decisions.items) ? 0 : 1;
    const bNeeds = projectNeedsAttention(b, $decisions.items) ? 0 : 1;
    if (aNeeds !== bNeeds) return aNeeds - bNeeds;
    return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
  });

  $: attentionCount = sortedProjects.filter((p) =>
    projectNeedsAttention(p, $decisions.items)
  ).length;

  function subscribeActivityFeed() {
    if (activityUnsub) return;
    activityUnsub = decisionActivity.subscribe((ev) => {
      if (!ev?.type) return;
      const pid = sseProjectKey(ev);
      if (!pid) return;
      if (ev.type === 'role_started') {
        activeByProject = {
          ...activeByProject,
          [pid]: { role: ev.role ?? 'role', startedAt: (ev.ts ?? Date.now() / 1000) * 1000 },
        };
      } else if (ev.type === 'role_finished' || ev.type === 'role_failed') {
        const next = { ...activeByProject };
        delete next[pid];
        activeByProject = next;
        void loadStuckSummary();
      } else if (ev.type === 'card_created' || ev.type === 'card_updated') {
        void loadStuckSummary();
      }
    });
  }

  async function loadStuckSummary() {
    try {
      const res = await api.get<{ by_project_id?: Record<string, StuckSummary> }>(
        '/api/v2/projects/recovery/summary?limit=200'
      );
      stuckByProject = res.by_project_id ?? {};
    } catch {
      stuckByProject = {};
    }
  }

  async function load() {
    try {
      const qs = showArchived ? '?limit=200&include_archived=true' : '?limit=200';
      const res = await api.get<{
        items: (string | ProjectRow)[];
        db_unavailable?: boolean;
      }>(`/api/v2/projects${qs}`);
      if (res.db_unavailable) {
        error =
          'Hub database is unavailable — start Postgres or check vault DB credentials.';
      }
      const parsed = (res.items ?? []).map((it) =>
        typeof it === 'string' ? (JSON.parse(it) as ProjectRow) : it
      );
      parsed.sort((a, b) =>
        (b.updated_at ?? '').localeCompare(a.updated_at ?? '')
      );
      projects = parsed;
      if (!res.db_unavailable) error = null;
    } catch (e) {
      error = formatErr(e, 'Failed to load projects');
    } finally {
      loading = false;
    }
  }

  function phaseIndex(phase: string | undefined): number {
    if (!phase) return -1;
    const p = phase.toLowerCase();
    if (p === 'intake') return 0;
    if (p.startsWith('plan')) return 1;
    if (p.startsWith('build')) return 2;
    if (p.startsWith('verify') || p === 'acceptance') return 3;
    if (p === 'released' || p === 'release' || p === 'operate' || p === 'retro') return 4;
    return -1;
  }

  function phaseClass(phase: string, current: string): string {
    const idx = PHASES.indexOf(phase as any);
    const cur = phaseIndex(current);
    if (idx < 0 || cur < 0) return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
    if (idx < cur) return 'bg-severity-info text-white';
    if (idx === cur) return 'bg-accent text-white';
    return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
  }

  function statusBadge(s: string): string {
    if (s === 'active') return 'bg-severity-info text-white';
    if (s === 'paused') return 'bg-severity-warning text-white';
    if (s === 'completed') return 'bg-surface-600 text-surface-100';
    if (s === 'terminated') return 'bg-severity-critical text-white';
    return 'bg-surface-200 text-surface-700 dark:bg-surface-700 dark:text-surface-200';
  }

  function statusLabel(s: string): string {
    if (s === 'completed') return 'archived';
    return s;
  }

  async function openEdit(p: ProjectRow) {
    editTarget = p;
    editName = p.name;
    editDescription = '';
    editError = null;
    editOpen = true;
    try {
      const full = await api.get<{ name: string; metadata?: Record<string, unknown> }>(
        `/api/v2/projects/${p.project_id}/full`
      );
      editName = full.name;
      editDescription = projectBrief(full);
    } catch (e) {
      editError = formatErr(e, 'Could not load project details');
    }
  }

  function openConfirm(kind: ConfirmKind, p: ProjectRow) {
    confirmKind = kind;
    confirmTarget = p;
    confirmOpen = true;
  }

  async function handleConfirm() {
    if (!confirmTarget) return;
    confirmBusy = true;
    const id = confirmTarget.project_id;
    const label = confirmTarget.name;
    try {
      if (confirmKind === 'archive') {
        await archiveProject(id);
        toasts.push({ kind: 'success', message: `Archived "${label}"`, ttlMs: 4000 });
      } else if (confirmKind === 'restore') {
        await restoreProject(id);
        toasts.push({ kind: 'success', message: `Restored "${label}"`, ttlMs: 4000 });
      } else {
        await deleteProject(id);
        toasts.push({ kind: 'success', message: `Deleted "${label}"`, ttlMs: 4000 });
      }
      confirmOpen = false;
      confirmTarget = null;
      await load();
      void loadStuckSummary();
    } catch (e) {
      toasts.push({ kind: 'error', message: formatErr(e, 'Project action failed') });
    } finally {
      confirmBusy = false;
    }
  }

  async function handleEditSave(e: CustomEvent<{ name: string; description: string }>) {
    if (!editTarget) return;
    editBusy = true;
    editError = null;
    try {
      await updateProject(editTarget.project_id, {
        name: e.detail.name,
        description: e.detail.description || undefined,
      });
      toasts.push({ kind: 'success', message: `Updated "${e.detail.name}"`, ttlMs: 3500 });
      editOpen = false;
      editTarget = null;
      await load();
    } catch (err) {
      editError = formatErr(err, 'Save failed');
    } finally {
      editBusy = false;
    }
  }

  $: confirmCopy = (() => {
    const name = confirmTarget?.name ?? 'this project';
    if (confirmKind === 'archive') {
      return {
        title: 'Archive project?',
        message: `"${name}" will move to archived projects. You can restore it later; the workspace and audit trail stay on the Hub.`,
        confirmLabel: 'Archive',
        variant: 'warning' as const,
      };
    }
    if (confirmKind === 'restore') {
      return {
        title: 'Restore project?',
        message: `"${name}" will return to your active project list.`,
        confirmLabel: 'Restore',
        variant: 'default' as const,
      };
    }
    return {
      title: 'Delete project?',
      message: `"${name}" will be permanently removed from the Hub UI. This cannot be undone from the SPA.`,
      confirmLabel: 'Delete',
      variant: 'danger' as const,
    };
  })();

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
    void load();
    void decisions.load('pending');
    void loadStuckSummary();
    subscribeActivityFeed();
    pollHandle = window.setInterval(() => {
      load();
      loadStuckSummary();
    }, 5000) as unknown as number;
    nowInterval = window.setInterval(() => { nowTick = Date.now(); }, 1000) as unknown as number;
  });

  onDestroy(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
    if (nowInterval !== null) window.clearInterval(nowInterval);
    activityUnsub?.();
    activityUnsub = null;
  });
</script>

<PanelHeader
  title="Projects"
  subtitle={filteredProjects.length > 0
    ? attentionCount > 0
      ? `${filteredProjects.length} project${filteredProjects.length === 1 ? '' : 's'} · ${attentionCount} need${attentionCount === 1 ? 's' : ''} your attention`
      : `${filteredProjects.length} project${filteredProjects.length === 1 ? '' : 's'} shown`
    : 'No projects shown'}
>
  <div class="flex flex-wrap items-center gap-4">
    <label class="flex items-center gap-2 text-xs text-surface-700 dark:text-surface-200 cursor-pointer">
      <input type="checkbox" bind:checked={showArchived} on:change={() => load()} class="rounded border-surface-300 text-accent focus:ring-accent" />
      Show archived
    </label>
    <label class="flex items-center gap-2 text-xs text-surface-700 dark:text-surface-200 cursor-pointer">
      <input type="checkbox" bind:checked={showAutomated} class="rounded border-surface-300 text-accent focus:ring-accent" />
      Show automated test runs
    </label>
    <a href="{base}/" class="btn-primary text-sm">+ New project</a>
  </div>
</PanelHeader>

{#if error}
  <div class="mb-4">
    <ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} />
  </div>
{/if}

{#if loading}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading projects" /></div>
{:else if filteredProjects.length === 0}
  <section class="panel-card text-center py-8">
    <p class="mb-3 text-sm text-surface-700 dark:text-surface-200">
      {#if projects.length > 0}
        No user-driven projects shown. Toggle "Show automated test runs" to see smoke tests.
      {:else}
        No projects in this Hub yet.
      {/if}
    </p>
    {#if projects.length === 0}
      <a href="{base}/" class="btn-primary text-sm">Start your first project →</a>
    {/if}
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
          <th class="px-3 py-2 text-right">Manage</th>
        </tr>
      </thead>
      <tbody>
        {#each sortedProjects as p (p.project_id)}
          {@const active = activeForProject(p)}
          {@const needsAttention = projectNeedsAttention(p, $decisions.items)}
          {@const hint = attentionHint(p, $decisions.items)}
          {@const pending = pendingForProject(p, $decisions.items)}
          {@const elapsed = active ? Math.max(0, Math.round((nowTick - active.startedAt) / 1000)) : 0}
          {@const archived = isArchived(p)}
          <tr
            data-testid={needsAttention ? 'project-needs-attention' : undefined}
            class="border-t border-surface-200 dark:border-surface-700 {needsAttention
              ? 'bg-amber-500/10 ring-1 ring-inset ring-amber-500/30 hover:bg-amber-500/15'
              : 'hover:bg-surface-50 dark:hover:bg-surface-700'}"
          >
            <td class="px-3 py-2">
              <a
                href="{base}/projects/{p.project_id}"
                class="font-medium {needsAttention ? 'text-amber-100 hover:text-amber-50' : 'text-accent hover:underline'}"
              >
                {p.name}
              </a>
              <div class="mt-1 flex flex-wrap items-center gap-2">
                {#if active}
                  <span class="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[0.65rem] font-medium text-white">
                    <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-white"></span>
                    {active.role} · {elapsed}s
                  </span>
                {/if}
                {#if needsAttention && hint}
                  <span
                    class="inline-flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-500/15 px-2 py-0.5 text-[0.65rem] font-medium text-amber-100"
                  >
                    {hint}
                  </span>
                {/if}
              </div>
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
                {statusLabel(p.status)}
              </span>
            </td>
            <td class="px-3 py-2 text-xs text-surface-700/80 dark:text-surface-200/80">{p.owner ?? ''}</td>
            <td class="px-3 py-2 text-right text-xs text-surface-700/80 dark:text-surface-200/80">
              {relTime(p.updated_at)}
            </td>
            <td class="px-3 py-2 text-right">
              <div class="flex flex-wrap items-center justify-end gap-1">
                {#if needsAttention}
                  <a
                    href="{base}/projects/{p.project_id}"
                    class="inline-flex items-center rounded-md border border-amber-500/50 bg-amber-500/15 px-2.5 py-1 text-xs font-medium text-amber-100 transition hover:border-amber-400/70 hover:bg-amber-500/25"
                    data-testid="project-review-action"
                  >
                    {pending > 0 ? 'Review →' : 'Open →'}
                  </a>
                {/if}
                <button type="button" class="btn-ghost px-2 py-1 text-xs" on:click={() => openEdit(p)} data-testid="project-edit-btn">
                  Edit
                </button>
                {#if archived}
                  <button type="button" class="btn-ghost px-2 py-1 text-xs" on:click={() => openConfirm('restore', p)}>
                    Restore
                  </button>
                {:else}
                  <button type="button" class="btn-ghost px-2 py-1 text-xs" on:click={() => openConfirm('archive', p)}>
                    Archive
                  </button>
                {/if}
                <button type="button" class="btn-ghost px-2 py-1 text-xs text-rose-300 hover:text-rose-200" on:click={() => openConfirm('delete', p)} data-testid="project-delete-btn">
                  Delete
                </button>
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

<ConfirmDialog
  bind:open={confirmOpen}
  title={confirmCopy.title}
  message={confirmCopy.message}
  confirmLabel={confirmCopy.confirmLabel}
  variant={confirmCopy.variant}
  busy={confirmBusy}
  on:confirm={handleConfirm}
  on:cancel={() => {
    if (!confirmBusy) confirmTarget = null;
  }}
/>

<ProjectEditDialog
  bind:open={editOpen}
  name={editName}
  description={editDescription}
  busy={editBusy}
  error={editError}
  on:save={handleEditSave}
  on:cancel={() => {
    if (!editBusy) {
      editTarget = null;
      editError = null;
    }
  }}
/>
