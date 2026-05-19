<!--
  Spine Hub SPA — Logout page (V3 Wave 3 part 2, Squad SPA1).

  Calls POST /api/v2/auth/logout (per shared/api/middleware/oidc.py:logout).
  The backend invalidates the server-side session, clears the cookie, and
  redirects the user to Keycloak's end-session endpoint. Our role here is
  just to fire the POST and surface a brief confirmation while the
  redirect happens — the browser-level Location header does the real work.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { base } from '$app/paths';
  import { clearUser } from '$lib/stores/user';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';

  let error: string | null = null;

  onMount(() => {
    if (!browser) return;
    (async () => {
      try {
        // Use the native fetch so we follow the 302 response from the
        // backend; apiFetch would treat the redirect as a final JSON body.
        // credentials:'include' ships the cookie.
        await fetch('/api/v2/auth/logout', {
          method: 'POST',
          credentials: 'include',
          redirect: 'follow'
        });
        clearUser();
        // The backend already 302'd us to Keycloak end-session; if the
        // browser didn't honour the redirect (e.g. CORS edge case in
        // sub-path deploys), fall back to the SPA root.
        setTimeout(() => window.location.assign(base + '/'), 250);
      } catch (e) {
        error = (e as Error).message || 'logout failed';
      }
    })();
  });
</script>

<div class="flex flex-1 items-center justify-center px-4 py-10">
  <div class="panel-card w-full max-w-md text-center">
    {#if error}
      <ErrorBanner kind="error" message={error} />
      <a href="/" class="btn-primary mt-4 inline-flex">Return to Hub</a>
    {:else}
      <h1 class="text-lg font-semibold text-surface-900 dark:text-surface-50">Signing you out</h1>
      <div class="mt-4 flex justify-center"><LoadingSpinner label="Talking to Keycloak…" /></div>
    {/if}
  </div>
</div>
