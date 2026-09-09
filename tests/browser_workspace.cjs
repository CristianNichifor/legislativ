// Build: uv run python -m scripts.construieste_web --sursa fixturi
// Serve web/ on BROWSER_BASE_URL; uses real Pyodide, SQLite and IndexedDB.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const base = process.env.BROWSER_BASE_URL || 'http://127.0.0.1:8057';
async function api(page, path, body) {
  return page.evaluate(async ({path, body}) => {
    const r = await Promise.race([
      fetch(path, body === undefined ? undefined : {method: 'POST', body: JSON.stringify(body)}),
      new Promise((_, reject) => setTimeout(() => reject(new Error('Browser API timed out: ' + path)), 90000)),
    ]);
    return {status: r.status, data: await r.json()};
  }, {path, body});
}
async function good(page, path, body) {
  const out = await api(page, path, body);
  assert.equal(out.status, 200, JSON.stringify(out.data));
  assert.ok(!out.data.error, JSON.stringify(out.data)); return out.data;
}
(async () => {
  const seed = JSON.parse(execFileSync('uv', ['run', 'python', '-m', 'tests.browser_workspace_fixture'], {encoding: 'utf8', maxBuffer: 16 * 1024 * 1024}));
  const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
  try { for (const width of [1280, 390]) {
    const context = await browser.newContext({viewport: {width, height: 1000}, serviceWorkers: 'block'});
    const page = await context.newPage(), errors = [], uploads = [];
    page.on('pageerror', e => errors.push(e.message));
    context.on('request', r => { if (r.method() !== 'GET' && r.method() !== 'HEAD') uploads.push(r.url()); });
    await page.goto(base);
    const id = 'a'.repeat(32);
    await good(page, '/api/dosare', {id, titlu: 'Browser retained research'});
    console.log(`${width}: Pyodide boot and first durable write`);
    await page.reload();
    assert.equal((await good(page, '/api/dosare?id=' + id)).titlu, 'Browser retained research');
    const second = await context.newPage(); await second.goto(base);
    const contenders = await Promise.all([page, second].map((p, i) => api(p, '/api/dosare/metadate', {
      id, titlu: 'Concurrent ' + i, arhivat: false, revizie: 0,
    })));
    assert.equal(contenders.filter(r => r.status === 200).length, 1, 'Exactly one stale-revision contender commits');
    let meta = await good(page, '/api/dosare/metadate?id=' + id);
    for (let n = 0; n < 4; n++) {
      meta = await good(page, '/api/dosare/metadate', {id, titlu: 'Retained ' + n, arhivat: false, revizie: meta.revizie});
    }
    const before = await good(page, '/api/browser-workspace');
    assert.equal(before.backups.length, 3);
    // Inject a real IDB transaction abort in the running worker, after SQLite commits.
    const worker = page.workers()[0];
    await worker.evaluate(() => {
      globalThis.originalTransaction = IDBDatabase.prototype.transaction;
      IDBDatabase.prototype.transaction = function (...args) {
        const tx = originalTransaction.apply(this, args);
        if (args[1] === 'readwrite') queueMicrotask(() => tx.abort());
        return tx;
      };
    });
    const failed = await api(page, '/api/dosare/metadate', {id, titlu: 'MUST NOT SURVIVE', arhivat: false, revizie: meta.revizie});
    assert.equal(failed.status, 500);
    assert.deepEqual(await good(page, '/api/browser-workspace'), before, 'Failed write cannot rotate backups');
    assert.equal((await good(page, '/api/dosare?id=' + id)).titlu, meta.titlu, 'Failed write rolled back in worker');
    await page.reload();
    assert.equal((await good(page, '/api/dosare?id=' + id)).titlu, meta.titlu);
    const exported = await good(page, '/api/browser-workspace', {action: 'export'});
    assert.equal(Buffer.from(exported.bytes).subarray(0, 15).toString(), 'SQLite format 3');
    const invalid = await api(page, '/api/browser-workspace', {action: 'import', bytes: [1, 2, 3]});
    assert.equal(invalid.status, 500);
    assert.deepEqual(await good(page, '/api/browser-workspace'), before);
    await good(page, '/api/browser-workspace', {action: 'restore', backup: 0});
    assert.equal((await good(page, '/api/dosare?id=' + id)).titlu, 'Retained 2');
    await good(page, '/api/browser-workspace', {action: 'import', bytes: exported.bytes});
    await page.reload();
    assert.equal((await good(page, '/api/dosare?id=' + id)).titlu, meta.titlu);
    // Restore a native schema 9 dossier, then exercise shared services in real Pyodide.
    await good(page, '/api/browser-workspace', {action: 'import', bytes: seed.bytes});
    const identity = {dosar_id: seed.id, rulare_id: seed.run, constatare_id: seed.finding};
    const query = new URLSearchParams({id: seed.id, rulare_id: seed.run, constatare_id: seed.finding, revizie: '1'});
    const linkHistory = await good(page, '/api/dosare/propuneri/legaturi-ue?' + query);
    assert.equal(linkHistory.selectata.id, seed.link, 'Retained EU evidence works without source acquisition');
    const analysis = await good(page, '/api/dosare/propuneri/analize', {...identity, id: 'e'.repeat(32), revizie: 1});
    assert.ok(analysis.id);
    const review = await good(page, '/api/dosare/revizuiri', {...identity, id: 'f'.repeat(32), revizie: 0, stare: 'needs_evidence', evaluator: 'Browser reviewer', motiv: 'Retained review'});
    assert.ok(review);
    const fields = ['aplicabil_de_la', 'aplicabil_pana_la', 'teritoriu', 'destinatari', 'exceptii', 'tranzitorii', 'clasificare'];
    const contextFields = Object.fromEntries(fields.map(k => [k, {valoare: '', citare: ''}]));
    contextFields.teritoriu = {valoare: 'Romania', citare: 'Fixture art1'};
    await good(page, '/api/dosare/context', {...identity, id: '1'.repeat(32), tinta: 'a', revizie: 0, evaluator: 'Browser reviewer', motiv: 'Declared context', context: contextFields});
    await good(page, '/api/dosare/propuneri', {...identity, id: '2'.repeat(32), revizie: 1, titlu: 'Browser revision', text: 'Text pastrat in browser.', motiv: 'Revision fixture'});
    await page.reload();
    const revision2 = new URLSearchParams(query); revision2.set('revizie', '2');
    assert.equal((await good(page, '/api/dosare/propuneri?' + revision2)).propunere.titlu, 'Browser revision');
    assert.equal((await good(page, '/api/dosare/propuneri/analize?' + query)).selectata.id, analysis.id);
    assert.equal((await good(page, '/api/dosare/propuneri/legaturi-ue?' + query)).selectata.id, seed.link);
    await page.click('#tab-matrice');
    await page.locator('#dossier-library > summary').click();
    await page.locator('#browser-workspace > summary').click();
    await page.locator('#browser-workspace').scrollIntoViewIfNeeded();
    await page.screenshot({path: `/tmp/browser-workspace-${width}.png`});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    assert.deepEqual(uploads, [], 'Research must not produce network writes');
    console.log(`${width}: reload, concurrent conflict, failed durable write rollback, backup retention, export/import/restore, UI and no uploads passed`);
    await context.close();
  }} finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
