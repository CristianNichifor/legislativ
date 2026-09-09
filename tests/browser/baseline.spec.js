import { test, expect } from '@playwright/test';

for (const width of [390, 1440]) {
  test(`local corpus search, lint and theme persistence at ${width}px`, async ({ page, context }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    const external = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.hostname !== '127.0.0.1') {
        external.push(url.origin);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto('/');
    await page.locator('#tab-cauta').click();
    await expect(page.locator('#pane-cauta')).toBeVisible();
    await page.locator('#q').fill('registrul demonstrativ');
    await page.locator('#q').press('Enter');
    await expect(page.locator('#cauta-out')).toContainText('999999');
    await page.screenshot({ path: info.outputPath(`search-${width}.png`), fullPage: true });
    await page.locator('#tab-lint').click();
    await page.locator('#draft').fill('In termen de 30 de zile, Guvernul aproba normele metodologice.');
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/lint'));
    await page.locator('#go').click();
    expect((await responsePromise).ok()).toBe(true);
    await expect(page.locator('#lint-out')).toContainText('verificat în');
    await expect(page.locator('#lint-out')).not.toContainText('Eroare:');
    await page.screenshot({ path: info.outputPath(`lint-${width}.png`), fullPage: true });
    await page.locator('#tema-btn').click();
    const theme = await page.evaluate(() => localStorage.getItem('tema'));
    expect(['light', 'dark']).toContain(theme);
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await page.reload();
    expect(await page.evaluate(() => localStorage.getItem('tema'))).toBe(theme);
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    expect(external).toEqual([]);
    expect(errors).toEqual([]);
    await page.screenshot({ path: info.outputPath(`local-${width}.png`), fullPage: true });
  });
}
