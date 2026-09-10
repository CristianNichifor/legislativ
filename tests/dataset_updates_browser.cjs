// Offline UI fixture: no publication, external requests or real dataset changes.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'app/index.html'), 'utf8')
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replace('</body>', '<script src="dataset-updates.js"></script></body>');
const javascript = fs.readFileSync(path.join(root, 'app/dataset-updates.js'), 'utf8');
const base = 'http://127.0.0.1:8927';
const offer = {manifest: {release: '2026-09-10', files: [
  {name: 'corpus.db', bytes: 8388608, sha256: 'a'.repeat(64)},
]}, url: 'https://date.cnwebify.dev/2026-09-10/dataset-release.json', sha256: 'b'.repeat(64)};
const initial = () => ({mode: 'local', channel: 'https://date.cnwebify.dev/channel.json',
  active: null, offer: null, progress: {state: 'idle', bytes: 0, total: 0},
  private_data_uploaded: false});

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({viewport: {width, height: 1000}});
      let status = initial(), unsupported = false, unavailable = true;
      let posts = [], gets = 0, documents = 0;
      const unexpected = [], errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.origin !== base) { unexpected.push(url.href); return route.abort(); }
        if (url.pathname === '/') {
          documents++;
          return route.fulfill({contentType: 'text/html', body: html});
        }
        if (url.pathname === '/dataset-updates.js') {
          return route.fulfill({contentType: 'text/javascript', body: javascript});
        }
        if (url.pathname.startsWith('/fonts/')) {
          return route.fulfill({path: path.join(root, 'app', url.pathname.slice(1))});
        }
        if (url.pathname === '/api/date') {
          if (unsupported) return route.fulfill({status: 404, body: '{}'});
          if (request.method() === 'POST') {
            const body = request.postDataJSON(); posts.push(body);
            assert.deepEqual(Object.keys(body).sort(), body.action === 'check'
              ? ['action'] : ['action', 'sha256']);
            if (body.action === 'check' && unavailable) {
              return route.fulfill({status: 404, json: {error: 'Canalul nu este publicat.'}});
            }
            if (body.action === 'check') status = {...status, offer, progress: {state: 'checked'}};
            if (body.action === 'download') status.progress = {
              state: 'downloading', bytes: 1024, total: 8388608, file: 'corpus.db', file_bytes: 1024,
            };
            if (body.action === 'cancel') status.progress.state = 'cancelled';
            if (body.action === 'activate') {
              status.active = {release: '2026-09-10', generation: 'new', previous: 'old'};
              status.progress.state = 'active';
            }
            if (body.action === 'rollback') {
              status.active = {release: '2026-09-09', generation: 'old', previous: 'new'};
            }
          } else gets++;
          return route.fulfill({json: status});
        }
        unexpected.push(url.href);
        return route.abort();
      });
      await page.goto(base);
      const host = page.locator('#dataset-updates');
      const button = action => host.locator(`[data-action="${action}"]`);
      await host.waitFor({state: 'visible'});
      assert.match(await host.innerText(), /Nicio bază legislativă instalată/);
      await page.screenshot({path: `/tmp/dataset-updates-empty-${width}.png`});
      assert.equal(posts.length, 0);
      await page.waitForTimeout(2700);
      assert.ok(gets >= 2);
      assert.equal(posts.length, 0, 'Startup/poll must never check the remote channel');
      await button('check').click();
      await host.locator('[data-error]').filter({hasText: 'Canalul nu este publicat'}).waitFor();
      assert.equal(await host.isVisible(), true);
      assert.equal(await button('download').isVisible(), false);
      assert.equal(await button('activate').isVisible(), false);
      unavailable = false;
      await button('check').click();
      await button('download').waitFor({state: 'visible'});
      assert.match(await host.locator('[data-offer]').innerText(), /2026-09-10 · 8 MiB/);
      page.once('dialog', dialog => {
        assert.match(dialog.message(), /2026-09-10 \(8 MiB\)/);
        dialog.dismiss();
      });
      await button('download').click();
      assert.equal(posts.length, 2);
      page.once('dialog', dialog => dialog.accept());
      await button('download').click();
      await button('cancel').waitFor({state: 'visible'});
      assert.equal(posts.at(-1).sha256, offer.sha256);
      assert.equal(await host.locator('progress').getAttribute('max'), '8388608');
      await button('cancel').click();
      await button('download').waitFor({state: 'visible'});
      assert.equal(posts.at(-1).action, 'cancel');
      status.progress.state = 'verifying';
      await page.waitForFunction(() => document.querySelector('[data-status]').textContent.includes('integritatea'));
      assert.equal(await button('activate').isVisible(), false);
      status.progress.state = 'ready';
      await button('activate').waitFor({state: 'visible'});
      await page.evaluate(() => {
        window.unsaved = true;
        window.addEventListener('beforeunload', event => {
          if (window.unsaved) { event.preventDefault(); event.returnValue = ''; }
        });
        document.querySelector('#draft').value = 'Ciornă privată';
      });
      const before = posts.length;
      await button('activate').click();
      assert.equal(posts.length, before);
      assert.match(await host.locator('[data-error]').innerText(), /nesalvate/);
      await page.evaluate(() => { window.unsaved = false; });
      page.once('dialog', dialog => dialog.accept());
      await button('activate').click();
      await button('reload').waitFor({state: 'visible'});
      assert.equal(documents, 1, 'Activation must not reload automatically');
      assert.equal(await page.locator('#draft').inputValue(), 'Ciornă privată');
      await page.evaluate(() => { window.unsaved = true; });
      await button('reload').click();
      assert.equal(documents, 1);
      await button('rollback').click();
      assert.equal(posts.at(-1).action, 'activate');
      await page.evaluate(() => { window.unsaved = false; });
      page.once('dialog', dialog => dialog.accept());
      await button('rollback').click();
      await page.waitForFunction(() => document.querySelector('[data-active]').textContent.includes('2026-09-09'));
      status.progress = {state: 'error', error: 'Spațiu insuficient <img src=x>'};
      await host.locator('[data-error]').filter({hasText: 'Spațiu insuficient'}).waitFor();
      assert.match(await host.innerText(), /Versiunea instalată este păstrată/);
      assert.equal(await host.locator('img').count(), 0);
      assert.equal(await page.evaluate(() => {
        const host = document.querySelector('#dataset-updates');
        return host.scrollWidth > host.clientWidth;
      }), false, 'Update panel must not overflow');
      for (const element of await host.locator('button:visible').all()) {
        const box = await element.boundingBox();
        assert.ok(box.x >= 0 && box.x + box.width <= width);
      }
      await page.screenshot({path: `/tmp/dataset-updates-${width}.png`});
      assert.deepEqual(errors, []);
      assert.deepEqual(unexpected, []);
      status.mode = 'browser';
      await page.reload();
      await page.waitForTimeout(100);
      assert.equal(await host.isVisible(), false);
      unsupported = true;
      await page.reload();
      await page.waitForTimeout(100);
      assert.equal(await host.isVisible(), false);
      await page.close();
      console.log(`${width}: explicit actions, hash pinning, progress, draft guards, rollback, errors, unsupported endpoint passed`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
