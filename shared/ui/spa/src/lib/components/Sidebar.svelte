<!--
  Spine Hub SPA — Sidebar component.

  Surfaces grouped by user-job:
    BUILD       — what you do to make software
    OBSERVE     — what's happening + history
    OPERATE     — Hub itself + integrations + secrets
    GOVERNANCE  — federation across Hubs + license / entitlements

  Each item has a one-line description that surfaces as a tooltip + an
  icon glyph so the IA reads at a glance.
-->
<script lang="ts">
  import { page } from '$app/stores';
  import { base } from '$app/paths';

  export let open = false;
  export let onClose: (() => void) | null = null;

  interface NavItem {
    label: string;
    href: string;
    icon: string;       // single glyph; cheap, no icon-pkg dependency
    desc: string;       // tooltip + screen-reader supplement
    shipped: boolean;
  }
  interface NavSection {
    title: string;
    blurb: string;      // shown small under the section title
    items: NavItem[];
  }

  const sections: NavSection[] = [
    {
      title: 'Build',
      blurb: 'Make software',
      items: [
        { label: 'Dashboard',       href: '/',                       icon: '⌂', desc: 'Start a new project; recent projects',                           shipped: true },
        { label: 'Projects',        href: '/projects',               icon: '▤', desc: 'All projects in this Hub with SDLC phase + status',            shipped: true },
        { label: 'Decisions',       href: '/panels/decision-queue',  icon: '✓', desc: 'Approval cards waiting on you (PRD, TRD, code review…)',       shipped: true },
        { label: 'Talk to a role',  href: '/panels/role-chat',       icon: '✎', desc: 'Ad-hoc chat with any role (product, architect, engineer, qa…)', shipped: true },
      ]
    },
    {
      title: 'Observe',
      blurb: 'What is happening',
      items: [
        { label: 'Audit log',     href: '/panels/audit',     icon: '⌽', desc: 'Hash-chained ledger — every LLM call, every role action',         shipped: true },
        { label: 'Knowledge graph', href: '/panels/kg-search', icon: '◈', desc: 'Search the project KG — symbols, files, decisions, citations',   shipped: true },
      ]
    },
    {
      title: 'Operate',
      blurb: 'Hub configuration',
      items: [
        { label: 'Master roles',  href: '/panels/master-roles', icon: '◐', desc: 'Master-tier role state (PM, Architect, QA, DevOps, …)',           shipped: true },
        { label: 'Registry',      href: '/panels/registry',     icon: '◇', desc: 'Catalog of roles + integrations the Hub knows about',            shipped: true },
        { label: 'Integrations',  href: '/panels/integrations', icon: '⌶', desc: 'External systems wired in (GitHub, Linear, Slack, Vanta, …)',    shipped: true },
        { label: 'Vault',         href: '/panels/vault-config', icon: '🔒', desc: 'Secret paths the Hub references (per design decision #9)',      shipped: true },
      ]
    },
    {
      title: 'Governance',
      blurb: 'Across the org',
      items: [
        { label: 'Federation', href: '/panels/federation', icon: '⌬', desc: 'Hub-to-Hub topology — link this Hub to others in your org',       shipped: true },
        { label: 'License',    href: '/panels/license',    icon: '◍', desc: 'Active license bundle + feature flags (per design decision #23)', shipped: true },
      ]
    }
  ];

  $: pathname = $page.url.pathname;
  function isActive(href: string): boolean {
    if (href === '/') return pathname === base + '/' || pathname === base;
    return pathname === base + href;
  }
</script>

<!-- Backdrop (mobile only) -->
{#if open}
  <button
    type="button"
    aria-label="Close navigation"
    class="fixed inset-0 z-30 bg-black/60 md:hidden"
    on:click={() => onClose?.()}
  ></button>
{/if}

<aside
  class="fixed inset-y-0 left-0 z-40 w-72 transform overflow-y-auto border-r border-surface-700/60 bg-surface-900/70 p-4 backdrop-blur-md transition-transform md:static md:translate-x-0"
  class:translate-x-0={open}
  class:-translate-x-full={!open}
  aria-label="Hub surfaces"
>
  <nav class="flex h-full flex-col gap-5">
    {#each sections as section (section.title)}
      <div>
        <header class="mb-2 px-2">
          <h2 class="text-[0.7rem] font-semibold uppercase tracking-widest text-accent">
            {section.title}
          </h2>
          <p class="text-[0.65rem] text-surface-500">
            {section.blurb}
          </p>
        </header>
        <ul class="flex flex-col gap-0.5">
          {#each section.items as it (it.href)}
            <li>
              {#if it.shipped}
                <a
                  href={base + it.href}
                  title={it.desc}
                  aria-label="{it.label} — {it.desc}"
                  class="group flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm text-surface-300 transition-all hover:bg-surface-800/80 hover:text-white"
                  class:!bg-gradient-brand={isActive(it.href)}
                  class:!text-white={isActive(it.href)}
                  class:shadow-glow-sm={isActive(it.href)}
                  on:click={() => onClose?.()}
                >
                  <span class="mt-0.5 w-4 text-center text-base leading-none opacity-70 group-hover:opacity-100">{it.icon}</span>
                  <span class="flex-1">
                    <span class="block font-medium">{it.label}</span>
                    <span
                      class="block text-[0.65rem] leading-tight {isActive(it.href) ? 'text-white/80' : 'text-surface-500 group-hover:text-surface-300'}"
                    >{it.desc}</span>
                  </span>
                </a>
              {:else}
                <span
                  class="flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm text-surface-500"
                  title="Coming soon"
                >
                  <span class="mt-0.5 w-4 text-center opacity-50">{it.icon}</span>
                  <span class="flex-1">
                    <span class="block">{it.label}</span>
                    <span class="block text-[0.65rem] text-surface-600">{it.desc}</span>
                  </span>
                  <span class="text-[0.6rem] uppercase tracking-wide text-surface-600">soon</span>
                </span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </nav>
</aside>
