<!--
  Spine Hub SPA — OIDC callback landing (V3 Wave 3 part 2, Squad SPA1).

  The Keycloak auth-code flow returns the browser to
  /api/v2/auth/callback (backend route in shared/api/middleware/oidc.py).
  That backend route exchanges the code for tokens, signs a session
  cookie, and 302s to /. So the user almost never sees this page —
  it exists for two edge cases:

    1. The deployment shape puts the SPA on a different origin than the
       API (uncommon; only "Hub-on-CDN" shape per docs/DEPLOYMENT_SHAPES.md).
       In that case the callback may land here client-side and we forward
       the query string to the API explicitly.
    2. The /auth/callback URL is registered as a fallback in Keycloak
       (per keycloak/realm-config/spine-hub-client.json's redirectUris)
       so federated IdPs that strip query-prefixes still resolve.

  Behaviour: if `?code` is present, POST it to the API; otherwise display
  an error and link back to /auth/login so the user can retry.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';

  let error: string | null = null;
  let stage: 'forwarding' | 'done' = 'forwarding';

  onMount(() => {
    if (!browser) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    if (!code) {
      error = 'OIDC callback missing `code` parameter. Please retry sign-in.';
      stage = 'done';
      return;
    }
    // Hand off to the backend endpoint that owns token exchange + cookie set.
    // Use a hard navigation so the Set-Cookie reaches the browser
    // synchronously and subsequent SPA fetches carry it.
    const forward = `/api/v2/auth/callback?code=${encodeURIComponent(code)}${
      state ? `&state=${encodeURIComponent(state)}` : ''
    }`;
    window.location.assign(forward);
  });
</script>

<div class="flex flex-1 items-center justify-center px-4 py-10">
  <div class="panel-card w-full max-w-md text-center">
    {#if error}
      <ErrorBanner kind="error" message={error} />
      <a href="/auth/login" class="btn-primary mt-4 inline-flex">Try sign-in again</a>
    {:else if stage === 'forwarding'}
      <h1 class="text-lg font-semibold text-surface-900 dark:text-surface-50">Finalising sign-in</h1>
      <div class="mt-4 flex justify-center">
        <LoadingSpinner label="Exchanging code with Keycloak…" />
      </div>
    {/if}
  </div>
</div>
