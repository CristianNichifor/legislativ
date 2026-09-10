// Run against a built fixture app; validates recovery guards with real Pyodide/IndexedDB.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const base = process.env.BROWSER_BASE_URL || 'http://127.0.0.1:8057';
async function api(page, path, body) {
  return page.evaluate(async ({path, body}) => {
    const r = await fetch(path, body ? {method:'POST', body:JSON.stringify(body)} : undefined);
    return {status:r.status, data:await r.json()};
  }, {path, body});
}
(async () => {
  const code = `import tempfile,sqlite3,json\nfrom pathlib import Path\nfrom scripts.dosare import APPLICATION_ID\nwith tempfile.TemporaryDirectory() as d:\n p=Path(d)/'spoof.db'\n c=sqlite3.connect(p); c.execute(f'PRAGMA application_id={APPLICATION_ID}'); c.execute('PRAGMA user_version=9'); c.close(); print(json.dumps(list(p.read_bytes())))`;
  const spoof = JSON.parse(execFileSync('uv', ['run','python','-c',code], {encoding:'utf8'}));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
  try {for (const width of [1280, 390]) {
    const context = await browser.newContext({viewport:{width,height:1000}, serviceWorkers:'block'});
    const page = await context.newPage(); await page.goto(base);
    const id = 'a'.repeat(32), endpoint = '/api/browser-workspace';
    assert.equal((await api(page, '/api/dosare', {id,titlu:'Guarded workspace'})).status, 200);
    assert.equal((await api(page, '/api/dosare/metadate', {id,titlu:'Latest',arhivat:false,revizie:0})).status, 200);
    const before = (await api(page, endpoint)).data;
    const exported = (await api(page, endpoint, {action:'export'})).data;
    await page.click('#tab-matrice'); await page.locator('#dossier-library > summary').click();
    await page.locator('#browser-workspace > summary').click();
    await page.waitForFunction(() => !document.querySelector('#browser-workspace [data-restore]').disabled);
    await page.evaluate(() => {
      window.posts = []; const original = fetch;
      window.fetch = (...args) => {if(args[1]?.method === 'POST') posts.push(args[0]); return original(...args);};
      window.cancelRecovery = e => e.preventDefault(); addEventListener('beforeunload',cancelRecovery);
    });
    await page.locator('#browser-workspace [data-restore]').click();
    await page.waitForFunction(() => document.querySelector('#browser-workspace [data-status]').textContent.includes('Pastrati'));
    await page.locator('#browser-workspace [data-import]').setInputFiles({name:'backup.db',mimeType:'application/vnd.sqlite3',buffer:Buffer.from(exported.bytes)});
    assert.deepEqual(await page.evaluate(() => posts), []);
    assert.deepEqual((await api(page, endpoint)).data, before);
    await page.evaluate(() => removeEventListener('beforeunload', cancelRecovery));
    const rejected = await api(page, endpoint, {action:'import',bytes:spoof});
    assert.equal(rejected.status, 500);
    assert.deepEqual((await api(page, endpoint)).data, before);
    assert.equal((await api(page, '/api/dosare?id='+id)).data.titlu, 'Latest');
    console.log(`${width}: cancelled import/restore send no POST and preserve hash/backups; spoofed schema9 rejected before replacement`);
    await context.close();
  }} finally {await browser.close();}
})().catch(e => {console.error(e);process.exit(1);});
