// Real Pyodide regression for historical pinned releases with missing optional payloads.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http = require('node:http'), fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), output = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-legacy-'));
let missingCorpus = false, missingCatalog = false;
const requests = [];
function send(req, res, file, remote) {
  if (!fs.existsSync(file)) {res.writeHead(404); res.end(); return;}
  const raw = fs.readFileSync(file), range = req.headers.range?.match(/^bytes=(\d+)-(\d+)$/);
  const start = range ? Number(range[1]) : 0, end = range ? Math.min(Number(range[2]), raw.length - 1) : raw.length - 1;
  const headers = {'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes', 'Access-Control-Allow-Origin': '*',
    'Access-Control-Expose-Headers': 'Accept-Ranges, Content-Length, Content-Range'};
  if (range) headers['Content-Range'] = `bytes ${start}-${end}/${raw.length}`;
  if (file.endsWith('.js')) headers['Content-Type'] = 'application/javascript';
  if (file.endsWith('.html')) headers['Content-Type'] = 'text/html';
  res.writeHead(range ? 206 : 200, headers); res.end(req.method === 'HEAD' ? undefined : raw.subarray(start, end + 1));
}
const remote = http.createServer((req, res) => {
  requests.push(req.url);
  const name = req.url.split('/').pop();
  if ((name === 'corpus.db' && !missingCorpus) || (!missingCatalog && ['index.json', 'termeni.json', 'manifest.json'].includes(name))) {
    send(req, res, path.join(root, 'web/data', name), true);
  } else {res.writeHead(404, {'Access-Control-Allow-Origin': '*'}); res.end();}
});
const app = http.createServer((req, res) => {
  const name = req.url === '/' ? 'index.html' : req.url.slice(1);
  const file = path.join(output, name);
  send(req, res, fs.existsSync(file) ? file : path.join(root, 'web', name));
});
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
(async () => {
  let browser;
  try {
    await listen(remote); await listen(app);
    const origin = `http://127.0.0.1:${remote.address().port}`;
    const code = `import importlib.util, pathlib, sys\np=pathlib.Path(sys.argv[1])\ns=importlib.util.spec_from_file_location('legacy_builder',p)\nb=importlib.util.module_from_spec(s)\ns.loader.exec_module(b)\nb.ROOT=pathlib.Path(sys.argv[2]); b.WEB=pathlib.Path(sys.argv[3]); b.DATA=b.ROOT/'web/data'\nb._worker(sys.argv[4]); b._pagina(sys.argv[4],1)`;
    execFileSync('uv', ['run', 'python', '-c', code, process.env.BROWSER_BUILD_MODULE || path.join(root, 'scripts/construieste_web.py'), root, output, origin], {cwd: root});
    browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
    for (const noCatalog of [false, true]) {
      missingCatalog = noCatalog;
      const context = await browser.newContext({serviceWorkers: 'block'}), page = await context.newPage();
      await page.goto(`http://127.0.0.1:${app.address().port}`);
      const summary = await page.evaluate(async () => {const r = await fetch('/api/rezumat'); return {status:r.status, data:await r.json()};});
      assert.equal(summary.status, 200, JSON.stringify(summary));
      assert.equal(summary.data.initiative, 0);
      const missing = await page.evaluate(() => window.browserSourceLimitations);
      for (const file of ['vid.json', 'eu.db', 'graf.db', 'initiative.db']) assert.ok(missing.includes(file));
      if (noCatalog) assert.ok(missing.includes('manifest.json'));
      assert.ok(await page.locator('#browser-source-limitations').isVisible());
      assert.ok(!requests.some(url => url.endsWith('/vid.json')), 'Undeclared reports must not be fetched or borrowed');
      await context.close();
    }
    missingCorpus = true;
    const page = await browser.newPage(); await page.goto(`http://127.0.0.1:${app.address().port}`);
    const failure = await page.evaluate(async () => (await fetch('/api/rezumat')).status);
    assert.equal(failure, 503);
    console.log('Real Pyodide: missing optional databases/catalogs boot with limitations; missing corpus fails.');
  } finally {
    if (browser) await browser.close(); remote.closeAllConnections(); app.closeAllConnections(); remote.close(); app.close();
    fs.rmSync(output, {recursive: true, force: true});
  }
})().catch(e => {console.error(e); process.exitCode = 1;});
