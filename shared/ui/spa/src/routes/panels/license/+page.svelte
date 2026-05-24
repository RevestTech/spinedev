<!--
  Spine Hub SPA — License panel (V3 Wave 3 part 2, Squad SPA3).

  Surfaces backend at shared/api/routes/license.py:
    GET /api/v2/license         → LicenseSummary  (tier + bundle_id + flags[])
    GET /api/v2/license/usage   → UsageResponse   (per-flag counters)

  Per design decisions:
    - #12 Cite-or-Refuse: both responses carry a `citation` (file:line or
          signed-bundle hash) which we render as a CitationChip.
    - #23 Licensing as product discovery: each flag row shows
          enabled / quota_used / remaining; disabled flags surface an
          inline "upgrade tier" CTA (today: mailto:, Wave 4 wires a real
          in-app upgrade flow).
    - #9  Never display secret VALUES — the license bundle is metadata
          only; nothing here is sensitive.
    - #28 Responsive: 1 col phone, 2 col tablet, 3 col desktop on the
          flag matrix.

  Backend gaps (filed for Wave 4):
    - Wave 3 part 1 stub returns count=0 for every flag — the panel
      renders the durable shape today so swapping in real spine_license
      counters needs zero SPA churn.
    - Signature verification status (trusted vendor fingerprint match +
      last verify timestamp): backend exposes `signed: bool` but no
      fingerprint yet. Panel renders a "signature: unverified (stub)"
      indicator and leaves the slot wired for Wave 4 to fill.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { api } from '$lib/api/client';
  import type { Citation } from '$lib/api/types';

  type LicenseTier = 'free' | 'founder' | 'team' | 'enterprise' | 'airgapped';

  interface FlagStatus {
    flag: string;
    enabled: boolean;
  }
  interface LicenseSummary {
    ok: boolean;
    tier: LicenseTier;
    bundle_id: string;
    expires_at: string;
    signed: boolean;
    flags: FlagStatus[];
    citation: string | null;
  }
  interface UsageCounter {
    flag: string;
    count: number;
    last_used_at?: string | null;
  }
  interface UsageResponse {
    ok: boolean;
    items: UsageCounter[];
    citation: string | null;
  }

  let loading = true;
  let error: string | null = null;
  let summary: LicenseSummary | null = null;
  let usage: UsageResponse | null = null;

  async function load() {
    loading = true;
    error = null;
    try {
      const [s, u] = await Promise.all([
        api.get<LicenseSummary>('/api/v2/license'),
        api.get<UsageResponse>('/api/v2/license/usage')
      ]);
      summary = s;
      usage = u;
    } catch (err) {
      error = (err as Error).message || 'failed to load license';
      summary = null;
      usage = null;
    } finally {
      loading = false;
    }
  }

  // Wave 4 ships real quotas; for now treat all flags as "unlimited" when
  // enabled, "0/0" when disabled. The shape mirrors the durable contract.
  interface FlagRow {
    flag: string;
    enabled: boolean;
    quota: number | null; // null = unlimited
    used: number;
  }

  $: rows = (summary?.flags ?? []).map<FlagRow>((f) => {
    const usageRow = (usage?.items ?? []).find((u) => u.flag === f.flag);
    return {
      flag: f.flag,
      enabled: f.enabled,
      quota: null, // Wave 4 — sourced from spine_license.quota_value
      used: usageRow?.count ?? 0
    };
  });

  function remaining(r: FlagRow): string {
    if (!r.enabled) return 'disabled';
    if (r.quota === null) return 'unlimited';
    return String(Math.max(0, r.quota - r.used));
  }

  function chipFor(citationRef: string | null | undefined): Citation | null {
    if (!citationRef) return null;
    // Heuristic: if it looks like 'path:line' it's a file_line citation,
    // otherwise fall back to audit_hash. Matches the keys backend emits.
    const isFile = /^[\w./-]+:\d+/.test(citationRef) || citationRef.includes('/');
    return { type: isFile ? 'file_line' : 'audit_hash', ref: citationRef };
  }

  function upgradeMailto(flag: string): string {
    const subject = `Spine: upgrade tier to unlock ${flag}`;
    const body = `Hi Spine team,\n\nI'd like to upgrade my license to enable the "${flag}" flag.\n\nThanks.`;
    return `mailto:sales@spine.app?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  onMount(load);
</script>

<PanelHeader
  title="License & usage"
  subtitle="Tier, feature flags, quota usage, and signature verification (#23)"
>
  <button type="button" class="btn-ghost" on:click={load} aria-label="Refresh license">
    Refresh
  </button>
</PanelHeader>

{#if error}
  <div class="mb-4"><ErrorBanner kind="error" message={error} onDismiss={() => (error = null)} /></div>
{/if}

{#if loading && !summary}
  <div class="flex items-center justify-center py-10"><LoadingSpinner label="Loading license" /></div>
{:else if !summary}
  <EmptyState title="No license data" message="The license endpoint returned nothing." />
{:else}
  <!-- Summary card: tier + bundle + signature + citation -->
  <section class="panel-card mb-4 flex flex-col gap-2" data-testid="license-summary">
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 class="text-sm font-semibold uppercase text-surface-700 dark:text-surface-200">
          Active tier
        </h2>
        <p class="text-2xl font-bold capitalize" data-testid="tier-label">
          {summary.tier}
        </p>
        <p class="font-mono text-[0.65rem] text-surface-700 dark:text-surface-200">
          {summary.bundle_id}
        </p>
      </div>
      <div class="flex flex-col items-end gap-1 text-xs">
        <span>expires <b>{new Date(summary.expires_at).toLocaleDateString()}</b></span>
        <span
          class="rounded-full px-2 py-0.5 text-[0.65rem] uppercase"
          class:bg-emerald-100={summary.signed}
          class:text-emerald-900={summary.signed}
          class:bg-amber-100={!summary.signed}
          class:text-amber-900={!summary.signed}
          data-testid="signature-status"
        >
          {summary.signed ? 'signature verified' : 'signature unverified'}
        </span>
      </div>
    </div>
    {#if chipFor(summary.citation)}
      <div class="flex items-center gap-1">
        <span class="text-[0.65rem] text-surface-700 dark:text-surface-200">bundle ref:</span>
        <CitationChip citation={chipFor(summary.citation)} />
      </div>
    {/if}
  </section>

  <!-- Per-flag matrix -->
  <h2 class="mb-2 text-xs font-semibold uppercase text-surface-700 dark:text-surface-200">
    Feature flags
  </h2>
  <ul
    class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3"
    data-testid="flag-matrix"
  >
    {#each rows as r (r.flag)}
      <li
        class="panel-card border-l-4"
        class:border-l-emerald-400={r.enabled}
        class:border-l-surface-300={!r.enabled}
        data-testid="flag-row"
        data-flag={r.flag}
        data-enabled={String(r.enabled)}
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate font-mono text-sm">{r.flag}</p>
            <p class="text-[0.65rem] text-surface-700 dark:text-surface-200">
              quota: {r.quota === null ? '∞' : r.quota} · used: <b>{r.used}</b> · remaining: <b>{remaining(r)}</b>
            </p>
          </div>
          {#if r.enabled}
            <span class="rounded-full bg-emerald-100 px-2 py-0.5 text-[0.6rem] uppercase text-emerald-900">
              on
            </span>
          {:else}
            <span class="rounded-full bg-surface-200 px-2 py-0.5 text-[0.6rem] uppercase text-surface-700">
              off
            </span>
          {/if}
        </div>
        {#if !r.enabled}
          <a
            href={upgradeMailto(r.flag)}
            class="mt-2 inline-block text-[0.65rem] underline text-accent"
            data-testid="upgrade-cta"
          >
            Upgrade tier to unlock
          </a>
        {/if}
      </li>
    {/each}
  </ul>

  {#if chipFor(usage?.citation)}
    <div class="mt-4 flex items-center gap-1 text-[0.65rem] text-surface-700 dark:text-surface-200">
      <span>usage ref:</span>
      <CitationChip citation={chipFor(usage?.citation)} />
    </div>
  {/if}
{/if}
