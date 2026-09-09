/* Shared worker persistence and browser-only recovery controls. */
(function (scope) {
  'use strict';
  const DB = 'legislativ-private-workspace-v1', LOCK = DB;
  const PATH = '/workspace/dosare.db', CANDIDATE = '/workspace/import.db';
  const MAX_BYTES = 128 * 1024 * 1024;
  async function open() {
    return new Promise((resolve, reject) => {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore('snapshots');
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
      r.onblocked = () => reject(new Error('Stocarea este blocata de alta fila.'));
    });
  }
  async function read() {
    const db = await open();
    try { return await new Promise((resolve, reject) => {
      const tx = db.transaction('snapshots', 'readonly');
      const r = tx.objectStore('snapshots').get('workspace');
      tx.oncomplete = () => resolve(r.result || {current: null, backups: []});
      tx.onabort = () => reject(tx.error || new Error('Citirea a esuat.'));
    }); } finally { db.close(); }
  }
  async function write(value) {
    const db = await open();
    try { await new Promise((resolve, reject) => {
      const tx = db.transaction('snapshots', 'readwrite', {durability: 'strict'});
      tx.objectStore('snapshots').put(value, 'workspace');
      // A request success is not a durable acknowledgement. Wait for commit.
      tx.oncomplete = resolve;
      tx.onabort = () => reject(tx.error || new Error('Salvarea durabila a esuat.'));
      tx.onerror = () => {};
    }); } finally { db.close(); }
  }
  async function record(bytes) {
    return {bytes, date: new Date().toISOString(), sha256: Array.from(new Uint8Array(
      await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('')};
  }
  async function check(item) {
    if (!item || !(item.bytes instanceof Uint8Array) || item.bytes.length > MAX_BYTES ||
        (await record(item.bytes)).sha256 !== item.sha256) throw new Error('Snapshot invalid; folositi o copie de siguranta.');
  }
  scope.BrowserWorkspace = {
    async run(py, request, execute) {
      if (!navigator.locks || !scope.indexedDB) throw new Error('Browserul necesita Web Locks si IndexedDB pentru dosare persistente.');
      return navigator.locks.request(LOCK, async () => {
        const state = await read();
        const control = request.path === '/api/browser-workspace';
        const action = control ? JSON.parse(request.body || '{}') : {};
        if (control && request.method === 'GET') return JSON.stringify({
          current: state.current && {date: state.current.date, sha256: state.current.sha256},
          backups: state.backups.map((b, index) => ({index, date: b.date, sha256: b.sha256})),
        });
        if (action.action === 'export') {
          const item = action.backup === undefined ? state.current : state.backups[action.backup];
          await check(item);
          return JSON.stringify({bytes: Array.from(item.bytes)});
        }
        py.FS.mkdirTree('/workspace');
        const restore = bytes => {
          for (const suffix of ['', '-wal', '-shm', '-journal']) {
            try { py.FS.unlink(PATH + suffix); } catch (_) { /* absent */ }
          }
          if (bytes) py.FS.writeFile(PATH, bytes);
        };
        try {
          let result;
          if (action.action === 'import' || action.action === 'restore') {
            let bytes;
            if (action.action === 'restore') {
              const item = state.backups[action.backup]; await check(item); bytes = item.bytes;
            } else {
              if (!Array.isArray(action.bytes) || action.bytes.length > MAX_BYTES ||
                  action.bytes.some(b => !Number.isInteger(b) || b < 0 || b > 255)) throw new Error('Backup invalid sau prea mare.');
              bytes = new Uint8Array(action.bytes);
            }
            for (const suffix of ['', '-wal', '-shm', '-journal']) {
              try { py.FS.unlink(CANDIDATE + suffix); } catch (_) { /* absent */ }
            }
            py.FS.writeFile(CANDIDATE, bytes);
            try { py.runPython("from scripts.browser_workspace import validate; validate('/workspace/import.db')");
              restore(py.FS.readFile(CANDIDATE));
            } finally {
              for (const suffix of ['', '-wal', '-shm', '-journal']) {
                try { py.FS.unlink(CANDIDATE + suffix); } catch (_) { /* absent */ }
              }
            }
            result = JSON.stringify({ok: true});
          } else {
            if (control) throw new Error('Actiune necunoscuta.');
            if (state.current) await check(state.current);
            restore(state.current && state.current.bytes);
            py.runPython("from scripts.browser_workspace import initialize; initialize('/workspace/dosare.db')");
            result = execute();
          }
          if (request.method === 'POST') {
            const next = await record(py.FS.readFile(PATH));
            if (next.bytes.length > MAX_BYTES) throw new Error('Limita spatiului de lucru: 128 MiB. Exportati un backup.');
            if (!state.current || state.current.sha256 !== next.sha256) {
              await write({current: next, backups: [state.current, ...state.backups].filter(Boolean).slice(0, 3)});
            }
          }
          return result;
        } catch (error) {
          restore(state.current && state.current.bytes);
          throw error;
        }
      });
    },
  };
  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const host = document.querySelector('#dossier-library');
    if (!host) return;
    const panel = document.createElement('details');
    panel.id = 'browser-workspace';
    panel.innerHTML = '<summary>Spatiu de lucru in browser</summary><div class="dossier-actions"><button type="button" data-export>Exporta backup SQLite</button><label>Importa backup SQLite<input type="file" accept=".db,.sqlite" data-import></label><label>Copii anterioare<select data-backups></select></label><button type="button" data-restore>Restaureaza copia</button><button type="button" data-backup-export>Exporta copia</button><button type="button" data-persist>Solicita pastrarea pe dispozitiv</button></div><p role="status" data-status></p>';
    host.append(panel);
    panel.querySelectorAll('button').forEach(button => button.classList.add('ghost', 'mini'));
    panel.querySelectorAll('label').forEach(label => {label.style.minWidth = '0'; label.style.maxWidth = '100%';});
    panel.querySelector('input').style.maxWidth = '100%';
    const status = panel.querySelector('[data-status]'), backups = panel.querySelector('select');
    const api = async data => {
      const r = await fetch('/api/browser-workspace', data ? {method: 'POST', body: JSON.stringify(data)} : undefined);
      const out = await r.json(); if (!r.ok || out.error) throw new Error(out.error); return out;
    };
    async function refresh() {
      const out = await api(); backups.replaceChildren();
      for (const b of out.backups) backups.add(new Option(b.date, b.index));
      panel.querySelector('[data-restore]').disabled = !out.backups.length;
      panel.querySelector('[data-backup-export]').disabled = !out.backups.length;
    }
    async function act(fn) {
      const buttons = panel.querySelectorAll('button,input,select');
      buttons.forEach(b => b.disabled = true);
      try { await fn(); status.textContent = 'Operatie finalizata.'; }
      catch (e) { status.textContent = e.message; }
      finally { buttons.forEach(b => b.disabled = false); await refresh().catch(e => {status.textContent = e.message;}); }
    }
    async function download(backup) {
      const out = await api({action: 'export', ...(backup === undefined ? {} : {backup})});
      const url = URL.createObjectURL(new Blob([new Uint8Array(out.bytes)], {type: 'application/vnd.sqlite3'}));
      const a = document.createElement('a'); a.href = url; a.download = 'legislativ-dosare.db'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
    panel.querySelector('[data-export]').onclick = () => act(() => download());
    panel.querySelector('[data-backup-export]').onclick = () => act(() => download(Number(backups.value)));
    panel.querySelector('[data-restore]').onclick = () => act(async () => {
      if (!confirm('Inlocuiti spatiul de lucru cu aceasta copie? Datele curente raman in copiile anterioare.')) return;
      await api({action: 'restore', backup: Number(backups.value)}); location.reload();
    });
    panel.querySelector('[data-import]').onchange = e => act(async () => {
      const file = e.target.files[0]; if (!file) return;
      if (file.size > MAX_BYTES) throw new Error('Limita backup: 128 MiB.');
      if (!confirm('Inlocuiti spatiul de lucru cu backupul selectat?')) return;
      await api({action: 'import', bytes: Array.from(new Uint8Array(await file.arrayBuffer()))}); location.reload();
    });
    panel.querySelector('[data-persist]').onclick = () => act(async () => {
      if (!await navigator.storage.persist()) throw new Error('Browserul nu a acordat pastrarea persistenta. Exportati un backup.');
    });
    panel.addEventListener('toggle', () => { if (panel.open) refresh().catch(e => {status.textContent = e.message;}); });
  });
})(globalThis);
