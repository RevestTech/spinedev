// Spine Hub SPA — Vite config (V3 Wave 3 part 2, Squad SPA1)
//
// Output target: dist/ — copied into the Hub container at
//   /app/static/spa/   (see hub/Dockerfile + shared/api/app.py StaticFiles)
//
// During dev: the SvelteKit dev server on :5173 proxies /api/* to the
// FastAPI app on :8088 so the OIDC cookie flow + Bearer translation work
// end-to-end without CORS friction.

import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
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
