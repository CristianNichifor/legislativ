import { test, expect } from '@playwright/test';

async function lint(page, days = 30) {
  await page.locator('#tab-lint').click();
  await page.locator('#draft').fill(`In termen de ${days} de zile, Guvernul aproba normele metodologice.`);
  await page.locator('#go').click();
  await expect(page.locator('#lint-out')).toContainText('verificat în');
  await expect(page.locator('#lint-out')).toContainText(String(days));
  await expect(page.locator('#lint-out')).not.toContainText('Eroare:');
}

for (const path of ['/', '/nested/']) {
test(`real worker, Pagefind and warm offline at ${path}`, async ({ page, context, browserName }, info) => {
  const requests = [];
  const errors = [];
  const pagefindResponses = [];
  const fallbackWarnings = [];
  context.on('request', request => requests.push(request.url()));
  context.on('response', response => {
    if (response.url().includes('/pagefind/')) pagefindResponses.push({ url: response.url(), ok: response.ok() });
  });
  page.on('console', message => {
    if (message.text().includes('revin la motor')) fallbackWarnings.push(message.text());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    globalThis.baselineWorkers = [];
    globalThis.Worker = new Proxy(globalThis.Worker, {
      construct(Target, args) {
        const worker = Reflect.construct(Target, args);
        const record = { url: new URL(args[0], location.href).href, ready: false };
        baselineWorkers.push(record);
        worker.addEventListener('message', event => {
          if (event.data?.type === 'ready') record.ready = true;
        });
        return worker;
      },
    });
  });
  await page.goto(path);
  await expect(page.locator('#stat')).toContainText('4 acte');
  expect(await page.evaluate(() => baselineWorkers.some(worker => worker.ready && worker.url.endsWith('/worker.js')))).toBe(true);
  expect(await page.evaluate(() => typeof globalThis.loadPyodide)).toBe('undefined');
  await lint(page);
  await page.locator('#tab-cauta').click();
  await page.locator('#q').fill('achizitii publice');
  await page.locator('#q').press('Enter');
  await expect(page.locator('#cauta-out')).toContainText('98');
  expect(pagefindResponses.some(response => response.ok && response.url.includes('.pf_index'))).toBe(true);
  expect(pagefindResponses.some(response => response.ok && response.url.includes('.pf_fragment'))).toBe(true);
  expect(pagefindResponses.filter(response => !response.ok)).toEqual([]);
  expect(requests.filter(url => url.includes('/pagefind/pagefind/'))).toEqual([]);
  expect(fallbackWarnings).toEqual([]);
  if (browserName === 'chromium') {
    expect(requests.some(url => url.includes('/pyodide/v0.27.2/'))).toBe(true);
  }
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  const keys = await page.evaluate(async () => {
    const cachesFound = await caches.keys();
    const cache = await caches.open(cachesFound.find(name => name.startsWith('legislativ-')));
    return (await cache.keys()).map(request => request.url);
  });
  expect(keys.some(url => url.endsWith('/worker.js'))).toBe(true);
  expect(keys.some(url => url.includes('/pagefind/'))).toBe(true);
  expect(keys.some(url => url.includes('cdn.jsdelivr.net'))).toBe(false);
  expect(requests.filter(url => /\/api\/|\/corpus\.db/.test(url))).toEqual([]);
  await page.screenshot({ path: info.outputPath('static-search-online.png'), fullPage: true });
  await context.setOffline(true);
  await lint(page, 47);
  const offlineSearch = await page.evaluate(async () => {
    const response = await fetch('/api/cauta?q=achizitii%20publice');
    return response.json();
  });
  expect(offlineSearch.results.map(result => result.act_id)).toContain('lege-98-2016');
  await page.locator('#tab-cauta').click();
  await page.locator('#q').press('Enter');
  await expect(page.locator('#cauta-out')).toContainText('98');
  expect(errors).toEqual([]);
  expect(requests.filter(url => /\/api\/|\/corpus\.db/.test(url))).toEqual([]);
  expect(fallbackWarnings).toEqual([]);
  await page.screenshot({ path: info.outputPath('static-search-warm-offline.png'), fullPage: true });
  // Firefox/WebKit reject Playwright offline navigation before exposing the cached shell.
  // Keep its real same-tab checks above; do not claim restart coverage for that engine.
  if (browserName !== 'chromium') return;
  // A reload loses the live worker. The service worker does not own the CDN runtime.
  await context.route('https://cdn.jsdelivr.net/**', route => route.abort());
  await page.reload();
  await expect(page.locator('#draft')).toBeVisible();
  const unavailable = await page.evaluate(async () => {
    const response = await fetch('/api/rezumat');
    return { status: response.status, body: await response.json() };
  });
  expect(unavailable.status).toBe(503);
  expect(unavailable.body.error).toContain('motor indisponibil');
  await page.locator('#draft').fill('In termen de 63 de zile, Guvernul aproba normele.');
  await page.locator('#go').click();
  await expect(page.locator('#lint-out')).toContainText('motor indisponibil');
  await page.screenshot({ path: info.outputPath('static-shell-without-cdn-runtime.png'), fullPage: true });
});
}

test('cold offline context cannot load an uncached static shell', async ({ page, context }) => {
  await context.setOffline(true);
  await expect(page.goto('/')).rejects.toThrow();
  expect(await context.serviceWorkers()).toEqual([]);
});
