<!--
  Spine Hub SPA — Sidebar component (V3 Wave 3 part 2, Squad SPA1).

  Lists the 9 Hub surfaces enumerated in design decision #3. The two
  example panels shipped by Squad SPA1 (decision-queue, role-chat) link
  through; the remaining 8 are rendered disabled until SPA2 / SPA3 land
  the corresponding pages. The full set is intentionally visible so the
  navigation IA is stable from the user's first session.

  Responsive: off-canvas drawer < md, persistent rail >= md.
-->
<script lang="ts">
  import { page } from '$app/stores';

  export let open = false;
  export let onClose: (() => void) | null = null;

  interface NavItem {
    label: string;
    href: string;
    surface: string; // matches the 9 surfaces in #3
    shipped: boolean; // false while SPA2/SPA3 build it
  }

  // Order mirrors the enumeration in V3_DESIGN_DECISIONS.md #3.
  // All 10 surfaces shipped 2026-05-18 across SPA1+SPA2+SPA3.
  const items: NavItem[] = [
    { label: 'Dashboard', href: '/', surface: 'dashboard', shipped: true },
    { label: 'Decision queue', href: '/panels/decision-queue', surface: 'decisions', shipped: true },
    { label: 'Talk to a role', href: '/panels/role-chat', surface: 'role_chat', shipped: true },
    { label: 'Master roles', href: '/panels/master-roles', surface: 'master_roles', shipped: true },
    { label: 'Registry', href: '/panels/registry', surface: 'registry', shipped: true },
    { label: 'Audit', href: '/panels/audit', surface: 'audit', shipped: true },
    { label: 'Vault config', href: '/panels/vault-config', surface: 'vault_config', shipped: true },
    { label: 'Integrations', href: '/panels/integrations', surface: 'integrations', shipped: true },
    { label: 'Federation', href: '/panels/federation', surface: 'federation', shipped: true },
    { label: 'License', href: '/panels/license', surface: 'license', shipped: true },
    { label: 'KG search', href: '/panels/kg-search', surface: 'kg_search', shipped: true }
  ];
</script>

<!-- Backdrop (mobile only) -->
{#if open}
  <button
    type="button"
    aria-label="Close navigation"
    class="fixed inset-0 z-30 bg-black/40 md:hidden"
    on:click={() => onClose?.()}
  ></button>
{/if}

<aside
  class="fixed inset-y-0 left-0 z-40 w-64 transform border-r border-surface-200 bg-white p-3 transition-transform dark:border-surface-700 dark:bg-surface-800 md:static md:translate-x-0"
  class:translate-x-0={open}
  class:-translate-x-full={!open}
  aria-label="Hub surfaces"
>
  <nav class="flex h-full flex-col gap-1">
    {#each items as it (it.surface)}
      {#if it.shipped}
        <a
          href={it.href}
          class="flex items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-surface-100 dark:hover:bg-surface-700"
          class:bg-accent={$page.url.pathname === it.href}
          class:text-white={$page.url.pathname === it.href}
          on:click={() => onClose?.()}
        >
          <span>{it.label}</span>
        </a>
      {:else}
        <span
          class="flex items-center justify-between rounded-md px-3 py-2 text-sm text-surface-700/60 dark:text-surface-200/60"
          title="Shipped by Squad SPA2/SPA3 in Wave 3 part 2"
        >
          <span>{it.label}</span>
          <span class="text-[0.65rem] uppercase tracking-wide">soon</span>
        </span>
      {/if}
    {/each}
  </nav>
</aside>
