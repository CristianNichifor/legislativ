// Build: uv run python -m scripts.construieste_web --sursa fixturi
// Serve web/ on BROWSER_BASE_URL; uses real Pyodide, SQLite and IndexedDB.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
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
async function acceptanceJourney(page) {
  const search = await good(page, '/api/cauta?q=achizitii%20publice&limita=5');
  const hit = search.results.find(result => result.act_id && result.locator);
  assert.ok(hit, 'Search returns an act provision that can be opened');
  const opened = await good(page, '/api/prevedere?' + new URLSearchParams({
    act: hit.act_id,
    loc: hit.locator,
  }));
  const sourceText = opened.gasit
    ? opened.text
    : hit.fragment.replaceAll('[', '').replaceAll(']', '');
  const sourceHash = opened.source_hash || createHash('sha256').update(sourceText).digest('hex');
  const source = {
    act_id: opened.act_id || hit.act_id,
    locator: opened.locator || hit.locator,
    source_url: opened.source_url || hit.sursa_url || '',
    source_hash: sourceHash,
    text: sourceText,
  };
  assert.ok(source.text.includes('achiziții publice'), 'Opened source retains searchable text');
  assert.match(source.source_hash, /^[a-f0-9]{64}$/);

  const dossierId = '9'.repeat(32);
  const noteId = '8'.repeat(32);
  await good(page, '/api/dosare', {
    id: dossierId,
    titlu: 'Flux complet lacună legislativă',
    intrebare: 'Ce lipsește pentru aplicarea Legii 98/2016?',
    domeniu: 'achiziții publice',
  });
  const run = await good(page, '/api/dosare/rulari', {
    dosar_id: dossierId,
    filtre: {act: 'lege-98-2016'},
  });
  assert.equal(run.engine_version, 'fisa-act-v1');
  const finding = run.raport.viduri[0];
  assert.ok(finding.text.includes('norme metodologice'));
  const findings = await good(page, '/api/dosare/revizuiri?' + new URLSearchParams({
    id: dossierId,
    rulare_id: run.id,
  }));
  const findingId = findings.constatari[0].id;
  const note = await good(page, '/api/dosare/note', {
    id: noteId,
    dosar_id: dossierId,
    revizie: 0,
    title: 'Lacună privind norme metodologice',
    type: 'lacuna',
    act_id: source.act_id,
    locator: source.locator,
    evidence_quote: source.text.slice(0, 900),
    source_url: source.source_url || '',
    source_hash: source.source_hash,
    reasoning: 'Fișa actului indică obligația de norme metodologice; sursa deschisă fixează contextul achizițiilor publice.',
    status: 'ready_for_review',
  });
  assert.equal(note.status, 'ready_for_review');
  const notes = await good(page, '/api/dosare/note?id=' + dossierId);
  assert.equal(notes.total, 1);
  assert.equal(notes.recente[0].id, noteId);

  const reviewChecklist = await good(page, '/api/dosare/ai-draft', {
    task: 'review_checklist',
    title: note.title,
    type: note.type,
    context: note.reasoning,
    evidence: [{
      label: 'Prevedere deschisă din căutare',
      act_id: source.act_id,
      locator: source.locator,
      source_url: source.source_url || '',
      source_hash: source.source_hash,
      quote: note.evidence_quote,
      language: 'RON',
    }],
  });
  assert.equal(reviewChecklist.task, 'review_checklist');
  assert.equal(reviewChecklist.approval.server_calls_model, false);

  const identity = {
    dosar_id: dossierId,
    rulare_id: run.id,
    constatare_id: findingId,
  };
  const proposal = await good(page, '/api/dosare/propuneri', {
    ...identity,
    id: '7'.repeat(32),
    revizie: 0,
    titlu: 'Propunere de verificare norme metodologice',
    text: 'Se verifică și se completează normele metodologice necesare aplicării Legii nr. 98/2016.',
    motiv: 'Ciornă manuală din nota salvată și din fișa actului; nu folosește AI.',
  });
  assert.equal(proposal.revizie, 1);
  const exportedProposal = await good(page, '/api/dosare/propuneri?' + new URLSearchParams({
    id: dossierId,
    rulare_id: run.id,
    constatare_id: findingId,
    mod: 'export',
    revizie: '1',
  }));
  assert.ok(exportedProposal.markdown.includes('Propunere de modificare'));
  assert.ok(exportedProposal.markdown.includes('Text propus de autor'));
  assert.ok(exportedProposal.markdown.includes('norme metodologice'));

  const exportedWorkspace = await good(page, '/api/browser-workspace', {action: 'export'});
  await page.reload();
  assert.equal((await good(page, '/api/dosare/note?id=' + dossierId + '&note_id=' + noteId)).source_hash, source.source_hash);
  assert.equal((await good(page, '/api/dosare/propuneri?' + new URLSearchParams({
    id: dossierId,
    rulare_id: run.id,
    constatare_id: findingId,
  }))).propunere.id, proposal.id);
  await good(page, '/api/browser-workspace', {action: 'import', bytes: exportedWorkspace.bytes});
  await page.reload();
  assert.equal((await good(page, '/api/dosare?id=' + dossierId)).titlu, 'Flux complet lacună legislativă');
  assert.equal((await good(page, '/api/dosare/note?id=' + dossierId)).recente[0].id, noteId);
  const restoredExport = await good(page, '/api/dosare/propuneri?' + new URLSearchParams({
    id: dossierId,
    rulare_id: run.id,
    constatare_id: findingId,
    mod: 'export',
    revizie: '1',
  }));
  assert.equal(restoredExport.propunere.id, proposal.id);
}
(async () => {
  const seed = JSON.parse(execFileSync('uv', ['run', 'python', '-m', 'tests.browser_workspace_fixture'], {encoding: 'utf8', maxBuffer: 16 * 1024 * 1024}));
  const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
  try { for (const width of [1280]) {
    const context = await browser.newContext({viewport: {width, height: 1000}, serviceWorkers: 'block'});
    const page = await context.newPage(), errors = [], uploads = [];
    page.on('pageerror', e => errors.push(e.message));
    context.on('request', r => { if (r.method() !== 'GET' && r.method() !== 'HEAD') uploads.push(r.url()); });
    await page.goto(base);
    if (width === 1280) {
      await acceptanceJourney(page);
      console.log(`${width}: full source, note, proposal, export and restore acceptance path`);
    }
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
    await page.setViewportSize({width: 390, height: 1000});
    await page.locator('#browser-workspace').scrollIntoViewIfNeeded();
    await page.screenshot({path: '/tmp/browser-workspace-390.png'});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    assert.deepEqual(uploads, [], 'Research must not produce network writes');
    console.log(`${width}/390: reload, concurrent conflict, failed durable write rollback, backup retention, export/import/restore, UI and no uploads passed`);
    await context.close();
  }} finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
