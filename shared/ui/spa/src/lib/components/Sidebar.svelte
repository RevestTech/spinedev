<!--
  Spine Hub SPA — Sidebar component.

  Surfaces grouped by user-job:
    BUILD       — what you do to make software
    OPERATE     — Hub itself + integrations + secrets
    GOVERNANCE  — federation across Hubs + license / entitlements

  Each item has a one-line description that surfaces as a tooltip + an
  icon glyph so the IA reads at a glance.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { isNavItemActive, navHref } from '$lib/navActive';

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
        { label: 'Hub inbox',       href: '/panels/hub-inbox',       icon: '✉', desc: 'Portfolio briefings from master directors (Hub-wide)',         shipped: true },
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

  let isDesktop = false;

  onMount(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const syncViewport = () => {
      isDesktop = mq.matches;
    };
    syncViewport();
    mq.addEventListener('change', syncViewport);

    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && open && !isDesktop) {
        onClose?.();
      }
    };
    window.addEventListener('keydown', onKeydown);

    return () => {
      mq.removeEventListener('change', syncViewport);
      window.removeEventListener('keydown', onKeydown);
    };
  });

  // {#key} below forces nav links to re-bind aria-current on client-side route changes.
  $: mobileHidden = !open && !isDesktop;
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
  id="hub-sidebar"
  class="fixed inset-y-0 left-0 z-40 w-60 transform overflow-y-auto border-r border-surface-700/60 bg-surface-900/70 p-3 backdrop-blur-md transition-transform md:static md:translate-x-0"
  class:translate-x-0={open}
  class:-translate-x-full={!open}
  aria-label="Hub surfaces"
  aria-hidden={mobileHidden ? true : undefined}
  inert={mobileHidden ? true : undefined}
>
  <nav class="flex h-full flex-col gap-5" aria-label="Sidebar">
    {#key $page.url.pathname + ($page.route.id ?? '')}
    {#each sections as section (section.title)}
      <div>
        <header class="mb-2 px-2">
          <h2 class="text-xs font-semibold uppercase tracking-widest text-accent">
            {section.title}
          </h2>
          <p class="text-sm text-surface-500">
            {section.blurb}
          </p>
        </header>
        <ul class="flex flex-col gap-0.5">
          {#each section.items as it (it.href)}
            <li>
              {#if it.shipped}
                <a
                  href={navHref(it.href)}
                  title={it.desc}
                  aria-label="{it.label} — {it.desc}"
                  aria-current={isNavItemActive($page.url.pathname, it.href, $page.route.id)
                    ? 'page'
                    : undefined}
                  class="sidebar-nav-link group"
                  data-testid="sidebar-nav-{it.href.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'home'}"
                  data-nav-active={isNavItemActive($page.url.pathname, it.href, $page.route.id)
                    ? 'true'
                    : 'false'}
                  data-sveltekit-preload-data="hover"
                  tabindex={mobileHidden ? -1 : undefined}
                  on:click={() => onClose?.()}
                >
                  <span
                    class="w-4 text-center text-base leading-none {isNavItemActive(
                      $page.url.pathname,
                      it.href,
                      $page.route.id
                    )
                      ? 'opacity-100'
                      : 'opacity-70 group-hover:opacity-100'}"
                    aria-hidden="true"
                  >{it.icon}</span>
                  <span class="flex-1">{it.label}</span>
                </a>
              {:else}
                <span
                  class="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-surface-500"
                  title="{it.desc} Not available in this Hub build yet."
                  aria-disabled="true"
                >
                  <span class="w-4 text-center opacity-50" aria-hidden="true">{it.icon}</span>
                  <span class="flex-1">{it.label}</span>
                  <span class="text-[0.6rem] uppercase tracking-wide text-surface-600">planned</span>
                </span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
    {/key}
  </nav>
</aside>
