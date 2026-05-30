import { test, expect } from '@playwright/test';

const BOOGER_ID = 'c94d5f8c-5c7a-40a1-9da9-e25fcca63c88';
const HUB = process.env.HUB_BASE ?? 'http://localhost:8090';

test('dashboard → Booger workspace shows recovery actions without hanging', async ({ page }) => {
  test.setTimeout(60_000);

  await page.goto(`${HUB}/spa/`, { waitUntil: 'domcontentloaded' });

  const boogerLink = page.locator(`a[href*="/projects/${BOOGER_ID}"]`).first();
  await expect(boogerLink).toBeVisible({ timeout: 20_000 });
  await boogerLink.click();

  await page.waitForURL(`**/projects/${BOOGER_ID}**`, { timeout: 15_000 });

  // Wait until pipeline controls render (boot gate cleared + recovery in store).
  await expect(page.getByTestId('recovery-actions-ready')).toBeVisible({ timeout: 45_000 });
  await expect(page.getByTestId('workspace-boot')).toBeHidden({ timeout: 5_000 });
  await expect(page.getByText('Loading actions')).toBeHidden({ timeout: 5_000 });
});
