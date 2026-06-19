import { test, expect } from '@playwright/test';

const PROJECT_ID =
  process.env.HUB_E2E_PROJECT_ID ?? '3f2a6e0e-15a3-44cd-9bc1-c06880199342';
const URL = `/spa/projects/${PROJECT_ID}`;

/**
 * Direct regression for SPA-HANG: page must become interactive and show
 * pipeline recovery actions without main-thread freeze.
 */
test.describe('project workspace hang (SPA-HANG)', () => {
  test('loads pipeline actions and stays responsive', async ({ page }) => {
    test.setTimeout(90_000);

    const apiLog: { path: string; ms: number; status: number }[] = [];
    page.on('response', (resp) => {
      const u = resp.url();
      if (!u.includes('/api/v2/')) return;
      const path = u.replace(/https?:\/\/[^/]+/, '');
      apiLog.push({ path, ms: 0, status: resp.status() });
    });

    const t0 = Date.now();
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 45_000 });

    await expect(page.getByTestId('workspace-boot')).toBeHidden({ timeout: 12_000 });
    await expect(page.getByTestId('project-pipeline')).toBeVisible({ timeout: 12_000 });

    const recoveryLocator = page.getByTestId('recovery-actions-ready');
    await expect(recoveryLocator).toBeVisible({ timeout: 20_000 });

    const bootMs = Date.now() - t0;

    // Main-thread responsiveness: evaluate must return within 2s for 5 consecutive checks
    for (let i = 0; i < 5; i++) {
      const probe = await Promise.race([
        page.evaluate(() => ({
          ready: !!document.querySelector('[data-testid="recovery-actions-ready"]'),
          loading: document.body.innerText.includes('Loading actions'),
          actions: document.querySelectorAll('[data-testid="recovery-actions-ready"] li').length,
        })),
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error('main thread frozen')), 2000)
        ),
      ]);
      expect(probe.ready).toBe(true);
      expect(probe.loading).toBe(false);
      expect(probe.actions).toBeGreaterThan(0);
      await page.waitForTimeout(300);
    }

    const totalMs = Date.now() - t0;
    console.log(
      JSON.stringify({
        bootMs,
        totalMs,
        apiCalls: apiLog.map((a) => `${a.status} ${a.path}`).slice(0, 15),
      })
    );

    expect(bootMs).toBeLessThan(15_000);
    expect(totalMs).toBeLessThan(25_000);
  });

  test('no freeze when terminal and SSE both allowed', async ({ page }) => {
    test.setTimeout(90_000);

    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await expect(page.getByTestId('recovery-actions-ready')).toBeVisible({ timeout: 25_000 });

    // Wait for deferred terminal + SSE (staged boot)
    await page.waitForTimeout(2500);

    for (let i = 0; i < 8; i++) {
      await page.evaluate(() => document.title, { timeout: 2000 });
      await page.waitForTimeout(200);
    }
  });
});
