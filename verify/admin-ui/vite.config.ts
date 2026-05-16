import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:13000',
        changeOrigin: true,
        rewrite: (path) => path,
      }
    }
  },
  build: {
    // nginx compose mounts ./admin/dist — keep legacy path stable
    outDir: '../admin/dist',
    emptyOutDir: true,
    sourcemap: true,
    minify: 'esbuild',
  }
})
