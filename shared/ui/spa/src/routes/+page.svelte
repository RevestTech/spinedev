<!--
  Spine Hub SPA — Dashboard.

  Left: grouped project portfolio (attention / live / idle).
  Right: new-project card. Footer: compact Hub shortcuts.
-->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import { user } from '$lib/stores/user';
  import { decisions, pendingCount, decisionActivity } from '$lib/stores/decisions';
  import { hubInbox, hubInboxCount } from '$lib/stores/hubInbox';
  import { navHref } from '$lib/navActive';
  import { api } from '$lib/api/client';
  import { ApiError } from '$lib/api/types';
  import {
    SDLC_PHASES,
    filterUserProjects,
    groupProjects,
    phaseClass,
    projectStatusLine,
    projectsWithPending,
    relTime,
    statusToneClass,
    type HubProjectRow,
    type StuckSummary
  } from '$lib/projectAttention';

  type ProjectType =
    | 'feature' | 'bug' | 'incident' | 'support' | 'refactor' | 'infra' | 'compliance';
  type ProjectKind = 'greenfield' | ProjectType;

  const KIND_OPTIONS: { value: ProjectKind; label: string; hint: string }[] = [
    { value: 'greenfield', label: 'New project (greenfield)', hint: 'Start a new app / service / codebase from scratch' },
    { value: 'feature', label: 'Feature (existing code)', hint: 'Add a capability to a project you already have' },
    { value: 'bug', label: 'Bug', hint: 'Existing behavior is broken; fix it' },
    { value: 'refactor', label: 'Refactor', hint: 'Clean up / restructure existing code' },
    { value: 'incident', label: 'Incident', hint: 'Production is on fire; respond + write a post-mortem' },
    { value: 'support', label: 'Support', hint: 'Customer-facing question or change' },
    { value: 'infra', label: 'Infra', hint: 'Deploy / scale / migrate infrastructure' },
    { value: 'compliance', label: 'Compliance', hint: 'SOC 2 / GDPR / sector control work' }
  ];

  const HUB_SHORTCUT_GROUPS = [
    {
      label: 'Build',
      links: [
        { href: '/projects', label: 'All projects' },
        { href: '/panels/hub-inbox', label: 'Hub inbox' }
      ]
    },
    {
      label: 'Operate',
      links: [
        { href: '/panels/integrations', label: 'Integrations' },
        { href: '/panels/vault-config', label: 'Vault' },
        { href: '/panels/registry', label: 'Registry' },
        { href: '/panels/master-roles', label: 'Master roles' }
      ]
    },
    {
      label: 'Governance',
      links: [
        { href: '/panels/federation', label: 'Federation' },
        { href: '/panels/license', label: 'License' }
      ]
    }
  ] as const;

  function kindToBackend(kind: ProjectKind): { type: ProjectType; greenfield: boolean } {
    return kind === 'greenfield'
      ? { type: 'feature', greenfield: true }
      : { type: kind, greenfield: false };
  }

  let name = '';
  let projectKind: ProjectKind = 'greenfield';
  let description = '';
  let submitting = false;
  let error: string | null = null;
  let projectsLoadError: string | null = null;

  let projects: HubProjectRow[] = [];
  let projectsLoading = true;
  let stuckByProject: Record<string, StuckSummary> = {};
  let activeByProject: Record<string, { role: string; startedAt: number }> = {};
  let activityUnsub: (() => void) | null = null;
  let nowTick = Date.now();
  let nowInterval: number | null = null;

  $: visibleProjects = filterUserProjects(projects);
  $: projectGroups = groupProjects(visibleProjects, $decisions.items, stuckByProject);
  $: pendingByProject = projectsWithPending(visibleProjects, $decisions.items);

  function activeForProject(p: HubProjectRow) {
    return (
      activeByProject[p.project_id] ??
      (p.project_uuid ? activeByProject[p.project_uuid] : undefined)
    );
  }

  function formatErr(e: unknown, fallback: string): string {
    if (e instanceof ApiError) return e.message;
    if (e instanceof Error && e.message) return e.message;
    return fallback;
  }

  function resolveRouteProjectId(data?: {
    id?: number;
    project_id?: string;
    project_uuid?: string;
  }): string | null {
    if (data?.id != null) return String(data.id);
    const pid = data?.project_id ?? data?.project_uuid;
    return pid ? String(pid) : null;
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

  async function loadProjects() {
    projectsLoading = true;
    projectsLoadError = null;
    try {
      const res = await api.get<{
        items: (string | HubProjectRow)[];
        db_unavailable?: boolean;
      }>('/api/v2/projects?limit=200');
      if (res.db_unavailable) {
        projectsLoadError =
          'Hub database is unavailable — start Postgres or check vault DB credentials.';
      }
      projects = (res.items ?? []).map((it) =>
        typeof it === 'string' ? (JSON.parse(it) as HubProjectRow) : it
      );
    } catch (e) {
      projects = [];
      projectsLoadError = formatErr(e, 'Could not load projects from the Hub API.');
    } finally {
      projectsLoading = false;
    }
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

  async function createProject() {
    if (!name.trim()) {
      error = 'Give your project a short name first.';
      return;
    }
    submitting = true;
    error = null;
    try {
      const { type, greenfield } = kindToBackend(projectKind);
      const body: Record<string, unknown> = {
        name: name.trim(),
        project_type: type
      };
      if (description.trim()) body.description = description.trim();
      if (greenfield) body.greenfield = true;
      const res = await api.post<{
        status?: string;
        data?: { id?: number; project_id?: string; project_uuid?: string };
        error?: { message?: string };
      }>('/api/v2/projects', body);
      if (res.status === 'error') {
        throw new Error(res.error?.message || 'Project creation failed.');
      }
      const pid = resolveRouteProjectId(res.data);
      if (!pid) {
        throw new Error(
          'Project was created but the Hub did not return a project id. Open All projects or refresh.'
        );
      }
      void decisions.load('pending');
      await loadProjects();
      await goto(`${base}/projects/${pid}`);
    } catch (e) {
      error = formatErr(e, 'Project creation failed.');
    } finally {
      submitting = false;
    }
  }

  onMount(() => {
    void loadProjects();
    void loadStuckSummary();
    void decisions.load('pending');
    void hubInbox.load('pending');
    subscribeActivityFeed();
    nowInterval = window.setInterval(() => {
      nowTick = Date.now();
    }, 1000) as unknown as number;
  });

  onDestroy(() => {
    if (nowInterval !== null) window.clearInterval(nowInterval);
    activityUnsub?.();
    activityUnsub = null;
  });
</script>

<style>
  .dashboard-shell {
    display: grid;
    gap: 1.5rem;
  }
  @media (min-width: 1024px) {
    .dashboard-shell {
      grid-template-columns: minmax(0, 1.4fr) minmax(18rem, 0.9fr);
      align-items: start;
    }
    .dashboard-projects {
      grid-column: 1;
      grid-row: 1;
    }
    .dashboard-new-project {
      grid-column: 2;
      grid-row: 1;
      position: sticky;
      top: 1rem;
    }
  }
  .project-group + .project-group {
    margin-top: 1.25rem;
    padding-top: 1.25rem;
    border-top: 1px solid rgba(148, 163, 184, 0.12);
  }
</style>

<PanelHeader
  title="Dashboard"
  subtitle={`Your portfolio at a glance${$user?.username ? ` · ${$user.username}` : ''}`}
/>

{#if error}
  <div class="mb-4">
    <ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} />
  </div>
{/if}

{#if $pendingCount > 0 || $hubInboxCount > 0}
  <section
    class="mb-4 rounded-lg border border-surface-700/60 bg-surface-900/50 px-4 py-3"
    data-testid="dashboard-decisions-summary"
  >
    <div class="flex items-center justify-between gap-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-400">
        Decisions waiting
      </h2>
      {#if $pendingCount > 0}
        <a
          href={pendingByProject.length
            ? `${base}/projects/${pendingByProject[0].project.project_id}`
            : navHref('/projects')}
          class="text-xs font-medium text-amber-200/90 hover:text-amber-100"
          data-testid="dashboard-decisions-badge-link"
        >
          {$pendingCount} approval{$pendingCount === 1 ? '' : 's'} · Open project →
        </a>
      {/if}
    </div>
    <ul class="mt-2 space-y-1.5">
      {#if pendingByProject.length === 0 && $hubInboxCount > 0}
        <li class="px-2 py-1 text-xs text-surface-500">
          No project approvals — {$hubInboxCount} Hub message{$hubInboxCount === 1 ? '' : 's'} in inbox.
        </li>
      {/if}
      {#each pendingByProject as row (row.project.project_id)}
        <li>
          <a
            href="{base}/projects/{row.project.project_id}"
            class="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm transition hover:bg-amber-500/10"
          >
            <span class="font-medium text-amber-100">{row.project.name}</span>
            <span class="shrink-0 text-xs text-amber-200/90">
              {row.count} approval{row.count === 1 ? '' : 's'} · Review →
            </span>
          </a>
        </li>
      {/each}
      {#if $hubInboxCount > 0}
        <li>
          <a
            href={navHref('/panels/hub-inbox')}
            class="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm text-surface-300 transition hover:bg-surface-800/80"
          >
            <span>Hub inbox (portfolio briefings)</span>
            <span class="shrink-0 text-xs text-surface-400">
              {$hubInboxCount} message{$hubInboxCount === 1 ? '' : 's'} →
            </span>
          </a>
        </li>
      {/if}
    </ul>
  </section>
{/if}

<div class="dashboard-shell">
  <section class="dashboard-projects panel-card min-h-[20rem]" data-testid="dashboard-projects">
    <header class="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-surface-50">Projects</h2>
        <p class="mt-0.5 text-xs text-surface-400">
          {visibleProjects.length} in this Hub
          {#if projectGroups.attention.length > 0}
            · {projectGroups.attention.length} need you
          {/if}
        </p>
      </div>
      <a href="{base}/projects" class="shrink-0 text-xs text-accent hover:underline">
        Full list →
      </a>
    </header>

    {#if projectsLoadError}
      <div class="mb-4">
        <ErrorBanner
          kind="error"
          message={projectsLoadError}
          onDismiss={() => (projectsLoadError = null)}
        />
      </div>
    {/if}

    {#if projectsLoading}
      <div class="flex justify-center py-12">
        <LoadingSpinner label="Loading projects" />
      </div>
    {:else if visibleProjects.length === 0}
      <p class="py-8 text-center text-sm text-surface-400">
        No projects yet. Start one using the form on the right.
      </p>
    {:else}
      {#if projectGroups.attention.length > 0}
        <div class="project-group">
          <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-200/90">
            Needs your input · {projectGroups.attention.length}
          </h3>
          <ul class="space-y-2">
            {#each projectGroups.attention as p (p.project_id)}
              {@const active = activeForProject(p)}
              {@const status = projectStatusLine(p, $decisions.items, stuckByProject, active)}
              <li>
                <a
                  href="{base}/projects/{p.project_id}"
                  data-testid="project-needs-attention"
                  class="block rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 transition hover:border-amber-400/60 hover:bg-amber-500/15"
                >
                  <div class="flex items-start justify-between gap-2">
                    <span class="truncate text-sm font-medium text-amber-50">{p.name}</span>
                    <span class="shrink-0 text-xs font-medium text-amber-100">Review →</span>
                  </div>
                  <div class="mt-1.5 flex flex-wrap items-center gap-2">
                    <span class="inline-flex rounded-full border px-2 py-0.5 text-[0.65rem] font-medium {statusToneClass(status.tone)}">
                      {status.label}{#if status.detail} · {status.detail}{/if}
                    </span>
                    <span class="text-[0.65rem] text-surface-500">{relTime(p.updated_at)}</span>
                  </div>
                  <div class="mt-2 flex flex-wrap items-center gap-1">
                    {#each SDLC_PHASES as ph, i (ph)}
                      <span class="rounded-full px-1.5 py-0.5 text-[0.6rem] {phaseClass(ph, p.current_phase)}">
                        {ph}
                      </span>
                      {#if i < SDLC_PHASES.length - 1}
                        <span class="text-surface-600" aria-hidden="true">→</span>
                      {/if}
                    {/each}
                  </div>
                </a>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if projectGroups.live.length > 0}
        <div class="project-group">
          <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-sky-300/90">
            Live in pipeline · {projectGroups.live.length}
          </h3>
          <ul class="space-y-2">
            {#each projectGroups.live as p (p.project_id)}
              {@const active = activeForProject(p)}
              {@const elapsed = active ? Math.max(0, Math.round((nowTick - active.startedAt) / 1000)) : 0}
              {@const status = projectStatusLine(p, $decisions.items, stuckByProject, active)}
              <li>
                <a
                  href="{base}/projects/{p.project_id}"
                  class="block rounded-lg border border-surface-700/60 bg-surface-800/40 px-3 py-2.5 transition hover:border-accent/40 hover:bg-surface-800/70"
                >
                  <div class="flex items-start justify-between gap-2">
                    <span class="truncate text-sm font-medium text-surface-100">{p.name}</span>
                    <span class="shrink-0 text-[0.65rem] text-surface-500">{relTime(p.updated_at)}</span>
                  </div>
                  <div class="mt-1.5 flex flex-wrap items-center gap-2">
                    <span class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.65rem] font-medium {statusToneClass(status.tone)}">
                      {#if active}
                        <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current opacity-80"></span>
                        {active.role} · {elapsed}s
                      {:else}
                        {status.label}{#if status.detail} · {status.detail}{/if}
                      {/if}
                    </span>
                  </div>
                  <div class="mt-2 flex flex-wrap items-center gap-1">
                    {#each SDLC_PHASES as ph, i (ph)}
                      <span class="rounded-full px-1.5 py-0.5 text-[0.6rem] {phaseClass(ph, p.current_phase)}">
                        {ph}
                      </span>
                      {#if i < SDLC_PHASES.length - 1}
                        <span class="text-surface-600" aria-hidden="true">→</span>
                      {/if}
                    {/each}
                  </div>
                </a>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if projectGroups.idle.length > 0}
        <div class="project-group">
          <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
            Complete or idle · {projectGroups.idle.length}
          </h3>
          <ul class="space-y-1.5">
            {#each projectGroups.idle as p (p.project_id)}
              {@const status = projectStatusLine(p, $decisions.items, stuckByProject)}
              <li>
                <a
                  href="{base}/projects/{p.project_id}"
                  class="flex items-center justify-between gap-3 rounded-lg border border-transparent px-3 py-2 text-sm transition hover:border-surface-700/60 hover:bg-surface-800/50"
                >
                  <span class="truncate text-surface-300">{p.name}</span>
                  <span class="inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[0.65rem] font-medium {statusToneClass(status.tone)}">
                    {status.label}
                  </span>
                </a>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {/if}
  </section>

  <aside class="dashboard-new-project">
    <section class="panel-card" data-testid="dashboard-new-project">
      <h2 class="text-base font-semibold text-surface-50">Start a project</h2>
      <p class="mt-1 text-xs text-surface-400">
        Describe what you want; intake drafts a PRD and roles take it from there.
      </p>

      <form on:submit|preventDefault={createProject} class="mt-4 space-y-3">
        <label class="flex flex-col gap-1">
          <span class="text-xs text-surface-400">Name</span>
          <input
            type="text"
            bind:value={name}
            placeholder='e.g. "Checkout for pricing page"'
            maxlength="200"
            class="rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-surface-50 focus:border-accent focus:outline-none"
            data-testid="new-project-name"
          />
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-xs text-surface-400">Kind</span>
          <select
            bind:value={projectKind}
            class="rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-surface-50 focus:border-accent focus:outline-none"
            data-testid="new-project-type"
          >
            {#each KIND_OPTIONS as opt (opt.value)}
              <option value={opt.value}>{opt.label}</option>
            {/each}
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-xs text-surface-400">Brief</span>
          <textarea
            bind:value={description}
            placeholder="What should this do? What does done look like?"
            rows="4"
            class="rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-surface-50 focus:border-accent focus:outline-none"
            data-testid="new-project-description"
          ></textarea>
        </label>

        <p class="text-[0.65rem] leading-relaxed text-surface-500">
          {KIND_OPTIONS.find((o) => o.value === projectKind)?.hint}
        </p>

        <button
          type="submit"
          class="btn-primary w-full"
          disabled={submitting}
          data-testid="new-project-submit"
        >
          {submitting ? 'Creating…' : 'Start the build →'}
        </button>
      </form>
    </section>
  </aside>
</div>

<section class="panel-card mt-6">
  <h2 class="mb-4 text-sm font-semibold text-surface-50">Hub shortcuts</h2>
  <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
    {#each HUB_SHORTCUT_GROUPS as group (group.label)}
      <div>
        <h3 class="mb-2 text-[0.65rem] font-semibold uppercase tracking-wider text-surface-500">
          {group.label}
        </h3>
        <ul class="space-y-1">
          {#each group.links as link (link.href)}
            <li>
              <a
                href="{base}{link.href}"
                class="block rounded-md px-2 py-1.5 text-xs text-surface-300 transition hover:bg-surface-800/80 hover:text-accent"
              >
                {link.label}
              </a>
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </div>
</section>
