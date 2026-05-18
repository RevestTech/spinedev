<!--
  Spine Hub SPA — Login page (V3 Wave 3 part 2, Squad SPA1).

  Per design decision #25: Spine never handles passwords / MFA / social
  / SAML — everything delegates to Keycloak. This page is the entry-point
  the SPA shows to anonymous visitors and offers a single button that
  navigates the browser to /api/v2/auth/login. The backend (see
  shared/api/middleware/oidc.py:login) constructs the Keycloak auth-code
  URL (with state + nonce) and 302s the browser there. Keycloak handles
  identity, then redirects back to /api/v2/auth/callback which sets the
  signed `spine_sid` cookie and 302s back to /.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';

  let autoStartedAt: number | null = null;

  function startLogin() {
    if (!browser) return;
    autoStartedAt = Date.now();
    window.location.assign('/api/v2/auth/login');
  }

  // If the user lands here as a hard 401 redirect (browser kicked them
  // out of a protected route), auto-start the flow after a short pause
  // so they perceive a single hop, not two clicks.
  onMount(() => {
    if (!browser) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('auto') === '1') {
      const t = setTimeout(startLogin, 250);
      return () => clearTimeout(t);
    }
  });
</script>

<div class="flex flex-1 items-center justify-center px-4 py-10">
  <div class="panel-card w-full max-w-md text-center">
    <h1 class="text-xl font-semibold text-surface-900 dark:text-surface-50">Sign in to Spine Hub</h1>
    <p class="mt-2 text-sm text-surface-700 dark:text-surface-200">
      Authentication is handled by your organisation's Keycloak realm.
      You will be redirected to continue.
    </p>
    <button
      type="button"
      class="btn-primary mt-6 w-full"
      on:click={startLogin}
      data-testid="login-button"
    >
      Continue to Keycloak →
    </button>
    {#if autoStartedAt}
      <p class="mt-3 text-xs text-surface-700/70 dark:text-surface-200/70">Redirecting…</p>
    {/if}
    <p class="mt-6 text-xs text-surface-700/70 dark:text-surface-200/70">
      By signing in you agree to your organisation's acceptable use policy.
    </p>
  </div>
</div>
