import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 13001,
    proxy: {
      '/api': 'http://localhost:13000',
      '/health': 'http://localhost:13000',
      '/ready': 'http://localhost:13000',
      '/ws': {
        target: 'ws://localhost:13000',
        ws: true,
      },
    },
  },
})
