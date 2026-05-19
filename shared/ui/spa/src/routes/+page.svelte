<!--
  Spine Hub SPA — landing page (V3 Wave 3 part 2, Squad SPA1).

  Replaces the bare admin tile-grid with a "what do you want to build?"
  entry point per first-run user feedback ("I'm not sure what I'm looking
  at"). The Hub is positioned as an AI software company in a box
  (#1/#3); the landing should reflect that — pick a project type,
  describe what you want, hit Build. Admin / observability panels move
  down to a secondary section.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { user } from '$lib/stores/user';
  import { pendingCount } from '$lib/stores/decisions';
  import { api } from '$lib/api/client';

  type ProjectType =
    | 'feature' | 'bug' | 'incident' | 'support' | 'refactor' | 'infra' | 'compliance';

  // UI-only "kind" — `greenfield` maps to backend project_type='feature' with
  // a metadata.greenfield:true marker so the intake role skips the
  // "read existing code first" preamble. All other kinds 1:1 with the
  // 7 work-item types per #19. Greenfield is listed FIRST because that's
  // most vibecoder/startup users' actual job-to-be-done; the other 7 are
  // for teams operating against an existing codebase.
  type ProjectKind = 'greenfield' | ProjectType;

  const KIND_OPTIONS: { value: ProjectKind; label: string; hint: string }[] = [
    { value: 'greenfield', label: 'New project (greenfield)', hint: 'Start a new app / service / codebase from scratch' },
    { value: 'feature',    label: 'Feature (existing code)',   hint: 'Add a capability to a project you already have' },
    { value: 'bug',        label: 'Bug',                       hint: 'Existing behavior is broken; fix it' },
    { value: 'refactor',   label: 'Refactor',                  hint: 'Clean up / restructure existing code' },
    { value: 'incident',   label: 'Incident',                  hint: 'Production is on fire; respond + write a post-mortem' },
    { value: 'support',    label: 'Support',                   hint: 'Customer-facing question or change' },
    { value: 'infra',      label: 'Infra',                     hint: 'Deploy / scale / migrate infrastructure' },
    { value: 'compliance', label: 'Compliance',                hint: 'SOC 2 / GDPR / sector control work' }
  ];

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

  interface ProjectRow {
    project_id: string;
    name: string;
    project_type: string;
    current_phase: string;
    status: string;
    updated_at: string;
  }
  let recent: ProjectRow[] = [];
  let recentLoading = true;

  async function loadRecent() {
    recentLoading = true;
    try {
      // Backend returns items as JSON-encoded strings (Postgres
      // json_build_object()::text). Parse defensively so the cards
      // render real fields not "undefined".
      const res = await api.get<{ items: (string | ProjectRow)[] }>(
        '/api/v2/projects?limit=5'
      );
      recent = (res.items ?? []).map((it) =>
        typeof it === 'string' ? (JSON.parse(it) as ProjectRow) : it
      );
    } catch {
      recent = [];
    } finally {
      recentLoading = false;
    }
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
        data?: { project_id?: string };
        error?: { message?: string };
      }>('/api/v2/projects', body);
      if (res.status === 'error') {
        throw new Error(res.error?.message || 'Project creation returned status=error');
      }
      const pid = res.data?.project_id;
      console.info('project created:', pid);
      if (pid) {
        goto(`${base}/projects/${pid}`);
      } else {
        goto(`${base}/panels/decision-queue`);
      }
    } catch (e) {
      error = (e as Error).message || 'Project creation failed';
    } finally {
      submitting = false;
    }
  }

  onMount(loadRecent);
</script>

<PanelHeader
  title="Build something"
  subtitle={`Tell Spine what you want; AI scrum masters do the work and bring decisions back to you${$user?.username ? `, ${$user.username}` : ''}.`}
/>

{#if error}
  <div class="mb-4">
    <ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} />
  </div>
{/if}

<section class="panel-card mb-8">
  <h2 class="mb-4 text-base font-semibold text-surface-900 dark:text-surface-50">
    What do you want to build?
  </h2>

  <form on:submit|preventDefault={createProject} class="grid gap-4 md:grid-cols-3">
    <label class="md:col-span-2 flex flex-col gap-1">
      <span class="text-sm text-surface-700 dark:text-surface-200">Project name</span>
      <input
        type="text"
        bind:value={name}
        placeholder='e.g. "Stripe checkout for the pricing page"'
        maxlength="200"
        class="rounded-md border border-surface-300 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none dark:border-surface-600 dark:bg-surface-700 dark:text-surface-50"
        data-testid="new-project-name"
      />
    </label>

    <label class="flex flex-col gap-1">
      <span class="text-sm text-surface-700 dark:text-surface-200">Kind</span>
      <select
        bind:value={projectKind}
        class="rounded-md border border-surface-300 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none dark:border-surface-600 dark:bg-surface-700 dark:text-surface-50"
        data-testid="new-project-type"
      >
        {#each KIND_OPTIONS as opt (opt.value)}
          <option value={opt.value}>{opt.label}</option>
        {/each}
      </select>
    </label>

    <label class="md:col-span-3 flex flex-col gap-1">
      <span class="text-sm text-surface-700 dark:text-surface-200">
        Describe it (the intake role uses this to draft a PRD)
      </span>
      <textarea
        bind:value={description}
        placeholder="Two or three sentences is plenty. What's the user need? What's the constraint? What does 'done' look like?"
        rows="4"
        class="rounded-md border border-surface-300 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none dark:border-surface-600 dark:bg-surface-700 dark:text-surface-50"
        data-testid="new-project-description"
      ></textarea>
    </label>

    <div class="md:col-span-3 flex items-center justify-between">
      <p class="text-xs text-surface-700/70 dark:text-surface-200/70">
        {KIND_OPTIONS.find((o) => o.value === projectKind)?.hint}
      </p>
      <button
        type="submit"
        class="btn-primary"
        disabled={submitting}
        data-testid="new-project-submit"
      >
        {submitting ? 'Creating…' : 'Start the build →'}
      </button>
    </div>
  </form>
</section>

<section class="mb-8">
  <header class="mb-3 flex items-center justify-between">
    <h2 class="text-base font-semibold text-surface-900 dark:text-surface-50">Recent projects</h2>
    {#if $pendingCount > 0}
      <a
        href="{base}/panels/decision-queue"
        class="rounded-full bg-severity-warning px-3 py-1 text-xs font-medium text-white"
      >
        {$pendingCount} pending decision{$pendingCount === 1 ? '' : 's'} →
      </a>
    {/if}
  </header>

  {#if recentLoading}
    <p class="text-sm text-surface-700/70 dark:text-surface-200/70">Loading…</p>
  {:else if recent.length === 0}
    <p class="text-sm text-surface-700/70 dark:text-surface-200/70">
      No projects yet. Use the form above to start your first one.
    </p>
  {:else}
    <ul class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {#each recent as p (p.project_id)}
        <li>
          <a
            href="{base}/projects/{p.project_id}"
            class="panel-card block transition hover:border-accent hover:shadow-md"
          >
            <h3 class="break-words text-sm font-semibold text-surface-900 dark:text-surface-50">
              {p.name}
            </h3>
            <dl class="mt-2 grid grid-cols-2 gap-1 text-xs text-surface-700 dark:text-surface-200">
              <dt>Type</dt><dd>{p.project_type}</dd>
              <dt>Phase</dt><dd>{p.current_phase}</dd>
              <dt>Status</dt><dd>{p.status}</dd>
            </dl>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<details class="rounded-md border border-surface-200 bg-white p-3 dark:border-surface-700 dark:bg-surface-800">
  <summary class="cursor-pointer text-sm font-medium text-surface-900 dark:text-surface-50">
    Hub administration · observability surfaces
  </summary>
  <p class="mt-2 text-xs text-surface-700/70 dark:text-surface-200/70">
    These panels are for operators monitoring the Hub itself — your AI workforce, integrations,
    audit ledger, vault, license, federation. You won't need any of them to ship your first
    project; the build form above is the entry point.
  </p>
  <div class="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
    {#each [
      { href: '/panels/decision-queue', title: 'Decision queue',  desc: 'Pending decision cards from AI scrum masters (#5).' },
      { href: '/panels/role-chat',      title: 'Talk to a role',  desc: 'Ad-hoc chat with any role using its charter prompt.' },
      { href: '/panels/master-roles',   title: 'Master roles',    desc: 'Master-tier role state across the federation.' },
      { href: '/panels/registry',       title: 'Registry',        desc: 'Project + agent + role registry.' },
      { href: '/panels/audit',          title: 'Audit',           desc: 'Chained audit-event explorer.' },
      { href: '/panels/vault-config',   title: 'Vault config',    desc: 'Two-party vault secret approvals (#9).' },
      { href: '/panels/integrations',   title: 'Integrations',    desc: 'GitHub / Linear / Slack / Vanta wiring.' },
      { href: '/panels/federation',     title: 'Federation',      desc: 'Hub switcher + federation topology.' },
      { href: '/panels/license',        title: 'License',         desc: 'Active license bundle + feature flags (#23).' },
      { href: '/panels/kg-search',      title: 'KG search',       desc: 'Knowledge-graph hybrid search.' }
    ] as t (t.href)}
      <a
        href="{base}{t.href}"
        class="rounded-md border border-surface-200 p-3 text-sm hover:border-accent hover:bg-surface-50 dark:border-surface-700 dark:hover:bg-surface-700"
      >
        <span class="block font-medium text-surface-900 dark:text-surface-50">{t.title}</span>
        <span class="block text-xs text-surface-700/70 dark:text-surface-200/70">{t.desc}</span>
      </a>
    {/each}
  </div>
</details>
