<!--
  Spine Hub SPA — Topbar component (V3 Wave 3 part 2, Squad SPA1).

  Responsive: collapses to a hamburger + logo on viewports < md.
  Includes the federation hub-id chip (per #4 / #10) and the user menu.
-->
<script lang="ts">
  import { page } from '$app/stores';
  import { isNavItemActive, navHref } from '$lib/navActive';
  import { user } from '$lib/stores/user';
  import { pendingCount } from '$lib/stores/decisions';
  import { hubInboxCount } from '$lib/stores/hubInbox';

  export let title: string = 'Spine Hub';
  export let sidebarOpen = false;
  export let onToggleSidebar: (() => void) | null = null;

  $: hubId = $user?.hub_id ?? 'hub-local';
</script>

<header
  class="sticky top-0 z-20 flex min-h-[3.75rem] items-center justify-between border-b border-surface-700/60 bg-surface-900/90 px-3 backdrop-blur-md xs:px-4 md:px-6"
>
  <div class="flex min-w-0 items-center gap-2 md:gap-3">
    {#if onToggleSidebar}
      <button
        type="button"
        class="btn-ghost px-2 text-lg md:hidden"
        aria-label={sidebarOpen ? 'Close navigation menu' : 'Open navigation menu'}
        aria-expanded={sidebarOpen}
        aria-controls="hub-sidebar"
        on:click={onToggleSidebar}
      >
        <span aria-hidden="true">&#9776;</span>
      </button>
    {/if}
    <a href={navHref('/')} class="flex min-w-0 items-center gap-2.5 font-semibold text-surface-50">
      <span class="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-gradient-brand text-white shadow-glow-sm">
        <span aria-hidden="true" class="text-base font-bold">⌬</span>
      </span>
      <span class="truncate text-lg text-gradient sm:text-xl">{title}</span>
    </a>
    <span
      class="hidden truncate rounded-full border border-surface-600/80 bg-surface-800/80 px-2.5 py-1 text-sm text-surface-200 sm:inline-block"
      title="Federation hub-id (per design decision #4)"
    >
      {hubId}
    </span>
  </div>

  <nav class="hidden items-center gap-1.5 md:flex" aria-label="Primary">
    {#key $page.url.pathname + ($page.route.id ?? '')}
    <a
      href={navHref('/projects')}
      class="topbar-nav-link"
      aria-current={isNavItemActive($page.url.pathname, '/projects', $page.route.id) ? 'page' : undefined}
    >
      Projects
    </a>
    <a
      href={navHref('/panels/hub-inbox')}
      class="topbar-nav-link"
      aria-current={isNavItemActive($page.url.pathname, '/panels/hub-inbox', $page.route.id)
        ? 'page'
        : undefined}
      aria-label={$hubInboxCount > 0 ? `Inbox, ${$hubInboxCount} unread` : 'Inbox'}
    >
      Inbox
      {#if $hubInboxCount > 0}
        <span class="ml-1.5 rounded-full bg-sky-600 px-2 py-0.5 text-sm font-semibold text-white" aria-hidden="true">
          {$hubInboxCount}
        </span>
      {/if}
    </a>
    <a
      href={navHref('/panels/decision-queue')}
      class="topbar-nav-link"
      aria-current={isNavItemActive($page.url.pathname, '/panels/decision-queue', $page.route.id)
        ? 'page'
        : undefined}
      aria-label={$pendingCount > 0 ? `Decisions, ${$pendingCount} pending` : 'Decisions'}
    >
      Decisions
      {#if $pendingCount > 0}
        <span class="ml-1.5 rounded-full bg-severity-warning px-2 py-0.5 text-sm font-semibold text-white" aria-hidden="true">
          {$pendingCount}
        </span>
      {/if}
    </a>
    <a
      href={navHref('/panels/role-chat')}
      class="topbar-nav-link"
      aria-current={isNavItemActive($page.url.pathname, '/panels/role-chat', $page.route.id)
        ? 'page'
        : undefined}
    >
      Talk to a Role
    </a>
    {/key}
  </nav>

  <div class="flex items-center gap-2 sm:gap-3">
    {#if $user}
      <span class="hidden truncate text-base text-surface-200 sm:inline">
        {$user.username}
      </span>
      <a href={navHref('/auth/logout')} class="btn-ghost text-base" data-testid="logout-link">Sign out</a>
    {:else}
      <a href={navHref('/auth/login')} class="btn-primary text-base" data-testid="login-link">Sign in</a>
    {/if}
  </div>
</header>
