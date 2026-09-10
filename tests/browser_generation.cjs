// Serve the fixture build on 8057 and tests.browser_generation_fixture on 8058.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const base = process.env.BROWSER_BASE_URL || 'http://127.0.0.1:8057', source = 'http://127.0.0.1:8058';
async function api(page, path, body) {
  return page.evaluate(async ({path, body}) => {
    const r = await Promise.race([fetch(path, body === undefined ? undefined : {method:'POST', body:JSON.stringify(body)}),
      new Promise((_, reject) => setTimeout(() => reject(Error('API timeout: ' + path)), 90000))]);
    return {status:r.status, data:await r.json()};
  }, {path, body});
}
async function good(page, path, body) {const r = await api(page, path, body); assert.equal(r.status, 200, JSON.stringify(r.data)); assert.ok(!r.data.error, JSON.stringify(r.data)); return r.data;}
async function mode(page, name) {assert.ok((await page.request.get(source + '/__fixture__/' + name)).ok());}
async function idle(page) {await page.waitForFunction(() => !document.querySelector('#browser-generation [data-check]').disabled);}
const pub = '/api/browser-generation', priv = '/api/browser-workspace';
(async () => {
  const spoofCode = `import tempfile,sqlite3,json\nfrom pathlib import Path\nfrom scripts.dosare import APPLICATION_ID\nwith tempfile.TemporaryDirectory() as d:\n p=Path(d)/'spoof.db'\n c=sqlite3.connect(p); c.execute(f'PRAGMA application_id={APPLICATION_ID}'); c.execute('PRAGMA user_version=9'); c.close(); print(json.dumps(list(p.read_bytes())))`;
  const spoof = JSON.parse(execFileSync('uv', ['run','python','-c',spoofCode], {encoding:'utf8'}));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
  try {for (const width of [1280, 390]) {
    const context = await browser.newContext({viewport:{width, height:1000}, serviceWorkers:'block'});
    const page = await context.newPage(), requests = [], errors = [];
    context.on('request', r => requests.push({url:r.url(), method:r.method(), range:r.headers().range}));
    page.on('pageerror', e => errors.push(e.message));
    await mode(page, 'unpublished'); await page.goto(base);
    let status = await good(page, pub);
    assert.equal(status.selected, null);
    assert.equal(requests.filter(r => r.url === source + '/channel.json').length, 0, 'No unsolicited public check');
    await page.locator('#browser-generation [data-check]').click(); await idle(page);
    const unavailable = await page.locator('#browser-generation [data-status]').innerText();
    assert.ok(/404|Failed to fetch/.test(unavailable), unavailable);
    for (const failure of ['hash','origin','duplicate','redirect','cors']) {
      await mode(page, failure);
      assert.equal((await api(page, pub, {action:'check'})).status, 500, failure);
      assert.equal((await good(page, pub)).selected, null);
    }
    await mode(page, 'a');
    await page.locator('#browser-generation [data-check]').click(); await idle(page);
    const id = 'a'.repeat(32);
    await good(page, '/api/dosare', {id, titlu:'Private survives source updates'});
    await good(page, '/api/dosare/metadate', {id, titlu:'Private latest', arhivat:false, revizie:0});
    const privateBefore = await good(page, priv);
    const exported = await good(page, priv, {action:'export'});
    await page.evaluate(() => {
      window.auditPosts = [];
      const original = window.fetch;
      window.fetch = (...args) => {if (args[1]?.method === 'POST') auditPosts.push(args[0]); return original(...args);};
      window.cancelSwitch = e => e.preventDefault(); addEventListener('beforeunload', cancelSwitch);
    });
    await page.locator('#browser-generation [data-select]').click(); await idle(page);
    assert.deepEqual(await page.evaluate(() => auditPosts), [], 'Guard blocks public prepare/select before POST');
    assert.equal((await good(page, pub)).selected, null);
    await page.click('#tab-matrice'); await page.locator('#dossier-library > summary').click();
    await page.locator('#browser-workspace > summary').click();
    await page.waitForFunction(() => !document.querySelector('#browser-workspace [data-restore]').disabled);
    await page.locator('#browser-workspace [data-restore]').click();
    await page.waitForFunction(() => document.querySelector('#browser-workspace [data-status]').textContent.includes('Pastrati'));
    await page.locator('#browser-workspace [data-import]').setInputFiles({name:'backup.db', mimeType:'application/vnd.sqlite3', buffer:Buffer.from(exported.bytes)});
    assert.deepEqual(await page.evaluate(() => auditPosts), [], 'Guard blocks private import/restore before POST');
    assert.deepEqual(await good(page, priv), privateBefore);
    await page.evaluate(() => removeEventListener('beforeunload', cancelSwitch));
    const invalid = await api(page, priv, {action:'import', bytes:spoof});
    assert.equal(invalid.status, 500); assert.deepEqual(await good(page, priv), privateBefore);
    // Check the real editor guard too, rather than relying only on a synthetic cancel event.
    await page.evaluate(() => {window.auditPosts = [];});
    await page.locator('#tab-lint').click(); await page.locator('#draft').fill('UNSAVED PUBLIC SWITCH GUARD');
    await page.locator('#browser-generation [data-select]').click(); await idle(page);
    assert.deepEqual(await page.evaluate(() => auditPosts), []);
    page.once('dialog', dialog => dialog.accept());
    await page.reload(); await good(page, pub);
    await page.locator('#browser-generation [data-check]').click(); await idle(page);
    await page.locator('#browser-generation [data-select]').click(); await idle(page);
    status = await good(page, pub); assert.equal(status.selected.release, '2026-09-10-a'); assert.equal(status.active, null);
    assert.equal(status.corpus_verified, false);
    await page.locator('#browser-generation [data-reload]').click();
    await page.waitForLoadState('domcontentloaded');
    status = await good(page, pub); assert.equal(status.active.release, '2026-09-10-a');
    assert.equal((await good(page, '/api/rezumat')).acte, 101);
    const searchStart = requests.length;
    const found = await good(page, '/api/cauta?q=achizitii&limita=2');
    assert.ok(found.results.length); assert.ok(found.results.every(r => r.titlu === 'GENERATION A'));
    assert.ok(!requests.slice(searchStart).some(r => /pagefind|\/idx\/|\/acte\//.test(r.url)), 'Selected search bypasses build/shard indexes');
    assert.deepEqual(await good(page, priv), privateBefore);
    console.log(`${width}: selected A, hash-verified reports, range-only SQLite search, private state preserved`);
    for (const failure of ['report','no-range']) {
      await mode(page, failure);
      const offer = await good(page, pub, {action:'check'});
      assert.equal((await api(page, pub, {action:'prepare', sha256:offer.offer.sha256})).status, 500, failure);
      assert.equal((await good(page, pub)).selected.release, '2026-09-10-a');
    }
    await mode(page, 'b');
    await page.locator('#browser-generation [data-check]').click(); await idle(page);
    await page.evaluate(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const result = await original(...args);
        if (args[0] === '/api/browser-generation' && args[1]?.method === 'POST' && JSON.parse(args[1].body).action === 'select') {
          window.fetch = original; throw Error('Simulated lost acknowledgement after commit');
        }
        return result;
      };
    });
    await page.locator('#browser-generation [data-select]').click(); await idle(page);
    assert.ok((await page.locator('#browser-generation [data-status]').innerText()).includes('nu a fost confirmata'));
    assert.ok((await page.locator('#browser-generation [data-active]').innerText()).includes('2026-09-10-b'), 'Unknown acknowledgement reconciles actual committed selection');
    status = await good(page, pub); assert.equal(status.selected.release, '2026-09-10-b'); assert.equal(status.previous.release, '2026-09-10-a');
    await page.locator('#browser-generation [data-reload]').click(); await page.waitForLoadState('domcontentloaded');
    assert.equal((await good(page, '/api/rezumat')).acte, 202);
    assert.equal((await good(page, '/api/cauta?q=achizitii&limita=1')).results[0].titlu, 'GENERATION B');
    await page.locator('#browser-generation').scrollIntoViewIfNeeded();
    await page.screenshot({path:`/tmp/browser-generation-${width}.png`});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await mode(page, 'minimal');
    status = await good(page, pub, {action:'check'});
    await good(page, pub, {action:'prepare', sha256:status.offer.sha256});
    await good(page, pub, {action:'select', sha256:status.offer.sha256, expected:status.selected.sha256});
    await page.reload(); status = await good(page, pub);
    assert.equal(status.active.release, '2026-09-10-minimal'); assert.ok(status.active.missing.includes('eu.db'));
    assert.equal((await good(page, '/api/cauta?q=achizitii&limita=1')).results[0].titlu, 'GENERATION MINIMAL');
    // A broken selected source must leave recovery controls available.
    await mode(page, 'corpus-failure'); await page.reload(); await good(page, pub);
    assert.equal((await api(page, '/api/rezumat')).status, 503);
    await page.locator('#browser-generation [data-clear]').click(); await idle(page);
    await page.locator('#browser-generation [data-reload]').click(); await page.waitForLoadState('domcontentloaded');
    assert.equal((await good(page, '/api/rezumat')).acte, 4);
    assert.deepEqual(await good(page, priv), privateBefore);
    const worker = page.workers()[0];
    await worker.evaluate(() => {
      globalThis.savedOpen = indexedDB.open.bind(indexedDB);
      indexedDB.open = (...args) => {
        const request = savedOpen(...args);
        if (args[0] === 'legislativ-public-generation-v1') queueMicrotask(() => request.onblocked?.(new Event('blocked')));
        return request;
      };
    });
    assert.equal((await api(page, pub)).status, 500, 'Blocked IDB open rejects instead of hanging');
    await worker.evaluate(() => {indexedDB.open = savedOpen;});
    assert.ok(!requests.some(r => r.method === 'POST'), 'No research or update network POST');
    assert.ok(!requests.some(r => r.url.includes('untrusted.invalid')));
    assert.ok(requests.filter(r => r.url.startsWith(source) && r.url.endsWith('/corpus.db') && r.method === 'GET').every(r => r.range), 'No full corpus downloads');
    assert.deepEqual(errors, []);
    console.log(`${width}: draft guards, spoof rejection, failed checks/preparation, generation replacement, optional UE, failed-boot recovery, no uploads passed`);
    await context.close();
  }} finally {await browser.close();}
})().catch(e => {console.error(e); process.exit(1);});
