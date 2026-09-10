// The fixture serves the real app/API and verified SQLite releases in a temporary data home.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const python = process.env.PYTHON || path.join(root, '.venv/bin/python');

async function fixture() {
  const child = spawn(python, ['-u', 'tests/local_updates_fixture.py'], {cwd: root});
  let log = '';
  child.stderr.on('data', chunk => {log += chunk;});
  const url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture timeout: ' + log)), 15000);
    child.stdout.on('data', chunk => {
      const found = String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);
      if (found) {clearTimeout(timer); resolve(found[0]);}
    });
    child.on('exit', code => {clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${log}`));});
  });
  return {child, url};
}

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    for (const width of [1280, 390]) {
      const {child, url} = await fixture();
      const context = await browser.newContext({viewport: {width, height: 1000}});
      try {
        const page = await context.newPage(), errors = [], external = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          if (new URL(route.request().url()).origin !== url) {
            external.push(route.request().url()); return route.abort();
          }
          return route.continue();
        });
        page.on('dialog', dialog => dialog.accept());
        await page.goto(url);
        const host = page.locator('#dataset-updates');
        const button = action => host.locator(`[data-action="${action}"]`);
        await host.waitFor({state: 'visible'});
        assert.match(await host.innerText(), /Nicio bază legislativă instalată/);
        const dossier = await page.evaluate(async () => {
          const response = await fetch('/api/dosare', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: crypto.randomUUID().replaceAll('-', ''), titlu: 'Cercetare privata', intrebare: 'Test', domeniu: 'general'})});
          if (!response.ok) throw new Error(await response.text());
          return response.json();
        });
        await page.screenshot({path: `/tmp/local-updates-empty-${width}.png`});
        for (const version of ['2026-09-10', '2026-09-11']) {
          await button('check').click();
          await button('download').waitFor({state: 'visible'});
          assert.match(await host.locator('[data-offer]').innerText(), new RegExp(version));
          await button('download').click();
          await button('activate').waitFor({state: 'visible', timeout: 30000});
          await button('activate').click();
          await page.waitForFunction(v => document.querySelector('#dataset-updates [data-active]').textContent.includes(v), version);
        }
        await button('rollback').click();
        await page.waitForFunction(() => document.querySelector('#dataset-updates [data-active]').textContent.includes('2026-09-10'));
        const kept = await page.evaluate(async () => (await fetch('/api/dosare')).json());
        assert.ok(JSON.stringify(kept).includes('Cercetare privata'), JSON.stringify({dossier, kept}));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({path: `/tmp/local-updates-active-${width}.png`});
        assert.deepEqual(errors, []);
        assert.deepEqual(external, []);
        console.log(`Real local update UI ${width}: install, update, rollback, private dossier retained`);
      } finally {
        await context.close();
        const exited = once(child, 'exit'); child.kill('SIGTERM'); await exited;
      }
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
