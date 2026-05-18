// Spine Hub SPA — Vite config (V3 Wave 3 part 2, Squad SPA1)
//
// Output target: dist/ — copied into the Hub container at
//   /app/static/spa/   (see hub/Dockerfile + shared/api/app.py StaticFiles)
//
// During dev: the SvelteKit dev server on :5173 proxies /api/* to the
// FastAPI app on :8088 so the OIDC cookie flow + Bearer translation work
// end-to-end without CORS friction.

import { sveltekit } from '@sveltejs/kit/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  // svelteTesting() adds the `browser` resolve condition + auto-cleanup so
  // Svelte's browser build (with onMount + DOM lifecycle) is used in vitest,
  // not the SSR build. Without it `onMount` never fires under jsdom and any
  // panel that loads data via onMount fails its tests. (Wave 3 part 2 fix.)
  plugins: [sveltekit(), svelteTesting()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Dev proxy: forward all /api/v2/* + auth flows to the FastAPI Hub.
      // Keeps the SPA on its own port without inheriting CORS edge cases.
      '/api': {
        target: process.env.HUB_API_URL || 'http://localhost:8088',
        changeOrigin: true,
        secure: false,
        // SSE endpoints — disable buffering so server-sent events stream.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Accept-Encoding', 'identity');
          });
        }
      }
    }
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    // Asset filename pattern matches what FastAPI StaticFiles serves
    // — Hub mounts /static/spa/ as the public prefix.
    assetsDir: '_app/immutable'
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/lib/test-setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,js}']
  }
});
