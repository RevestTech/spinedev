<!--
  Spine Hub SPA — Topbar component (V3 Wave 3 part 2, Squad SPA1).

  Responsive: collapses to a hamburger + logo on viewports < md.
  Includes the federation hub-id chip (per #4 / #10) and the user menu.
-->
<script lang="ts">
  import { page } from '$app/stores';
  import { user } from '$lib/stores/user';
  import { pendingCount } from '$lib/stores/decisions';

  export let title: string = 'Spine Hub';
  export let onToggleSidebar: (() => void) | null = null;

  $: hubId = $user?.hub_id ?? 'hub-local';
</script>

<header
  class="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-surface-200 bg-white/95 px-3 backdrop-blur dark:border-surface-700 dark:bg-surface-800/95 xs:px-4 md:px-6"
>
  <div class="flex min-w-0 items-center gap-2 md:gap-3">
    {#if onToggleSidebar}
      <button
        type="button"
        class="btn-ghost px-2 md:hidden"
        aria-label="Toggle navigation"
        on:click={onToggleSidebar}
      >
        <span aria-hidden="true">&#9776;</span>
      </button>
    {/if}
    <a href="/" class="flex items-center gap-2 font-semibold text-surface-900 dark:text-surface-50">
      <span class="text-accent">{'/'}</span>
      <span class="truncate">{title}</span>
    </a>
    <span
      class="hidden truncate rounded-full bg-surface-100 px-2 py-0.5 text-xs text-surface-700 dark:bg-surface-700 dark:text-surface-100 sm:inline-block"
      title="Federation hub-id (per design decision #4)"
    >
      {hubId}
    </span>
  </div>

  <nav class="hidden items-center gap-1 md:flex" aria-label="Primary">
    <a
      href="/panels/decision-queue"
      class="rounded-md px-3 py-1.5 text-sm hover:bg-surface-100 dark:hover:bg-surface-700"
      class:bg-surface-100={$page.url.pathname.startsWith('/panels/decision-queue')}
    >
      Decisions
      {#if $pendingCount > 0}
        <span class="ml-1 rounded-full bg-severity-warning px-1.5 py-0.5 text-xs text-white">
          {$pendingCount}
        </span>
      {/if}
    </a>
    <a
      href="/panels/role-chat"
      class="rounded-md px-3 py-1.5 text-sm hover:bg-surface-100 dark:hover:bg-surface-700"
      class:bg-surface-100={$page.url.pathname.startsWith('/panels/role-chat')}
    >
      Talk to a Role
    </a>
  </nav>

  <div class="flex items-center gap-2">
    {#if $user}
      <span class="hidden truncate text-sm text-surface-700 dark:text-surface-200 sm:inline">
        {$user.username}
      </span>
      <a href="/auth/logout" class="btn-ghost text-sm" data-testid="logout-link">Sign out</a>
    {:else}
      <a href="/auth/login" class="btn-primary text-sm" data-testid="login-link">Sign in</a>
    {/if}
  </div>
</header>
