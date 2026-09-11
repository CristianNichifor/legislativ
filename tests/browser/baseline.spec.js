import { test, expect } from '@playwright/test';

for (const width of [390, 1440]) {
  test(`local corpus search, lint and theme persistence at ${width}px`, async ({ page, context }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    const external = [];
    const requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => requests.push(request.url()));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.hostname !== '127.0.0.1') {
        external.push(url.origin);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto('/');
    await expect(page.locator('#q')).toHaveClass(/civic-input/);
    await expect(page.locator('#f-tip')).toHaveClass(/civic-select/);
    await expect(page.locator('#f-an-min')).toHaveClass(/civic-select/);
    await expect(page.locator('#f-an-max')).toHaveClass(/civic-select/);
    expect(requests.some(url => url.endsWith('/vendor/civic-ui/styles.css'))).toBe(true);
    await page.locator('#tab-matrice').click();
    await page.locator('#dossier-library > summary').click();
    await expect(page.locator('#dossier-local')).toBeVisible();
    await page.locator('#dossier-create').evaluate(form => form.closest('details').open = true);
    await page.locator('#dossier-create input[name="titlu"]').fill(`Fișă act ${width}`);
    await page.locator('#dossier-create textarea[name="intrebare"]').fill('Ce afectează legea?');
    await page.locator('#dossier-create input[name="domeniu"]').fill('test');
    await page.locator('#dossier-create button[type="submit"]').click();
    await expect(page.locator('#dossier-status')).toContainText('Dosar ales');
    await page.locator('#tab-cauta').click();
    await expect(page.locator('#pane-cauta')).toBeVisible();
    await page.locator('#q').fill('registrul demonstrativ');
    await page.locator('#q').press('Enter');
    await expect(page.locator('#cauta-out')).toContainText('999999');
    const projectButton = page.locator('#cauta-out .impact-proiecte').first();
    await expect(projectButton).toBeVisible();
    await projectButton.click();
    await expect(page.locator('#cauta-out .project-impact').first()).toContainText('plx-999999-2026');
    await expect(page.locator('#cauta-out .project-impact').first()).toContainText('raport depus');
    await expect(page.locator('#cauta-out .project-impact').first()).toContainText('Ținte în act');
    await page.locator('#cauta-out .impact-compare').first().click();
    await expect(page.locator('#cauta-out .matrix-draft-form').first()).toContainText('Compară două proiecte');
    await page.locator('#cauta-out .law-workbench-btn').first().click();
    await expect(page.locator('#cauta-out .law-workbench').first()).toContainText('Fișă de lucru');
    await expect(page.locator('#cauta-out .law-workbench').first()).toContainText('Următorii pași');
    await expect(page.locator('#cauta-out .law-workbench').first()).toContainText('Inițiative pendinte');
    await page.locator('#cauta-out .law-workbench .dossier-actions button').first().click();
    await expect(page.locator('#dossier-saved')).toContainText('fisa-act-v1');
    await expect(page.locator('#dossier-saved')).toContainText('Fișă de lucru');
    await page.locator('#cauta-out .impact-watch').first().click();
    await expect(page.locator('#cauta-out .impact-watch').first()).toContainText('supravegheat');
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
