<!--
  Spine Hub SPA — Federation panel (V3 Wave 3 part 2, Squad SPA3).

  Surfaces backend at shared/api/routes/federation.py:
    GET  /api/v2/federation/hubs            → HubListResponse  (parent + peers + children)
    GET  /api/v2/federation/status          → FederationStatusResponse (local posture)
    POST /api/v2/federation/register-child  (hub-admin only)
    POST /api/v2/federation/consent         (hub-admin only)

  Per design decisions:
    - #4  Fractal Hub: same SPA serves customer Hub + Spine-internal Hub
    - #10 "a Hub is a Hub is a Hub": this Hub may be BOTH parent (of children)
          AND child (of its parent). The visual surfaces both sides as a
          simple tree (parent above local; children below; peers right-of).
    - #12 Cite-or-Refuse: register-child + consent rationale carry an
          audit_event_uuid we render as a CitationChip (audit_hash type)
    - #16 Update cascade: pending updates per child surface as badges;
          approve/reject buttons stub-call POST /federation/consent until
          Wave 4 wires a dedicated /update-approval endpoint.
    - #28 Mobile-responsive: stacks vertically < md; tree branches collapse.

  Wave 4 follow-ups (not in scope here):
    - Real graph viz (d3-hierarchy / cytoscape) — Squad chose plain
      tree-of-cards over a viz lib because (a) no npm install, (b) the
      topology rarely exceeds ~10 nodes in practice, (c) it stays
      keyboard-accessible. Graph viz is a v1.1 enhancement.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { api } from '$lib/api/client';
  import { toasts } from '$lib/stores/toasts';
  import type { Citation } from '$lib/api/types';

  // Mirror shared/api/routes/federation.py shapes (until codegen lands).
  type HubRole = 'root' | 'parent' | 'peer' | 'child';
  type ConsentDecision = 'accepted' | 'rejected' | 'pending';

  interface SpineEntry {
    project_id: string;
    name: string;
    project_type: string;
    current_phase: string;
    status: string;
    owner?: string;
    updated_at?: string;
  }

  interface HubEntry {
    hub_id: string;
    name: string;
    role: HubRole;
    url?: string | null;
    consent: ConsentDecision;
    running_spines?: SpineEntry[];
  }
  interface HubListResponse {
    ok: boolean;
    local_hub_id: string;
    items: HubEntry[];
  }
  interface FederationStatusResponse {
    ok: boolean;
    local_hub_id: string;
    parent_hub_id?: string | null;
    children_count: number;
    peers_count: number;
  }

  let loading = true;
  let error: string | null = null;
  let hubs: HubEntry[] = [];
  let posture: FederationStatusResponse | null = null;

  let localProjects: SpineEntry[] = [];
  let showAutomatedLocalSpines = false;

  $: filteredLocalSpines = localProjects.filter(p => {
    if (showAutomatedLocalSpines) return true;
    const isSmokeOwner = p.owner === 'smoke-harness';
    const isSmokeName = p.name ? p.name.startsWith('smoke-') : false;
    return !isSmokeOwner && !isSmokeName;
  });

  // Register-child form state
  let showRegisterForm = false;
  let form = { hub_id: '', name: '', url: '', rationale: '' };
  let submitting = false;
  let lastRegistrationCitation: Citation | null = null;

  async function load() {
    loading = true;
    error = null;
    try {
      const [list, stat, projRes] = await Promise.all([
        api.get<HubListResponse>('/api/v2/federation/hubs'),
        api.get<FederationStatusResponse>('/api/v2/federation/status'),
        api.get<{ items: (string | SpineEntry)[] }>('/api/v2/projects?limit=200')
      ]);
      hubs = list.items ?? [];
      posture = stat;
      localProjects = (projRes.items ?? []).map((it) =>
        typeof it === 'string' ? (JSON.parse(it) as SpineEntry) : it
      );
    } catch (err) {
      error = (err as Error).message || 'failed to load federation graph';
      hubs = [];
      posture = null;
      localProjects = [];
    } finally {
      loading = false;
    }
  }

  async function registerChild(e: SubmitEvent) {
    e.preventDefault();
    if (submitting) return;
    if (!form.hub_id || !form.name || !form.url || !form.rationale) {
      toasts.push({ kind: 'error', message: 'All fields required (rationale per #12)' });
      return;
    }
    submitting = true;
    try {
      const resp = await api.post<{
        ok: boolean;
        hub_id: string;
        actor: string;
        audit_event_uuid: string;
      }>('/api/v2/federation/register-child', { ...form });
      lastRegistrationCitation = { type: 'audit_hash', ref: resp.audit_event_uuid };
      toasts.push({ kind: 'success', message: `Registered child ${resp.hub_id}` });
      form = { hub_id: '', name: '', url: '', rationale: '' };
      showRegisterForm = false;
      await load();
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'register failed' });
    } finally {
      submitting = false;
    }
  }

  async function decideConsent(hub: HubEntry, decision: ConsentDecision) {
    try {
      const resp = await api.post<{
        ok: boolean;
        hub_id: string;
        decision: ConsentDecision;
        audit_event_uuid: string;
      }>('/api/v2/federation/consent', {
        hub_id: hub.hub_id,
        decision,
        rationale: `Operator ${decision} via SPA federation panel for hub ${hub.hub_id}`
      });
      toasts.push({
        kind: 'success',
        message: `Consent ${resp.decision} for ${hub.hub_id}`
      });
      lastRegistrationCitation = { type: 'audit_hash', ref: resp.audit_event_uuid };
      await load();
    } catch (err) {
      toasts.push({ kind: 'error', message: (err as Error).message || 'consent failed' });
    }
  }

  $: parents = hubs.filter((h) => h.role === 'parent' || h.role === 'root');
  $: peers = hubs.filter((h) => h.role === 'peer');
  $: children = hubs.filter((h) => h.role === 'child');

  const consentTone: Record<ConsentDecision, string> = {
    accepted: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100',
    rejected: 'bg-rose-100 text-rose-900 dark:bg-rose-900 dark:text-rose-100',
    pending: 'bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100'
  };

  onMount(load);
</script>

<PanelHeader
  title="Federation"
  subtitle="Hub-of-Hubs topology — this Hub may be both parent and child (#10)"
>
  <button
    type="button"
    class="btn-ghost"
    on:click={() => (showRegisterForm = !showRegisterForm)}
    data-testid="toggle-register"
  >
    {showRegisterForm ? 'Close' : 'Register child Hub'}
  </button>
  <button type="button" class="btn-ghost" on:click={load} aria-label="Refresh federation">
    Refresh
  </button>
</PanelHeader>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if lastRegistrationCitation}
  <div class="mb-3 flex items-center gap-2 text-xs text-surface-700 dark:text-surface-200">
    <span>Last audit:</span>
    <CitationChip citation={lastRegistrationCitation} />
  </div>
{/if}

{#if showRegisterForm}
  <form
    class="panel-card mb-4 flex flex-col gap-3"
    on:submit={registerChild}
    data-testid="register-form"
  >
    <h2 class="text-sm font-semibold">Register a downstream child Hub</h2>
    <label class="flex flex-col gap-1 text-xs">
      <span>Hub ID</span>
      <input class="rounded border border-surface-200 px-2 py-1" bind:value={form.hub_id}
             data-testid="form-hub-id" />
    </label>
    <label class="flex flex-col gap-1 text-xs">
      <span>Display name</span>
      <input class="rounded border border-surface-200 px-2 py-1" bind:value={form.name}
             data-testid="form-name" />
    </label>
    <label class="flex flex-col gap-1 text-xs">
      <span>URL</span>
      <input class="rounded border border-surface-200 px-2 py-1" type="url"
             bind:value={form.url} data-testid="form-url" />
    </label>
    <label class="flex flex-col gap-1 text-xs">
      <span>Rationale (audited per #12)</span>
      <textarea class="rounded border border-surface-200 px-2 py-1" rows="2"
                bind:value={form.rationale} data-testid="form-rationale"></textarea>
    </label>
    <div class="flex justify-end">
      <button type="submit" class="btn-primary" disabled={submitting} data-testid="form-submit">
        {submitting ? 'Submitting…' : 'Register child'}
      </button>
    </div>
  </form>
{/if}

{#if loading && hubs.length === 0}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading federation" /></div>
{:else if !posture}
  <EmptyState title="No federation data" message="The federation status endpoint returned nothing." />
{:else}
  <section class="flex flex-col gap-4" data-testid="federation-tree">
    <!-- Parent / Root tier (#10 — this Hub may be a child of another) -->
    {#if parents.length > 0}
      <div>
        <h2 class="mb-2 text-xs font-semibold uppercase text-surface-700 dark:text-surface-200">
          Upstream parent
        </h2>
        <ul class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
          {#each parents as p (p.hub_id)}
            <li class="panel-card border-l-4 border-l-blue-400" data-testid="hub-node" data-role={p.role}>
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono text-sm">{p.hub_id}</span>
                <span class="rounded-full px-2 py-0.5 text-[0.65rem] uppercase {consentTone[p.consent]}">
                  {p.consent}
                </span>
              </div>
              <p class="text-xs text-surface-700 dark:text-surface-200">{p.name}</p>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- Local Hub posture (this row anchors the visualisation) -->
    <div class="panel-card border-l-4 border-l-accent" data-testid="local-hub">
      <div class="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 class="text-sm font-semibold">This Hub</h2>
          <p class="font-mono text-xs">{posture.local_hub_id}</p>
        </div>
        <div class="flex flex-wrap gap-2 text-xs">
          <span>parent: <b>{posture.parent_hub_id ?? '(none)'}</b></span>
          <span>peers: <b>{posture.peers_count}</b></span>
          <span>children: <b>{posture.children_count}</b></span>
        </div>
      </div>

      <!-- Local running spines list -->
      <div class="mt-4 border-t border-surface-200 pt-3 dark:border-surface-700">
        <div class="flex flex-col xs:flex-row xs:items-center justify-between gap-2 mb-2">
          <h3 class="text-[0.7rem] font-bold uppercase tracking-wider text-surface-700/80 dark:text-surface-200/80">
            Local Running Spines
          </h3>
          <label class="flex items-center gap-1.5 text-[0.65rem] text-surface-700/80 dark:text-surface-200/80 cursor-pointer">
            <input type="checkbox" bind:checked={showAutomatedLocalSpines} class="rounded border-surface-300 text-accent focus:ring-accent" />
            Show automated runs
          </label>
        </div>
        {#if filteredLocalSpines.length === 0}
          <p class="text-xs text-surface-700/60 dark:text-surface-200/60 italic">No running spines</p>
        {:else}
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
            {#each filteredLocalSpines as spine}
              <div class="flex flex-col justify-between rounded bg-surface-50 p-2 text-xs dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                <div class="flex items-center justify-between gap-2 mb-1">
                  <a href="{base}/projects/{spine.project_id}" class="font-semibold text-accent hover:underline truncate max-w-[140px]" title={spine.name}>
                    {spine.name}
                  </a>
                  <span class="rounded px-1.5 py-0.5 text-[0.6rem] bg-accent/10 text-accent font-mono uppercase font-bold">
                    {spine.current_phase}
                  </span>
                </div>
                <div class="flex items-center justify-between text-[0.65rem] text-surface-700/60 dark:text-surface-200/60">
                  <span class="capitalize">{spine.project_type} · {spine.status}</span>
                  <span>{spine.owner || ''}</span>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <!-- Peers tier -->
    {#if peers.length > 0}
      <div>
        <h2 class="mb-2 text-xs font-semibold uppercase text-surface-700 dark:text-surface-200">
          Peers
        </h2>
        <ul class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
          {#each peers as p (p.hub_id)}
            <li class="panel-card border-l-4 border-l-blue-400" data-testid="hub-node" data-role={p.role}>
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono text-sm">{p.hub_id}</span>
                <span class="rounded-full px-2 py-0.5 text-[0.65rem] uppercase {consentTone[p.consent]}">
                  {p.consent}
                </span>
              </div>
              <p class="text-xs text-surface-700 dark:text-surface-200">{p.name}</p>

              <!-- Federated peer spines -->
              {#if p.running_spines && p.running_spines.length > 0}
                <div class="mt-3 border-t border-surface-200 pt-2 dark:border-surface-700">
                  <h4 class="text-[0.65rem] font-bold uppercase tracking-wider text-surface-700/80 dark:text-surface-200/80 mb-1.5">
                    Federated Spines
                  </h4>
                  <div class="flex flex-col gap-1.5">
                    {#each p.running_spines as spine}
                      <div class="flex items-center justify-between rounded bg-surface-50 p-1.5 text-[0.7rem] dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                        <span class="font-medium truncate max-w-[120px] text-surface-700 dark:text-surface-200" title={spine.name}>
                          {spine.name}
                        </span>
                        <div class="flex items-center gap-1.5">
                          <span class="rounded px-1.5 py-0.5 text-[0.55rem] bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 font-mono uppercase font-bold">
                            {spine.current_phase}
                          </span>
                        </div>
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}

              {#if p.consent === 'pending'}
                <div class="mt-2 flex flex-col gap-1 xs:flex-row">
                  <button class="btn-ghost text-xs" on:click={() => decideConsent(p, 'accepted')}
                          data-testid="consent-accept">Accept</button>
                  <button class="btn-ghost text-xs" on:click={() => decideConsent(p, 'rejected')}
                          data-testid="consent-reject">Reject</button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- Children tier (#16 update-cascade approvals live here) -->
    {#if children.length > 0}
      <div>
        <h2 class="mb-2 text-xs font-semibold uppercase text-surface-700 dark:text-surface-200">
          Downstream children
        </h2>
        <ul class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
          {#each children as c (c.hub_id)}
            <li class="panel-card border-l-4 border-l-emerald-400" data-testid="hub-node" data-role={c.role}>
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono text-sm">{c.hub_id}</span>
                <span class="rounded-full px-2 py-0.5 text-[0.65rem] uppercase {consentTone[c.consent]}">
                  {c.consent}
                </span>
              </div>
              <p class="text-xs text-surface-700 dark:text-surface-200">{c.name}</p>
              {#if c.url}
                <p class="truncate font-mono text-[0.65rem] text-surface-700 dark:text-surface-200">
                  {c.url}
                </p>
              {/if}

              <!-- Federated child spines -->
              {#if c.running_spines && c.running_spines.length > 0}
                <div class="mt-3 border-t border-surface-200 pt-2 dark:border-surface-700">
                  <h4 class="text-[0.65rem] font-bold uppercase tracking-wider text-surface-700/80 dark:text-surface-200/80 mb-1.5">
                    Federated Spines
                  </h4>
                  <div class="flex flex-col gap-1.5">
                    {#each c.running_spines as spine}
                      <div class="flex items-center justify-between rounded bg-surface-50 p-1.5 text-[0.7rem] dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                        <span class="font-medium truncate max-w-[120px] text-surface-700 dark:text-surface-200" title={spine.name}>
                          {spine.name}
                        </span>
                        <div class="flex items-center gap-1.5">
                          <span class="rounded px-1.5 py-0.5 text-[0.55rem] bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 font-mono uppercase font-bold">
                            {spine.current_phase}
                          </span>
                        </div>
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}

              {#if c.consent === 'pending'}
                <div class="mt-2 flex flex-col gap-1 xs:flex-row">
                  <button class="btn-ghost text-xs" on:click={() => decideConsent(c, 'accepted')}
                          data-testid="cascade-approve">Approve update</button>
                  <button class="btn-ghost text-xs" on:click={() => decideConsent(c, 'rejected')}
                          data-testid="cascade-reject">Reject update</button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if hubs.length === 0}
      <EmptyState
        title="No federated Hubs yet"
        message="Register a child Hub to start a topology, or wait for a parent to invite this Hub."
      />
    {/if}
  </section>
{/if}
