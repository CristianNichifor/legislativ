/* Local status only on startup. Remote checks and every mutation require a user action. */
(() => {
  const host = document.getElementById('dataset-updates');
  if (!host) return;
  const style = document.createElement('style');
  style.textContent = `
    #dataset-updates[hidden]{display:none}
    #dataset-updates{margin:0 0 1rem;padding:.75rem 0;border-bottom:1px solid var(--rule);
      font-family:var(--sans);font-size:.82rem;letter-spacing:0;min-width:0}
    #dataset-updates h2{font:600 1rem var(--sans);margin:0 0 .4rem;letter-spacing:0}
    #dataset-updates[data-empty="true"]{border-left:3px solid var(--material);padding-left:.8rem}
    #dataset-updates p{margin:.3rem 0;overflow-wrap:anywhere}
    #dataset-updates .dataset-actions{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.6rem}
    #dataset-updates button{white-space:normal;max-width:100%;min-height:2rem;letter-spacing:0}
    #dataset-updates progress{width:100%;max-width:32rem;height:.65rem;accent-color:var(--accent)}
    #dataset-updates [data-error]{color:var(--blocking)}
    #dataset-updates [hidden]{display:none}
  `;
  document.head.append(style);
  host.innerHTML = `
    <h2>Date legislative locale</h2>
    <p data-active></p><p data-offer></p>
    <p data-status role="status" aria-live="polite"></p>
    <progress data-progress hidden aria-label="Descărcarea datelor"></progress>
    <p data-file class="hint"></p><p data-error role="alert" hidden></p>
    <p class="hint" data-private>Datele private rămân pe acest calculator.</p>
    <div class="dataset-actions">
      <button type="button" class="ghost mini" data-action="check">Verifică actualizări</button>
      <button type="button" class="ghost mini" data-action="download" hidden>Descarcă versiunea</button>
      <button type="button" class="ghost mini" data-action="cancel" hidden>Oprește descărcarea</button>
      <button type="button" class="ghost mini" data-action="activate" hidden>Activează versiunea</button>
      <button type="button" class="ghost mini" data-action="rollback" hidden>Revino la versiunea anterioară</button>
      <button type="button" class="ghost mini" data-action="reload" hidden>Reîncarcă pagina</button>
    </div>`;
  const node = key => host.querySelector(`[data-${key}]`);
  const buttons = [...host.querySelectorAll('[data-action]')];
  const size = bytes => {
    if (!Number.isFinite(bytes) || bytes < 0) return '—';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return `${new Intl.NumberFormat('ro-RO', {maximumFractionDigits: i ? 1 : 0}).format(bytes)} ${units[i]}`;
  };
  let status = null, busy = false, stopped = false, timer = null;
  let initialGeneration, reloadNeeded = false, message = '';
  let pendingMutation = '', uncertain = false, locked = [];
  function lockWorkspace(lock) {
    if (lock && !locked.length) {
      for (let child = host; child.parentElement; child = child.parentElement) {
        for (const sibling of child.parentElement.children) {
          if (sibling !== child) { locked.push([sibling, sibling.inert]); sibling.inert = true; }
        }
        if (child.parentElement === document.body) break;
      }
    } else if (!lock) {
      locked.forEach(([element, inert]) => { element.inert = inert; }); locked = [];
    }
  }
  const transfer = () => ['downloading', 'verifying'].includes(status?.progress?.state);
  const offerSize = () => status?.offer?.manifest?.files?.reduce((n, f) => n + f.bytes, 0);
  function render() {
    if (!status) return;
    const active = status.active, offer = status.offer, progress = status.progress || {};
    const state = progress.state;
    host.hidden = false;
    host.dataset.empty = String(!active?.release);
    node('active').textContent = active?.release
      ? `${uncertain ? 'Ultima versiune confirmată' : 'Versiune instalată'}: ${active.release}`
      : 'Nicio bază legislativă instalată.';
    node('offer').textContent = offer
      ? `Versiune disponibilă: ${offer.manifest.release} · ${size(offerSize())}` : '';
    const labels = {
      idle: '', checked: offer ? 'Verificare încheiată.' : 'Nicio versiune nouă disponibilă.',
      downloading: `Se descarcă: ${size(progress.bytes)} / ${size(progress.total)}`,
      verifying: 'Se verifică integritatea fișierelor…', ready: 'Versiune verificată, pregătită pentru activare.',
      active: 'Versiunea este activă.', cancelled: 'Descărcare oprită.', error: 'Actualizarea nu a reușit.',
    };
    node('status').textContent = reloadNeeded
      ? 'Datele active s-au schimbat. Reîncarcă pagina când ai păstrat ciornele.' : labels[state] || '';
    if (pendingMutation || uncertain) {
      const spinner = document.createElement('span');
      spinner.className = 'spin'; spinner.setAttribute('aria-hidden', 'true');
      node('status').replaceChildren(spinner, document.createTextNode(uncertain
        ? ' Verific starea operației pe server…'
        : pendingMutation === 'activate' ? ' Activez versiunea…' : ' Revin la versiunea anterioară…'));
    }
    host.setAttribute('aria-busy', String(!!pendingMutation || uncertain));
    node('file').textContent = transfer() && progress.file
      ? `${progress.file} · ${size(progress.file_bytes)}` : '';
    const bar = node('progress');
    bar.hidden = !transfer();
    if (state === 'downloading' && progress.total > 0) {
      bar.max = progress.total;
      bar.value = Math.max(0, Math.min(progress.bytes || 0, progress.total));
    } else bar.removeAttribute('value');
    const error = message || progress.error;
    node('error').hidden = !error;
    node('error').textContent = error || '';
    node('private').hidden = status.private_data_uploaded !== false;
    for (const button of buttons) {
      const action = button.dataset.action;
      const visible = {
        check: true, download: !!offer && !transfer() && !['ready', 'active'].includes(state),
        cancel: transfer(), activate: state === 'ready',
        rollback: !!active?.previous && !transfer(), reload: reloadNeeded,
      };
      button.hidden = !visible[action];
      button.disabled = busy || uncertain || (action === 'check' && transfer());
    }
  }
  function accept(data) {
    if (data?.mode !== 'local' || !data.progress) {
      stopped = true; host.hidden = true; return;
    }
    const generation = data.active?.generation ?? data.active?.release ?? null;
    if (!status) initialGeneration = generation;
    else if (generation !== initialGeneration) reloadNeeded = true;
    status = data;
    render();
  }
  function draftsSafe() {
    // Reuse the editor, review and EU draft guards, without navigating or opening a dialog.
    const event = new Event('beforeunload', {cancelable: true});
    window.dispatchEvent(event);
    if (!event.defaultPrevented) return true;
    message = 'Există modificări nesalvate. Păstrează ciornele înainte de a schimba datele.';
    render();
    return false;
  }
  async function request(action) {
    if (busy || stopped || (uncertain && action)) return;
    if (['activate', 'rollback', 'reload'].includes(action) && !draftsSafe()) return;
    if (action === 'reload') { window.location.reload(); return; }
    const offer = status?.offer;
    if (action === 'download' && (!offer || !window.confirm(
      `Descarci versiunea ${offer.manifest.release} (${size(offerSize())})?`
    ))) return;
    if (['activate', 'rollback'].includes(action) && !window.confirm(action === 'activate'
      ? `Activezi versiunea ${offer?.manifest?.release || 'verificată'}?`
      : 'Revii la versiunea anterioară?')) return;
    busy = true;
    const mutation = ['activate', 'rollback'].includes(action);
    pendingMutation = mutation ? action : '';
    if (mutation) lockWorkspace(true);
    if (action) message = '';
    clearTimeout(timer); render();
    try {
      const response = await fetch('/api/date', {
        method: action ? 'POST' : 'GET', cache: 'no-store', redirect: 'error',
        ...(!mutation && !uncertain ? {signal: AbortSignal.timeout(10000)} : {}),
        ...(action ? {headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action, ...(['download', 'activate'].includes(action)
            ? {sha256: offer?.sha256} : {})})} : {}),
      });
      if (!status && !action && [404, 405, 501].includes(response.status)) {
        stopped = true; host.hidden = true; return;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || (response.status === 404
        ? 'Canalul de actualizări nu este disponibil.' : 'Cererea locală nu a reușit.'));
      if (status && (data?.mode !== 'local' || !data.progress)) {
        throw new Error('Starea locală nu poate fi confirmată.');
      }
      if (uncertain) { uncertain = false; message = ''; }
      accept(data);
      if (['activate', 'rollback'].includes(action) && status) reloadNeeded = true;
    } catch (error) {
      uncertain ||= mutation;
      message = uncertain
        ? 'Rezultatul operației nu este confirmat. Serverul poate continua schimbarea datelor.'
        : error.message || 'Starea locală nu poate fi citită.';
    } finally {
      busy = false; pendingMutation = '';
      if (!uncertain) lockWorkspace(false);
      if (!stopped) { render(); timer = setTimeout(() => request(), 2500); }
    }
  }
  buttons.forEach(button => button.addEventListener('click', () => request(button.dataset.action)));
  window.addEventListener('beforeunload', event => {
    if (pendingMutation || uncertain) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  request();
})();
