import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 1,
  use: {
    baseURL: process.env.HUB_BASE ?? 'http://localhost:8090',
    trace: 'off',
  },
});
