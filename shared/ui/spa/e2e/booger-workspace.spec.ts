import { test, expect } from '@playwright/test';

const HUB = process.env.HUB_BASE ?? 'http://localhost:8090';
const PROJECT_ID =
  process.env.HUB_E2E_PROJECT_ID ?? '3f2a6e0e-15a3-44cd-9bc1-c06880199342';

test('project workspace opens without full-page boot hang', async ({ page }) => {
  test.setTimeout(60_000);

  await page.goto(`${HUB}/spa/projects/${PROJECT_ID}`, { waitUntil: 'domcontentloaded' });

  await expect(page.getByTestId('workspace-boot')).toBeHidden({ timeout: 8_000 });
  await expect(page.getByTestId('project-pipeline')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('recovery-actions-ready')).toBeVisible({ timeout: 45_000 });
});
