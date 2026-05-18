<!--
  Spine Hub SPA — landing dashboard (V3 Wave 3 part 2, Squad SPA1).

  Lightweight tile grid that mirrors the 9 Hub surfaces (#3). Each tile
  links to its panel — Squad SPA1 ships the two driver examples
  (decision-queue + role-chat); the remaining 7 link to the SPA2/SPA3
  routes that will be added in the same Wave 3 part 2 sprint.

  Responsive grid: 1 column on xs/iPhone, 2 columns md (iPad portrait),
  3 columns lg (desktop). No horizontal scroll required at any viewport.
-->
<script lang="ts">
  import PanelHeader from '$lib/components/PanelHeader.svelte';
  import { user } from '$lib/stores/user';
  import { pendingCount } from '$lib/stores/decisions';

  interface Tile {
    href: string;
    title: string;
    description: string;
    shipped: boolean;
    badge?: string;
  }

  $: tiles = [
    {
      href: '/panels/decision-queue',
      title: 'Decision queue',
      description: 'Pending decisions pushed by AI Scrum Master / PM / Release Manager (per #5).',
      shipped: true,
      badge: $pendingCount > 0 ? `${$pendingCount} pending` : undefined
    },
    {
      href: '/panels/role-chat',
      title: 'Talk to a role',
      description: 'Ad-hoc chat with any configured role using its charter prompt.',
      shipped: true
    },
    { href: '/panels/master-roles', title: 'Master roles', description: 'Master-tier role state across the federation.', shipped: false },
    { href: '/panels/registry', title: 'Registry', description: 'Project + agent + role registry.', shipped: false },
    { href: '/panels/audit', title: 'Audit', description: 'Chained audit-event explorer.', shipped: false },
    { href: '/panels/vault-config', title: 'Vault config', description: 'Two-party vault secret approvals (per #9).', shipped: false },
    { href: '/panels/integrations', title: 'Integrations', description: 'Slack / Teams / Vanta / Drata wiring.', shipped: false },
    { href: '/panels/federation', title: 'Federation', description: 'Hub switcher + federation topology.', shipped: false },
    { href: '/panels/license', title: 'License', description: 'Active license bundle + feature flags (per #23).', shipped: false }
  ] satisfies Tile[];
</script>

<PanelHeader
  title={`Welcome${$user?.username ? ', ' + $user.username : ''}`}
  subtitle="Hub control plane — pick a surface to begin"
/>

<section class="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 lg:grid-cols-3">
  {#each tiles as tile (tile.href)}
    {#if tile.shipped}
      <a
        href={tile.href}
        class="panel-card flex flex-col gap-2 transition hover:border-accent hover:shadow-md"
      >
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">{tile.title}</h2>
          {#if tile.badge}
            <span class="rounded-full bg-severity-warning px-2 py-0.5 text-xs text-white">
              {tile.badge}
            </span>
          {/if}
        </div>
        <p class="text-sm text-surface-700 dark:text-surface-200">{tile.description}</p>
      </a>
    {:else}
      <div class="panel-card flex flex-col gap-2 opacity-60" aria-disabled="true">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-surface-900 dark:text-surface-50">{tile.title}</h2>
          <span class="rounded-full bg-surface-200 px-2 py-0.5 text-xs text-surface-700 dark:bg-surface-700 dark:text-surface-100">
            soon
          </span>
        </div>
        <p class="text-sm text-surface-700 dark:text-surface-200">{tile.description}</p>
      </div>
    {/if}
  {/each}
</section>
