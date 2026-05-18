// Spine Hub SPA — SvelteKit config (V3 Wave 3 part 2, Squad SPA1)
//
// adapter-static = build pure-static output the Hub container's FastAPI
// StaticFiles mount can serve under /static/spa/. We use SPA fallback
// (index.html) so client-side routing works for /spa/* deep links —
// FastAPI's catch-all /spa/{path:path} route serves the same file.
//
// Per design decision #3, Hub is a containerized product; the SPA is one
// of the artifacts the Hub serves alongside its REST + SSE API.

import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      // Pure SPA: emit index.html fallback so any /spa/<deep-link> resolves.
      pages: 'dist',
      assets: 'dist',
      fallback: 'index.html',
      precompress: false,
      strict: false
    }),
    // Build output is mounted at /static/spa/ by FastAPI; configure base
    // path so all asset URLs resolve correctly when served from that prefix.
    paths: {
      base: process.env.SPA_BASE_PATH || ''
    },
    // Allow the SPA to be served from /spa/* as a sub-path. The /spa/ prefix
    // is the catch-all route shared/api/app.py mounts.
    appDir: '_app',
    alias: {
      $lib: 'src/lib',
      '$lib/*': 'src/lib/*'
    }
  }
};

export default config;
