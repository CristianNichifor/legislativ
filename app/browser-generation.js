/* Public generation metadata and verified small reports, separate from private dossiers. */
(function (scope) {
  'use strict';
  const STORE = 'legislativ-public-generation-v1', MAX_META = 256 * 1024;
  const REPORTS = ['termeni.json', 'manifest.json', 'vid.json', 'neconstitutional.json',
    'norme_lovite.json', 'considerente.json', 'parlament.json', 'ue_acoperire.json'];
  const DATABASES = ['corpus.db', 'initiative.db', 'graf.db', 'eu.db'];
  const LABELS = {'index.json':'Index legislativ', 'termeni.json':'Index de terminologie',
    'manifest.json':'Indicatori de acoperire', 'vid.json':'Rapoarte privind obligatiile',
    'neconstitutional.json':'Rapoarte de constitutionalitate', 'norme_lovite.json':'Prevederi afectate de decizii',
    'considerente.json':'Motivarile deciziilor', 'parlament.json':'Traseu parlamentar',
    'initiative.db':'Traseu parlamentar', 'graf.db':'Legaturi intre acte',
    'eu.db':'Legislatie UE', 'ue_acoperire.json':'Acoperirea legislatiei UE'};
  scope.browserSourceLabels = files => [...new Set(files.map(name => LABELS[name] || 'Surse suplimentare'))].join(', ');
  const decode = bytes => new TextDecoder('utf-8', {fatal: true}).decode(bytes);
  const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
    b => b.toString(16).padStart(2, '0')).join('');
  async function database() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(STORE, 1);
      let blocked = false;
      request.onupgradeneeded = () => request.result.createObjectStore('state');
      request.onsuccess = () => {if (blocked) request.result.close(); else resolve(request.result);};
      request.onerror = () => reject(request.error);
      request.onblocked = () => {blocked = true; reject(new Error('Stocarea publica este blocata de alta fila. Inchideti fila respectiva si reincercati.'));};
    });
  }
  async function state(next) {
    const db = await database();
    try { return await new Promise((resolve, reject) => {
      const tx = db.transaction('state', next ? 'readwrite' : 'readonly', {durability: 'strict'});
      const request = next ? tx.objectStore('state').put(next, 'selection') : tx.objectStore('state').get('selection');
      tx.oncomplete = () => resolve(next || request.result || {selected: null, previous: null});
      tx.onabort = () => reject(tx.error || new Error('Selectia publica nu a putut fi pastrata.'));
    }); } finally { db.close(); }
  }
  async function bytes(response, limit) {
    if (Number(response.headers.get('Content-Length') || 0) > limit) throw new Error('Fisier peste limita declarata.');
    const reader = response.body.getReader(), chunks = []; let length = 0;
    try {
      while (true) {
        const {value, done} = await reader.read(); if (done) break;
        length += value.length;
        if (length > limit) throw new Error('Fisier peste limita declarata.');
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => {}); }
    const result = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) {result.set(chunk, offset); offset += chunk.length;}
    return result;
  }
  const brief = item => item && ({release: item.manifest.release, sha256: item.sha256,
    created_at: item.manifest.created_at, checked_at: item.checked_at,
    missing: [...DATABASES, ...REPORTS].filter(name => !item.manifest.files.some(f => f.name === name)),
    report_bytes: item.manifest.files.filter(f => REPORTS.includes(f.name)).reduce((n, f) => n + f.bytes, 0)});
  scope.BrowserGeneration = class {
    constructor(config, contract) {this.config = config; this.contract = contract; this.active = null; this.offer = null; this.candidate = null;}
    async fetch(url, options = {}) {
      if (new URL(url).origin !== new URL(this.config.channel).origin) throw new Error('Origine publica nepermisa.');
      const response = await fetch(url, {credentials: 'omit', redirect: 'error', cache: 'no-store',
        signal: AbortSignal.timeout(30000), ...options});
      if (!response.ok || response.url !== url) throw new Error(`Sursa publica indisponibila: HTTP ${response.status}`);
      return response;
    }
    validate(kind, raw) {return JSON.parse(this.contract(kind, raw, this.config.channel, this.config.allowLoopback));}
    async offerFrom(pointer, raw) {
      if (await digest(raw) !== pointer.sha256) throw new Error('SHA-256 al manifestului nu corespunde canalului.');
      const manifest = this.validate('manifest', decode(raw));
      const folder = new URL('.', pointer.manifest).href;
      if (new URL(folder).pathname !== '/' + manifest.release + '/') throw new Error('Versiunea manifestului nu corespunde adresei.');
      return {url: pointer.manifest, folder, sha256: pointer.sha256, manifest_text: decode(raw), manifest,
        checked_at: new Date().toISOString()};
    }
    async validateStored(item) {
      const pointer = this.validate('channel', JSON.stringify({schema_version: 1, manifest: item.url, sha256: item.sha256}));
      const verified = await this.offerFrom(pointer, new TextEncoder().encode(item.manifest_text));
      return {...verified, checked_at: item.checked_at, reports: item.reports};
    }
    async check() {
      this.candidate = null; this.offer = null;
      const pointer = this.validate('channel', decode(await bytes(await this.fetch(this.config.channel), MAX_META)));
      const offer = await this.offerFrom(pointer, await bytes(await this.fetch(pointer.manifest), MAX_META));
      this.offer = offer; return brief(offer);
    }
    async probe(item) {
      for (const entry of item.manifest.files.filter(f => DATABASES.includes(f.name))) {
        const url = item.folder + entry.name;
        const head = await this.fetch(url, {method: 'HEAD'});
        if (head.headers.get('Accept-Ranges') !== 'bytes' || Number(head.headers.get('Content-Length')) !== entry.bytes) {
          throw new Error(`${entry.name}: HEAD/Range sau lungime incompatibila.`);
        }
        const end = Math.min(99, entry.bytes - 1);
        const part = await this.fetch(url, {headers: {Range: `bytes=0-${end}`}});
        if (part.status !== 206 || part.headers.get('Content-Range') !== `bytes 0-${end}/${entry.bytes}`) {
          throw new Error(`${entry.name}: Content-Range incompatibil.`);
        }
        const header = await bytes(part, end + 1);
        if (header.length !== end + 1 || decode(header.slice(0, 15)) !== 'SQLite format 3' || header[18] !== 1 || header[19] !== 1) {
          throw new Error(`${entry.name}: baza SQLite nu este standalone DELETE-journal.`);
        }
      }
    }
    async prepare(hash, stored = null) {
      const offer = stored || this.offer;
      if (!offer || offer.sha256 !== hash) throw new Error('Verificati din nou oferta publica.');
      const candidate = {...offer, reports: {}};
      for (const entry of offer.manifest.files.filter(f => REPORTS.includes(f.name))) {
        const raw = stored ? stored.reports?.[entry.name] : await bytes(await this.fetch(offer.folder + entry.name), entry.bytes);
        if (!(raw instanceof Uint8Array) || raw.length !== entry.bytes || await digest(raw) !== entry.sha256) {
          throw new Error(`${entry.name}: integritatea raportului nu corespunde manifestului.`);
        }
        JSON.parse(decode(raw)); candidate.reports[entry.name] = raw;
      }
      await this.probe(candidate);
      this.candidate = candidate; return brief(candidate);
    }
    async select(hash, expected) {
      if (!navigator.locks) throw new Error('Selectia necesita Web Locks.');
      return navigator.locks.request(STORE, async () => {
        const current = await state();
        if ((current.selected?.sha256 || null) !== expected) throw new Error('Alta fila a schimbat selectia. Reincarcati starea.');
        if (!this.candidate || this.candidate.sha256 !== hash) throw new Error('Oferta nu este pregatita.');
        if (current.selected?.sha256 !== hash) await state({selected: this.candidate, previous: current.selected});
        return this.status();
      });
    }
    async clear(expected) {
      return navigator.locks.request(STORE, async () => {
        const current = await state();
        if ((current.selected?.sha256 || null) !== expected) throw new Error('Alta fila a schimbat selectia.');
        await state({selected: null, previous: current.selected || current.previous}); return this.status();
      });
    }
    async load() {
      const current = await state();
      if (!current.selected) return null;
      const selected = await this.validateStored(current.selected);
      await this.prepare(selected.sha256, selected);
      return this.candidate;
    }
    async status() {
      const current = await state();
      return {active: brief(this.active), selected: brief(current.selected), previous: brief(current.previous),
        offer: brief(this.offer), channel: this.config.channel, corpus_verified: false, online: true,
        legacy_root: this.config.legacyRoot || '', legacy_missing: this.legacyMissing || [], boot_error: this.bootError || ''};
    }
    async request(method, body) {
      const action = JSON.parse(body || '{}');
      if (method === 'GET') return JSON.stringify(await this.status());
      if (method !== 'POST') throw new Error('Metoda nesuportata.');
      if (action.action === 'check') await this.check();
      else if (action.action === 'prepare') await this.prepare(action.sha256);
      else if (action.action === 'select') await this.select(action.sha256, action.expected);
      else if (action.action === 'clear') await this.clear(action.expected);
      else if (action.action === 'previous') {
        const current = await state(); if (!current.previous) throw new Error('Nu exista o versiune precedenta.');
        const previous = await this.validateStored(current.previous);
        await this.prepare(previous.sha256, previous);
      } else throw new Error('Actiune necunoscuta.');
      return JSON.stringify(await this.status());
    }
  };
  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const panel = document.createElement('section'); panel.id = 'browser-generation';
    panel.style.cssText = 'margin:0 0 1rem;padding:.75rem 0;border-bottom:1px solid var(--rule);min-width:0;font-size:.85rem';
    panel.innerHTML = '<h2 style="font-size:1rem;margin:0">Date legislative online</h2><p data-active></p><p data-offer></p><p class="hint" data-coverage></p><p class="hint">Citire online a bazelor SQLite; hash-ul integral al bazelor nu este verificat. Fara copie offline a corpusului complet.</p><p role="status" data-status></p><div class="dossier-actions"><button type="button" class="ghost mini" data-check>Verifica actualizarile</button><button type="button" class="ghost mini" data-select hidden>Schimba versiunea online</button><button type="button" class="ghost mini" data-previous hidden>Versiunea precedenta</button><button type="button" class="ghost mini" data-clear hidden>Revino la datele incluse</button><button type="button" class="ghost mini" data-reload hidden>Reincarca pagina</button></div>';
    document.querySelector('header').after(panel);
    panel.querySelectorAll('p').forEach(p => {p.style.overflowWrap = 'anywhere'; p.style.margin = '.4rem 0';});
    panel.querySelectorAll('button').forEach(b => {b.style.maxWidth = '100%'; b.style.whiteSpace = 'normal';});
    const node = key => panel.querySelector(`[data-${key}]`);
    let current, busy = false;
    async function api(body) {
      const response = await fetch('/api/browser-generation', body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
      const out = await response.json(); if (!response.ok || out.error) throw new Error(out.error); return out;
    }
    function render(data) {
      current = data;
      const included = data.legacy_root ? 'versiunea publicata ' + data.legacy_root.split('/').filter(Boolean).pop() : 'datele incluse';
      node('active').textContent = `In aceasta fila: ${data.active?.release || included}. Selectata pentru reincarcare: ${data.selected?.release || included}.`;
      node('offer').textContent = data.offer ? `Oferta: ${data.offer.release} · publicata ${data.offer.created_at} · verificata ${data.offer.checked_at} · rapoarte: ${(data.offer.report_bytes / 1048576).toFixed(2)} MiB` : '';
      const missing = (data.offer || data.selected)?.missing || data.legacy_missing || [];
      node('coverage').textContent = missing.length ? `Surse optionale nepublicate; acoperire indisponibila: ${scope.browserSourceLabels(missing)}.` : '';
      node('select').hidden = !data.offer || data.offer.sha256 === data.selected?.sha256;
      node('clear').hidden = !data.selected; node('previous').hidden = !data.previous;
      node('reload').hidden = !data.boot_error && (data.active?.sha256 || null) === (data.selected?.sha256 || null);
    }
    async function act(fn) {
      if (busy) return; busy = true; panel.querySelectorAll('button').forEach(b => b.disabled = true);
      node('status').textContent = 'Operatie in curs...';
      try { await fn(); render(await api()); node('status').textContent = 'Operatie incheiata. Selectia se aplica la reincarcarea paginii.'; }
      catch (e) {
        node('status').textContent = 'Operatia nu a fost confirmata; verificati starea selectiei. ' + e.message;
        try {render(await api());} catch (_) {node('status').textContent += ' Starea selectiei este indisponibila.';}
      }
      finally {busy = false; panel.querySelectorAll('button').forEach(b => b.disabled = false);}
    }
    node('check').onclick = () => act(async () => {render(await api({action: 'check'}));});
    const guard = () => scope.BrowserWorkspace.guard();
    node('select').onclick = () => act(async () => {
      guard(); const hash = current.offer.sha256, expected = current.selected?.sha256 || null;
      await api({action: 'prepare', sha256: hash}); guard();
      render(await api({action: 'select', sha256: hash, expected}));
    });
    node('previous').onclick = () => act(async () => {
      guard(); const hash = current.previous.sha256, expected = current.selected?.sha256 || null;
      await api({action: 'previous'}); guard(); render(await api({action: 'select', sha256: hash, expected}));
    });
    node('clear').onclick = () => act(async () => {guard(); render(await api({action: 'clear', expected: current.selected?.sha256 || null}));});
    node('reload').onclick = () => {try {guard(); location.reload();} catch (e) {node('status').textContent = e.message;}};
    api().then(render).catch(e => {node('status').textContent = e.message;});
  });
})(globalThis);
