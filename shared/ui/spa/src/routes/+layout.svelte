<!--
  Spine Hub SPA — root layout (V3 Wave 3 part 2, Squad SPA1).

  Auth-guarded shell: Topbar + Sidebar + slot for the active panel + a
  status footer that reflects the live SSE-connected state of the
  decision queue. Stylesheet imported once here so every page picks it up.
-->
<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Topbar from '$lib/components/Topbar.svelte';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { toasts } from '$lib/stores/toasts';
  import { decisions } from '$lib/stores/decisions';
  import type { LayoutData } from './$types';

  export let data: LayoutData;

  let sidebarOpen = false;

  // SSE: open once at the layout level so multiple panels share the stream.
  onMount(() => {
    if (data.user) {
      decisions.connect();
    }
    return () => decisions.disconnect();
  });

  $: liveConnected = $decisions.liveConnected;
  $: isAuthRoute = $page.url.pathname.startsWith('/auth/');
</script>

<div class="flex min-h-screen flex-col">
  {#if !isAuthRoute}
    <Topbar title="Spine Hub" onToggleSidebar={() => (sidebarOpen = !sidebarOpen)} />
    <div class="flex flex-1 md:flex-row">
      <Sidebar open={sidebarOpen} onClose={() => (sidebarOpen = false)} />
      <main
        id="main-content"
        class="min-w-0 flex-1 px-3 py-4 xs:px-4 sm:py-6 md:px-6 lg:px-8"
        tabindex="-1"
      >
        <slot />
      </main>
    </div>
    <footer
      class="mt-auto flex flex-col items-center justify-between gap-1 border-t border-surface-200 bg-white px-3 py-2 text-xs text-surface-700 dark:border-surface-700 dark:bg-surface-800 dark:text-surface-200 sm:flex-row sm:px-6"
    >
      <span>Spine Hub v0.3 — Wave 3 SPA</span>
      <span
        class="inline-flex items-center gap-1"
        title="Decision-queue SSE connection (per design decision #5 active push)"
      >
        <span
          class="inline-block h-2 w-2 rounded-full"
          class:bg-green-500={liveConnected}
          class:bg-surface-200={!liveConnected}
          aria-hidden="true"
        ></span>
        {liveConnected ? 'Live' : 'Offline'}
      </span>
    </footer>
  {:else}
    <main class="flex flex-1 flex-col">
      <slot />
    </main>
  {/if}

  <!-- Toast island -->
  <div
    class="pointer-events-none fixed inset-x-0 bottom-3 z-50 flex flex-col items-center gap-2 px-3 sm:bottom-6"
    aria-live="polite"
  >
    {#each $toasts as toast (toast.id)}
      <div class="pointer-events-auto w-full max-w-md">
        <ErrorBanner
          kind={toast.kind}
          message={toast.message}
          onDismiss={() => toasts.dismiss(toast.id)}
        />
      </div>
    {/each}
  </div>
</div>
