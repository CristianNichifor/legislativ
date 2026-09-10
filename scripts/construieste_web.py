"""Build the browser bundle: the same app, running under Pyodide with no server.

This is the proof that the localhost tool and a public, static, in-browser tool are one codebase.
It produces, under `web/`:

- `bundle.zip` — the `scripts/` package and the `sources/` fixtures, unpacked into Pyodide's
  filesystem at load; the engines run there unchanged, so the 218 tests still guard what the
  browser executes.
- `data/corpus.db`, `data/initiative.db`, `data/graf.db`, `data/eu.db` — a **slice** of the corpus
  (a few hundred acts, plus a curated handful the demo cites), the whole graph when small, and the
  local CELEX source database. The full corpus is not shippable to a browser; the real app fetches
  per act on demand. This slice is enough to prove the wiring.
- `index.html` — the existing `app/index.html`, with one script prepended: it boots Pyodide,
  loads the bundle and the data into the virtual filesystem, and replaces `fetch('/api/…')` with a
  call into `scripts.servicii`. The rest of the page is untouched, so the whole UI runs client-side.

By default, nothing the user types leaves the tab. The deterministic checks run locally. The only
exception is explicit "Limbaj clar" rewriting when the user chooses online BYOK; then the browser
sends that text directly to the selected provider or user-owned Worker, with the user's key.

Two data sources:

- `--sursa corpus` (default when `corpus.db` exists) — a **slice** of the collected corpus, a few
  hundred acts plus a curated handful. For a local preview against real breadth.
- `--sursa fixturi` — a small corpus built from the committed `sources/*.gz` pages (Legea 98/2016
  and the acts around it), parsed to the article tree. Needs nothing git-ignored, so **CI can
  reproduce it**; this is what the public demo deploys.

Standard library only. Run: `uv run python -m scripts.construieste_web [--sursa fixturi|corpus]`.
"""
# ruff: noqa: E501  — this module embeds an HTML/JS boot blob where line length is not meaningful.

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from scripts import depozit, shard
from scripts.graf import construieste as construieste_graf
from scripts.parsare import din_fisier

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = WEB / "data"
SOURCES = ROOT / "sources"

# Acts the demo cites, kept in the slice no matter where they fall in the corpus, plus the first
# N by insertion order so search has a body to work against.
CURATE = ["lege-98-2016", "lege-99-2016", "lege-100-2016", "lege-24-2000", "oug-57-2019"]
# The demo's corpus. Every act here carries its full article tree, which is what makes the
# linter and the impact view demonstrate themselves — a flat act cannot. Measured: about
# 150 KB an act once structured, so this is the size dial for the published build.
N_ACTE = 400
N_INITIATIVE = 300

# The privacy boundary, made a rule the page obeys rather than a claim it makes. `connect-src` is the
# load-bearing line: deterministic checks can reach only this origin and the Pyodide/WebLLM assets.
# The extra AI provider origins are for explicit online BYOK rewriting, where the UI says the text
# and session-held key go directly to that provider. `'unsafe-eval'` is Pyodide's (it compiles Python
# and instantiates WebAssembly); `'unsafe-inline'` covers the app's first-party inline script/styles.
CSP = (
    "default-src 'self'; "
    # esm.run/jsdelivr serve Pyodide and (opt-in) the WebLLM library; both are code, not data.
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://esm.run; "
    # connect targets:
    #  · `api.openai.com` / `api.anthropic.com` — explicit BYOK rewrite providers;
    #  · `*.workers.dev` — a user-owned Worker rewrite endpoint;
    #  · huggingface.co / hf.co — WebLLM's on-device model weights, for the opt-in local AI. The
    #    provision text stays on the device; only the model is downloaded.
    "connect-src 'self' https://cdn.jsdelivr.net https://esm.run https://api.openai.com "
    "https://api.anthropic.com https://*.workers.dev "
    "https://huggingface.co https://*.huggingface.co https://hf.co https://*.hf.co "
    "https://raw.githubusercontent.com__DEPOZIT_CSP__; "
    "worker-src 'self' blob:; child-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)


def _origine(url: str) -> str:
    """The scheme://host of a repository URL — the most a CSP entry should ever name."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def _csp(depozit: str = "") -> str:
    """The page's policy, widened by exactly one origin when a repository is configured.

    This is worth being honest about: `connect-src` is what makes "the draft never leaves the tab"
    a rule rather than a promise, and naming another origin means a compromised script could in
    principle POST there. Three things keep that from being a real hole — the entry is the bucket's
    own origin and nothing broader, the bucket's CORS allows only GET and HEAD, and an unsigned
    write to R2 is rejected outright. The read it enables is public law; the draft is still only
    ever sent to 'self'.
    """
    return CSP.replace("__DEPOZIT_CSP__", f" {_origine(depozit)}" if depozit else "")


PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js"

# The worker: Pyodide, the engines, and all the data — off the main thread. It loads Pyodide and
# its sqlite3 package, unpacks the engines and fixtures into its own filesystem, mounts the data,
# and then answers request messages. Nothing here touches the DOM, so no call it makes can ever
# block the page: boot (seconds) and every lint or search run happen here, and the UI stays live.
WORKER = """
importScripts("__PYODIDE__");
importScripts("browser-workspace.js");
let raspunde, cautaJson, runtime;
const bootMissing = [];

// De unde se citește corpusul întreg. Gol = comportamentul vechi (doar catalogul mic + felii).
const DEPOZIT = "__DEPOZIT__";
// SQLite citește pagini de 4 KB. Bucăți mai mari aduc pagini pe care nu le cere nimeni: la 1 MiB
// (implicitul Emscripten) o lege costă 94 MB, la 16 KB costă 3 MB — adică exact textul ei.
const BUCATA = 16384;

// Un cititor cu memorie pe bucăți. Nimic nu descarcă fișierul întreg: SQLite cere o pagină, noi
// aducem bucata care o conține și o ținem. Aceeași interfață peste două surse — rețea sau disc.
function cuMemorie(adu, lungime){
  const bucati = new Map();
  return {
    lungime,
    citeste(dest, la, poz, cati){
      let scrisi = 0;
      while (scrisi < cati) {
        const idx = ((poz + scrisi) / BUCATA) | 0;
        let b = bucati.get(idx);
        if (!b) {
          b = adu(idx * BUCATA, Math.min((idx + 1) * BUCATA, lungime) - 1);
          bucati.set(idx, b);
        }
        const inceput = (poz + scrisi) % BUCATA;
        const acum = Math.min(b.length - inceput, cati - scrisi);
        // Ieșirea tăcută de aici ar returna o citire scurtă, iar SQLite ar lua restul paginii
        // drept date. Mai bine o eroare pe care o vede cineva decât un articol inventat.
        if (acum <= 0) throw new Error(`bucata ${idx} e prea scurtă: ${b.length} octeți`);
        dest.set(b.subarray(inceput, inceput + acum), la + scrisi);
        scrisi += acum;
      }
      return scrisi;
    },
  };
}

// Online: cereri Range către depozit. Sincrone — permise doar în worker, care e exact unde suntem.
//
// O bucată scurtă nu e o bucată: SQLite ar primi o pagină ciuntită și ar citi din ea numere care
// arată ca niște numere. De aceea nimic sub lungimea cerută nu e acceptat, iar un 429 (depozitul
// public are limită de ritm) se reîncearcă în loc să treacă drept date.
function aduBucata(url, de, la, incercari){
  const cati = la - de + 1;
  let ultima = "";
  for (let i = 0; i < incercari; i++) {
    if (i) {
      // Worker-ul e oricum blocat de XHR-ul sincron; așteptarea asta doar rărește reîncercările.
      const pana = Date.now() + 250 * Math.pow(2, i - 1);
      while (Date.now() < pana) { /* pauză înainte de următoarea încercare */ }
    }
    const x = new XMLHttpRequest();
    x.open("GET", url, false);
    x.responseType = "arraybuffer";
    x.setRequestHeader("Range", `bytes=${de}-${la}`);
    try { x.send(); } catch (e) { ultima = e.message; continue; }
    if (x.status !== 206 && x.status !== 200) { ultima = "HTTP " + x.status; continue; }
    const b = new Uint8Array(x.response || 0);
    if (b.length !== cati) { ultima = `${b.length} din ${cati} octeți`; continue; }
    return b;
  }
  throw new Error(`nu am putut citi octeții ${de}-${la}: ${ultima}`);
}

function prinRange(url, incercari){
  const cap = new XMLHttpRequest();
  cap.open("HEAD", url, false);
  cap.send();
  if (cap.status >= 400) throw new Error("depozitul nu răspunde: " + cap.status);
  if (cap.getResponseHeader("Accept-Ranges") !== "bytes") {
    throw new Error("depozitul nu servește intervale de octeți; corpusul nu poate fi citit pe bucăți");
  }
  const lungime = Number(cap.getResponseHeader("Content-Length"));
  if (!lungime) throw new Error("depozitul nu spune cât e de mare fișierul");
  return cuMemorie((de, la) => aduBucata(url, de, la, incercari || 4), lungime);
}

// Offline: aceleași pagini, citite de pe disc. Copia descărcată o dată nu mai cere nimic rețelei.
function dinOpfs(maner){
  return cuMemorie((de, la) => {
    const b = new Uint8Array(la - de + 1);
    maner.read(b, { at: de });
    return b;
  }, maner.getSize());
}

// Îl legăm de sistemul de fișiere al Pyodide, ca SQLite să-l vadă ca pe orice fișier obișnuit.
function monteaza(pyodide, sursa, nume){
  const FS = pyodide.FS;
  try { FS.unlink("data/" + nume); } catch (e) { /* nu era acolo */ }
  const nod = FS.createFile("data", nume, {}, true, false);
  nod.usedBytes = sursa.lungime;
  nod.stream_ops = {
    llseek(flux, deplasare, dinCe){
      let p = deplasare;
      if (dinCe === 1) p += flux.position;
      else if (dinCe === 2) p = sursa.lungime + deplasare;
      if (p < 0) throw new FS.ErrnoError(28);
      return p;
    },
    read(flux, tampon, deplasare, cati, pozitie){
      if (pozitie >= sursa.lungime) return 0;
      return sursa.citeste(tampon, deplasare, pozitie, Math.min(sursa.lungime - pozitie, cati));
    },
  };
}

// Copia offline, dacă utilizatorul a cerut-o vreodată. O singură cerere pentru tot fișierul.
async function copiaOffline(nume){
  const dir = await navigator.storage.getDirectory();
  const f = await dir.getFileHandle(nume);   // aruncă dacă nu există; atunci mergem în depozit
  return dinOpfs(await f.createSyncAccessHandle());
}

async function boot(){
  const pyodide = await loadPyodide();
  runtime = pyodide;
  await pyodide.loadPackage("sqlite3");  // unvendored in Pyodide; the corpus is SQLite
  const zip = await fetch("bundle.zip").then(r=>r.arrayBuffer());
  pyodide.unpackArchive(zip, "zip");
  try { pyodide.FS.mkdir("data"); } catch (e) {}
  // The whole corpus (corpus.db) is NOT shipped — only the small catalog the engines need: titles
  // (index.json), counts (manifest.json), the terminology dictionary (termeni.json), the graph,
  // the initiatives and the optional EU index. Search reads per-act shards over HTTP on demand;
  // nothing pulls the corpus.
  // Cu un depozit în spate, graf.db, initiative.db și eu.db se montează de acolo întregi; nu are rost să
  // descărcăm feliile lor de câteva sute de acte doar ca să le înlocuim imediat.
  const catalog = ["index.json","termeni.json","manifest.json","vid.json","neconstitutional.json","norme_lovite.json","considerente.json","parlament.json","ue_acoperire.json"];
  // The historical publisher exposes these three files, not the optional reports.
  // Never substitute bundled reports for an unrelated pinned remote corpus.
  const legacyCatalog = ['index.json', 'termeni.json', 'manifest.json'];
  if (DEPOZIT) bootMissing.push(...catalog.filter(name => !legacyCatalog.includes(name)));
  for (const name of (DEPOZIT ? legacyCatalog : ["graf.db","initiative.db","eu.db"].concat(catalog))) {
    // Reports and databases must describe the same selected generation.
    const url = DEPOZIT
      ? DEPOZIT.replace(/\\/$/, "") + "/" + name
      : "data/" + name;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      const buf = new Uint8Array(await response.arrayBuffer());
      pyodide.FS.writeFile("data/"+name, buf);
    } catch (error) {
      if (!DEPOZIT) throw error;
      bootMissing.push(name);
    }
  }
  // Only a bounded build-time slice, never an implicit full dataset download.
  if (!DEPOZIT && __LOCAL_CORPUS__) {
    const response = await fetch('data/corpus.db');
    if (!response.ok) throw new Error('Corpusul inclus nu este disponibil.');
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length > 32 * 1024 * 1024) throw new Error('Corpusul inclus depaseste limita de 32 MiB.');
    pyodide.FS.writeFile('data/corpus.db', bytes);
  }
  // Toate bazele mari, fără a descărca niciuna. Textul legii stă în corpus.db, citările în
  // graf.db, Parlamentul în initiative.db, iar dreptul UE în eu.db — degeaba am 203.353 de acte
  // dacă «cine citează legea asta», «cum a votat deputatul» și CELEX răspund din felii.
  if (DEPOZIT) {
    const baza = DEPOZIT.replace(/\\/$/, "");
    for (const nume of ["corpus.db", "graf.db", "initiative.db", "eu.db"]) {
      let sursa = null, deUnde = "";
      // Legacy OPFS files have no verified generation identity. Never mount them over
      // a selected remote release; the dataset protocol owns future verified caches.
      {
        try { sursa = prinRange(`${baza}/${nume}`); deUnde = "depozit"; }
        catch (e2) {
          if (nume === 'corpus.db') throw new Error(`${nume} din generatia selectata nu e disponibil: ${e2.message}`);
          bootMissing.push(nume);
        }
      }
      if (sursa) {
        monteaza(pyodide, sursa, nume);
        console.log(`${nume} montat (${deUnde}): ${(sursa.lungime/1e9).toFixed(2)} GB`);
      }
    }
  }
  raspunde = pyodide.runPython(`
import sys, json
if '.' not in sys.path: sys.path.insert(0, '.')
from urllib.parse import parse_qs
from scripts.servicii import (Stare, rezumat, _lint, _cauta, _vecini,
                              _redacteaza, _sugereaza, _consolidat, _compune, _act, _parseaza,
                              _norma, _termeni, _dictionar, _regula, _impact,
                              _cronologie, _citari, _supraveghere,
                              _opinie, _opinie_cerere,
                              _deputati, _parcurs, _rol, _stenograma, _dezbateri,
                              _domenii, _matrice, _matrice_acte, _matrice_dosar, _prevedere,
                              _matrice_contradictii,
                              _matrice_proiecte, _conflicte_proiecte,
                              _cine_citeaza, _ue, _acoperire_ue, _import_queue_ue)
if __CORPUS_INTREG__:
    from pathlib import Path
    if not Path('data/initiative.db').exists():
        from scripts import depozit
        with depozit.deschide('data/initiative.db'):
            pass
_stare = Stare('data/corpus.db', 'data/initiative.db', 'data/graf.db', 'data/eu.db',
               date_dir='data',
               corpus_intreg=__CORPUS_INTREG__)
_stare.dosare_db = '/workspace/dosare.db'
def _raspunde(path, query, body, method='GET'):
    qs = parse_qs(query or '')
    def _i(k):
        v = qs.get(k, [''])[0]
        try: return int(v) if v not in ('', None) else None
        except ValueError: return None
    if path == '/api/rezumat': out = rezumat(_stare)
    elif path == '/api/dosare' or path.startswith('/api/dosare/'):
        from scripts.browser_workspace import route
        out = route(_stare, path, qs, json.loads(body or '{}'), method)
    elif path == '/api/inventar-surse':
        from scripts.servicii import _inventar_surse
        out = _inventar_surse(_stare)
    elif path == '/api/cauta':
        # The same filters the shard path accepts. Dropping them here would give the UI a type
        # selector and a year range that quietly do nothing.
        out = _cauta(qs.get('q',[''])[0], _stare,
                     tip=(qs.get('tip',[''])[0] or None),
                     an_min=_i('an_min'), an_max=_i('an_max'),
                     limita=_i('limita') or 25, offset=_i('offset') or 0)
    elif path == '/api/vecini':
        a = qs.get('act',[''])[0]; out = _vecini(a, _stare) if a else {'error':'act lipsă'}
    elif path == '/api/cronologie': out = _cronologie(qs.get('act',[''])[0], _stare)
    elif path == '/api/citari': out = _citari(qs.get('act',[''])[0], _stare)
    elif path == '/api/supraveghere': out = _supraveghere(qs.get('act',[''])[0], _stare)
    elif path == '/api/redacteaza': out = _redacteaza(qs)
    elif path == '/api/sugereaza': out = _sugereaza(qs)
    elif path == '/api/consolidat': out = _consolidat(qs)
    elif path == '/api/act': out = _act(qs, _stare)
    elif path == '/api/deputati': out = _deputati(qs, _stare)
    elif path == '/api/parcurs': out = _parcurs(qs, _stare)
    elif path == '/api/rol': out = _rol(qs, _stare)
    elif path == '/api/stenograma': out = _stenograma(qs, _stare)
    elif path == '/api/dezbateri': out = _dezbateri(qs, _stare)
    elif path == '/api/domenii': out = _domenii(qs, _stare)
    elif path == '/api/matrice': out = _matrice(qs, _stare)
    elif path == '/api/matrice-acte': out = _matrice_acte(qs, _stare)
    elif path == '/api/matrice-dosar': out = _matrice_dosar(qs, _stare)
    elif path == '/api/matrice-contradictii': out = _matrice_contradictii(qs, _stare)
    elif path == '/api/matrice-proiecte': out = _matrice_proiecte(qs, _stare)
    elif path == '/api/surse-proiecte':
        out = {'mod': 'static', 'error': 'Achizitia surselor este disponibila numai in aplicatia locala.'}
    elif path == '/api/ue/surse':
        out = {'mod': 'static', 'error': 'Importul si istoricul surselor UE sunt disponibile numai in aplicatia locala.'}
    elif path in ('/api/documente-proiect', '/api/importa-proiect',
                  '/api/diferente-versiuni', '/api/actualizare-proiect'):
        out = {'error': 'Importul oficial este disponibil în aplicația locală.'}
    elif path == '/api/conflicte-proiecte': out = _conflicte_proiecte(json.loads(body or '{}'), _stare)
    elif path == '/api/prevedere': out = _prevedere(qs, _stare)
    elif path == '/api/cine-citeaza': out = _cine_citeaza(qs, _stare)
    elif path == '/api/ue/acoperire': out = _acoperire_ue(qs, _stare)
    elif path == '/api/ue/import-queue': out = _import_queue_ue(qs, _stare)
    elif path == '/api/compune':
        out = _compune(json.loads(body or '{}').get('interventii', []))
    elif path == '/api/parseaza':
        out = _parseaza((json.loads(body or '{}').get('text') or '').strip())
    elif path == '/api/norma':
        out = _norma((json.loads(body or '{}').get('text') or '').strip())
    elif path == '/api/termeni':
        out = _termeni((json.loads(body or '{}').get('text') or '').strip(), _stare)
    elif path == '/api/dictionar': out = _dictionar(_stare)
    elif path == '/api/regula':
        out = _regula((json.loads(body or '{}').get('text') or '').strip())
    elif path == '/api/opinie-cerere':
        out = _opinie_cerere((json.loads(body or '{}').get('draft') or '').strip(), _stare)
    elif path == '/api/opinie':
        _b = json.loads(body or '{}')
        # The tab ran WebLLM and posts the raw reply; the context is rebuilt here, never accepted
        # from the client, because the context is what the validator holds the model to.
        out = _opinie((_b.get('draft') or '').strip(), _stare, brut=_b.get('brut'))
    elif path == '/api/impact':
        draft = (json.loads(body or '{}').get('draft') or '').strip()
        out = _impact(draft, _stare) if draft else {'error':'draft gol'}
    elif path == '/api/ue':
        _b = json.loads(body or '{}')
        draft = (_b.get('draft') or '').strip()
        out = _ue(draft, _stare, limita=_b.get('limita', 12), limba=_b.get('limba')) if draft else {'error':'draft gol'}
    elif path == '/api/lint':
        draft = (json.loads(body or '{}').get('draft') or '').strip()
        out = _lint(draft, _stare) if draft else {'error':'draft gol'}
    else: out = {'error':'not found'}
    return json.dumps(out, ensure_ascii=False)
_raspunde
  `);
  // Search is async (it fetches index/act shards on demand), so it is a separate coroutine.
  cautaJson = pyodide.runPython(`
import json as _json
from urllib.parse import parse_qs
from scripts.cauta_web import cauta as _cauta_shard, cauta_montat as _cauta_montat
_DEPOZIT = __DEPOZIT_PY__
def _int(qs, k):
    v = qs.get(k, [''])[0]
    try: return int(v) if v not in ('', None) else None
    except ValueError: return None
async def _cauta_json(query):
    qs = parse_qs(query or '')
    q = qs.get('q', [''])[0]
    filtre = dict(
        limita=_int(qs, 'limita') or 25, offset=_int(qs, 'offset') or 0,
        tip=(qs.get('tip', [''])[0] or None),
        an_min=_int(qs, 'an_min'), an_max=_int(qs, 'an_max'))
    # Only the mounted path knows about the title band; the standalone shards rank titles first
    # already, so there is nothing to ask them for.
    doar_titluri = qs.get('doar_titluri', [''])[0] == '1'
    # The index shards live in the repository; the titles and snippets come from the mounted
    # corpus, so nothing has to ship the 7,3 GB of per-act files the standalone shards needed.
    if _DEPOZIT:
        r = await _cauta_montat(q, _DEPOZIT, 'data/corpus.db', doar_titluri=doar_titluri, **filtre)
    else:
        r = await _cauta_shard(q, 'data', **filtre)
    return _json.dumps(r, ensure_ascii=False)
_cauta_json
  `);
}
const gata = boot().then(()=>postMessage({type:"ready", limitations:bootMissing}))
                   .catch(e=>{ postMessage({type:"error", error:String(e)}); throw e; });
let requestQueue = Promise.resolve();
onmessage = (e) => { requestQueue = requestQueue.then(() => handle(e.data)); };
async function handle(request) {
  const {id, path, query, body, method = 'GET'} = request;
  try {
    await gata;
    // Căutarea trece mereu prin index, nu prin corpus. Măsurat pe corpusul montat: ordonarea a
    // 6.478 potriviri după bm25 a cerut ~1.000 de citiri împrăștiate și 291 de secunde, fiindcă
    // bm25 vrea lungimea fiecărui document. Aceleași potriviri ies din index în două cereri.
    const execute = () => raspunde(path, query, body, method);
    const res = (path === '/api/dosare' || path.startsWith('/api/dosare/') || path === '/api/browser-workspace')
      ? await BrowserWorkspace.run(runtime, {...request, method}, execute)
      : (path === "/api/cauta")
      ? await cautaJson(query || "")
      : execute();
    postMessage({id, ok:true, result:res});
  } catch(err){
    postMessage({id, ok:false, error:String(err)});
  }
};
"""

# The main-thread manager: it owns no engine and no data — it starts the worker and turns each
# `fetch('/api/…')` into a message to it, awaiting the reply. Because the work is in the worker,
# the page never freezes: the spinner keeps spinning, the textarea keeps typing, while a lint or a
# search runs. Runs before the app's own inline script (document order), so `window.fetch` is
# already redirected by the time the page makes its first call.
BOOT = """
<script src="browser-workspace.js"></script>
<script>
(function(){
  const origFetch = window.fetch.bind(window);

  // Căutarea nu trece prin worker. Motorul din worker citește SQLite sincron, deci N rezultate
  // înseamnă întotdeauna N drumuri dus-întors, unul după altul: o pagină de 25 a măsurat 46,6 s.
  // Pagefind ține fragmentul în index și le aduce în paralel — aceeași pagină, 0,1–0,35 s. Clientul
  // e servit de la noi, ca `script-src 'self'` să rămână întreg; doar datele vin din depozit.
  const DEPOZIT_CAUTARE = "__DEPOZIT__";
  // Indexul e tăiat în felii pentru că indexarea ține tot în memorie: ~200 KB pe act, adică ~40 GB
  // pentru tot corpusul. Feliile se construiesc separat și se lipesc aici, la interogare.
  const FELII_CAUTARE = __FELII_CAUTARE__;
  let pagefind = null;
  async function motorulDeCautare(){
    if (pagefind) return pagefind;
    const baza = DEPOZIT_CAUTARE ? DEPOZIT_CAUTARE.replace(/\\/$/, "") + "/" : new URL("./", location.href).href;
    const cale = i => FELII_CAUTARE > 1 ? `${baza}pagefind-${i}/` : `${baza}pagefind/`;
    const m = await import("./pagefind/pagefind.js");
    await m.options({basePath: cale(0), language: "ro"});
    // `mergeIndex` cere aceleași opțiuni pentru fiecare felie; altfel felia adusă e căutată cu
    // limba dedusă din propriul ei `pagefind-entry.json`, nu cu româna pe care am forțat-o.
    for (let i = 1; i < FELII_CAUTARE; i++) {
      await m.mergeIndex(cale(i), {language: "ro"});
    }
    pagefind = m;
    return m;
  }

  // Câte acte intră în bandă și cât o așteptăm. Motorul stă în worker, deci o căutare făcută
  // înainte să fie cald nu blochează pagina: peste termen, răspunde Pagefind singur.
  const BANDA_TITLURI = 8, RABDARE_BANDA = 25000;
  const INCALZIRE_BANDA = "achizitii publice";
  let incalzireBanda = null;
  function incalzesteBanda(){
    if (!DEPOZIT_CAUTARE) return ready;
    if (!incalzireBanda) {
      // Interogarea nu poate fi goală: Python iese înainte să citească `index.json`.
      const p = new URLSearchParams({q: INCALZIRE_BANDA, limita: "1", doar_titluri: "1"});
      incalzireBanda = ready.then(() => call("/api/cauta", p.toString(), "").catch(e=>{
        console.warn("încălzirea benzii de titluri a eșuat:", e && e.message);
      }));
    }
    return incalzireBanda;
  }
  async function bandaTitluri(qs){
    const q = (qs.get("q") || "").trim();
    if (!q) return [];
    const p = new URLSearchParams({q, limita: String(BANDA_TITLURI), doar_titluri: "1"});
    // Aceleași filtre ca restul căutării, altfel banda ar contrazice ce a cerut utilizatorul.
    for (const k of ["tip", "an_min", "an_max"]) if (qs.get(k)) p.set(k, qs.get(k));
    try {
      const pregatire = DEPOZIT_CAUTARE ? incalzesteBanda() : ready;
      const raspuns = await Promise.race([
        pregatire.then(() => call("/api/cauta", p.toString(), "")),
        new Promise(res => setTimeout(() => res(null), RABDARE_BANDA)),
      ]);
      if (!raspuns) return [];
      const o = (typeof raspuns === "string") ? JSON.parse(raspuns) : raspuns;
      return (o && o.results) || [];
    } catch (e) {
      // Banda e un plus, nu o condiție: dacă motorul nu pornește, căutarea rămâne întreagă.
      console.warn("banda de titluri a eșuat:", e && e.message);
      return [];
    }
  }

  // Forma pe care o citește pagina, aceeași pe care o întorcea motorul din worker.
  async function cauta(qs){
    const q = (qs.get("q") || "").trim();
    const limita = parseInt(qs.get("limita") || "25", 10) || 25;
    const offset = parseInt(qs.get("offset") || "0", 10) || 0;
    if (!q) return {results: [], total: 0, offset, limita};

    const m = await motorulDeCautare();
    const filtre = {};
    const tip = qs.get("tip");
    if (tip) filtre.tip = [tip];
    // Pagefind filtrează pe valori exacte, nu pe intervale: un interval de ani devine lista lui.
    const anMin = parseInt(qs.get("an_min") || "", 10);
    const anMax = parseInt(qs.get("an_max") || "", 10);
    if (!isNaN(anMin) || !isNaN(anMax)) {
      const de = isNaN(anMin) ? 1800 : anMin, la = isNaN(anMax) ? new Date().getFullYear() : anMax;
      if (la - de <= 200) {
        filtre.an = [];
        for (let a = de; a <= la; a++) filtre.an.push(String(a));
      }
    }

    // Două întrebări diferite pun aceleași cuvinte: „despre ce act e vorba" și „unde apare
    // sintagma". Pagefind răspunde la a doua și nu poate fi învățat că titlul valorează mai mult:
    // „achiziții publice" apare undeva în 20.367 de acte, iar Legea 98/2016 iese pe locul 172.
    // Indexul de titluri răspunde la prima, e mic, și e deja publicat lângă corpus.
    const [r, banda] = await Promise.all([
      m.search(q, Object.keys(filtre).length ? {filters: filtre} : undefined),
      offset === 0 ? bandaTitluri(qs) : Promise.resolve([]),
    ]);
    const pagina = r.results.slice(offset, offset + limita);
    // Aici e câștigul: fragmentele se aduc deodată, nu unul câte unul.
    const date = await Promise.all(pagina.map(x => x.data()));
    const corp = date.map(d => ({
      act_id: (d.meta && d.meta.id) || String(d.url || "").replace(/^#\\/act\\//, ""),
      locator: "",
      fragment: d.excerpt || "",
      titlu: (d.meta && d.meta.title) || "",
      sursa_url: "",
      tip: (d.meta && d.meta.tip) || "",
      an: d.meta && d.meta.an ? parseInt(d.meta.an, 10) : null,
    }));
    // Banda intră deasupra, iar dublurile cad din corp — un act al cărui titlu se potrivește nu
    // trebuie să apară de două ori doar fiindcă sintagma e și în text.
    const dinBanda = new Set(banda.map(x => x.act_id));
    const rezultate = banda.concat(corp.filter(x => !dinBanda.has(x.act_id))).slice(0, limita);
    return {results: rezultate, total: r.results.length, offset, limita};
  }

  let resolveReady, rejectReady;
  const ready = new Promise((res, rej)=>{ resolveReady=res; rejectReady=rej; });
  const worker = new Worker("worker.js");
  const pending = new Map(); let seq = 0;
  worker.onmessage = (e)=>{
    const m = e.data;
    if (m.type === "ready"){
      window.browserSourceLimitations = m.limitations || [];
      if (window.browserSourceLimitations.length) {
        const note = document.createElement('p'); note.id = 'browser-source-limitations';
        note.className = 'hint'; note.setAttribute('role', 'status');
        note.style.overflowWrap = 'anywhere';
        note.textContent = 'Acoperire indisponibila pentru sursele optionale: ' + window.browserSourceLimitations.join(', ');
        document.querySelector('header')?.after(note);
      }
      resolveReady(); return;
    }
    if (m.type === "error"){
      rejectReady(new Error(m.error));
      const s = document.getElementById("stat");
      if (s) s.textContent = "eroare la pornirea motorului: " + m.error;
      return;
    }
    const p = pending.get(m.id); if (!p) return; pending.delete(m.id);
    m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
  };
  worker.onerror = (e)=>{
    const error = new Error(e.message || "worker error");
    rejectReady(error);
    for (const p of pending.values()) p.reject(error);
    pending.clear();
  };
  function call(path, query, body, method = 'GET'){
    return new Promise((resolve, reject)=>{
      const id = ++seq; pending.set(id, {resolve, reject});
      worker.postMessage({id, path, query, body, method});
    });
  }
  if (DEPOZIT_CAUTARE) incalzesteBanda().catch(()=>{});
  window.fetch = async function(url, opts){
    const u = (typeof url === "string") ? url : (url && url.url);
    if (u && u.indexOf("/api/cauta") === 0) {
      try {
        const parsed = new URL(u, location.origin);
        const out = await cauta(parsed.searchParams);
        return new Response(JSON.stringify(out), {status:200, headers:{"Content-Type":"application/json; charset=utf-8"}});
      } catch (e) {
        // Fără index publicat, căutarea rămâne cea din motor — mai lentă, dar prezentă.
        console.warn("căutarea prin index a eșuat, revin la motor:", e && e.message);
      }
    }
    if (u && u.indexOf("/api/") === 0) {
      try { await ready; }
      catch(e){ return new Response(JSON.stringify({error:"motor indisponibil: "+e}), {status:503}); }
      try {
        const parsed = new URL(u, location.origin);
        const body = (opts && opts.body) ? String(opts.body) : "";
        const res = await call(parsed.pathname, parsed.search.slice(1), body, (opts && opts.method || 'GET').toUpperCase());
        return new Response(res, {status:200, headers:{"Content-Type":"application/json; charset=utf-8"}});
      } catch(e){
        return new Response(JSON.stringify({error:String(e)}), {status:500});
      }
    }
    return origFetch(url, opts);
  };
  // The service worker caches the shell and the data (versioned), so a second visit is instant and
  // works offline; a new build changes the version baked into sw.js, which retires the old cache.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(()=>{});
  }
})();
</script>
"""

# The service worker. Two strategies, on purpose:
#   - the **shell** (page, worker.js, bundle, the small catalog) is served **network-first**, so a
#     redeploy shows the new UI on the next visit — cache is only the offline fallback. Serving the
#     shell cache-first was the bug that pinned people to an old page after a UI change that did not
#     touch the data.
#   - the **big data** (the .db files, the search shards) is served **cache-first**: large, changes
#     rarely, and versioned by the cache name, so it stays instant and offline once fetched.
# The version is a content hash baked into sw.js at build time; a new build is a new sw.js, which the
# browser installs and whose `activate` deletes every older cache — the resync, without a manual clear.
SW = """
const VERSIUNE = "__VERSION__";
const CACHE = "legislativ-shell-" + VERSIUNE;
const NUCLEU = [
  "./", "./index.html", "./worker.js", "./browser-workspace.js", "./bundle.zip",
  __FONTURI__,
  "./data/graf.db", "./data/initiative.db", "./data/eu.db",
  "./data/index.json", "./data/termeni.json", "./data/manifest.json", "./data/vid.json",
  "./data/neconstitutional.json", "./data/norme_lovite.json", "./data/considerente.json",
  "./data/ue_acoperire.json"
];
const eBig = (p) => /\\/data\\/.*\\.db$/.test(p) || p.includes("/data/idx/") || p.includes("/data/acte/");
// Fonts join the big data on the cache-first path, not the network-first shell path: they are
// immutable within a build (a new build means a new cache name), and a network-first font is a
// font that arrives after the text does — the page flashes in Georgia on every visit.
const eFont = (p) => p.includes("/fonts/");
self.addEventListener("install", (e)=>{
  e.waitUntil(
    caches.open(CACHE).then(c=>c.addAll(NUCLEU)).catch(()=>{}).then(()=>self.skipWaiting())
  );
});
self.addEventListener("activate", (e)=>{
  e.waitUntil(
    caches.keys()
      .then(ks=>Promise.all(ks.map(k=>k!==CACHE && k.startsWith('legislativ-shell-') ? caches.delete(k) : null)))
      .then(()=>self.clients.claim())
  );
});
self.addEventListener("fetch", (e)=>{
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;  // Pyodide CDN and the like go straight to network
  if (eBig(url.pathname) || eFont(url.pathname)) {
    e.respondWith(caches.open(CACHE).then(async (c)=>{
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res && res.ok) c.put(req, res.clone());  // fill the cache with per-act shards on first use
      return res;
    }));
  } else {
    // shell: network-first, cache as the offline fallback
    e.respondWith((async ()=>{
      try {
        const res = await fetch(req);
        if (res && res.ok) { const c = await caches.open(CACHE); c.put(req, res.clone()); }
        return res;
      } catch (err) {
        const hit = await caches.open(CACHE).then(c=>c.match(req));
        return hit || Response.error();
      }
    })());
  }
});
"""


def _slice_corpus() -> None:
    tinta = DATA / "corpus.db"
    if tinta.exists():
        tinta.unlink()
    with depozit.deschide(str(tinta)) as con:
        con.execute("ATTACH DATABASE ? AS plin", (str(ROOT / "corpus.db"),))
        marcaje = ",".join("?" * len(CURATE))
        # Chosen by year, not by `rowid`. A rowid is a position in a file, not an identity: every
        # `scrie_act` deletes its row and inserts it again, so after a re-enrichment and the
        # namesake recovery the lowest rowid in `acte` is far above any small N — `rowid <= 200`
        # silently matched nothing and the build shipped five acts, the curated ones, and called
        # itself a corpus.
        con.execute(
            f"INSERT INTO acte SELECT * FROM plin.acte WHERE id IN ({marcaje})"
            " UNION SELECT * FROM plin.acte WHERE id NOT IN"
            f" ({marcaje}) ORDER BY an DESC, id LIMIT ?",
            (*CURATE, *CURATE, N_ACTE),
        )
        con.execute(
            "INSERT INTO provizii SELECT * FROM plin.provizii WHERE act_id IN (SELECT id FROM acte)"
        )
        con.execute(
            "INSERT INTO provizii_fts(text, act_id, locator) SELECT text, act_id, locator "
            "FROM provizii"
        )
        con.commit()
        con.execute("DETACH plin")
    print(f"  corpus slice → {tinta} ({tinta.stat().st_size / 1e6:.1f} MB)")


def _slice_initiative(*, tot_parlamentul: bool = False) -> None:
    """The initiatives, and the people behind them.

    This used to copy 300 rows of `initiative` and nothing else, which is why the published build
    had no members in it: the signatures, the divisions and the passages all live in other tables
    and none of them was shipped. A tab that searches parliamentarians against a database with no
    parliamentarians finds none, and says so, which reads like a bug in the search.

    **What is shipped is a size decision, and the numbers are the reason.** Measured over the
    collected corpus, after `VACUUM`:

    | slice                                    | size    |
    |------------------------------------------|---------|
    | initiatives + signatures + divisions      |  17,4 MB |
    | + the roll of every division, 2024 only   |  36,5 MB |
    | + the roll of every division, all         | 103,6 MB |
    | + everything said in plenary              | 131,3 MB |

    The whole build was 6,4 MB before this. The first row is shipped because it is what makes a
    member reachable at all — who signed what, and what became of it. The other two are a
    twenty-fold increase for two panels, so they are behind `--tot-parlamentul` and the page says
    they are absent rather than drawing an empty section.

    `obiect` is kept even though dropping it would save 3,5 MB: it is the bill's own statement of
    what it sets out to do, and it is the thing a reader opens an initiative to read.
    """
    tinta = DATA / "initiative.db"
    if tinta.exists():
        tinta.unlink()
    with depozit.deschide(str(tinta)) as con:
        con.execute("ATTACH DATABASE ? AS plin", (str(ROOT / "initiative.db"),))
        # Every initiative, not the first 300: a member's record is a list of bills, and a slice
        # that held a fourteenth of them would report a fourteenth of their work as all of it.
        for tabel in ("initiative", "initiativa_initiator", "initiativa_vot", "initiativa_etapa"):
            _copiaza_daca_exista(con, tabel)
        if tot_parlamentul:
            for tabel in (
                "vot_nominal_sedinta",
                "vot_nominal",
                "stenograma",
                "interventie",
            ):
                _copiaza_daca_exista(con, tabel)
            con.execute(
                "INSERT INTO interventie_fts(text, vorbitor, ids, idm, ord)"
                " SELECT text, coalesce(vorbitor,''), ids, idm, ord FROM interventie"
            )
        con.execute(
            "INSERT INTO initiative_fts(titlu, obiect, plx_id) "
            "SELECT titlu, obiect, plx_id FROM initiative"
        )
        con.commit()
        con.execute("DETACH plin")
    print(f"  initiative slice → {tinta} ({tinta.stat().st_size / 1e6:.1f} MB)")


def _slice_graf() -> None:
    """The edges that touch an act in the slice, rather than the whole graph.

    The graph used to be copied whole because it was 2,4 MB. Rebuilt over the collected corpus it
    is **203 MB** — 926 759 edges over 203 353 acts — and a visitor would download all of it once,
    to ask about the few hundred acts the build actually carries. 1,6% of the edges touch those
    acts; the rest answer questions this build cannot ask.

    Both directions are kept, and that is the point of the filter rather than an accident: an edge
    *into* a sliced act is "what depends on this", which is the question the impact view exists to
    answer, and it comes from acts that are not themselves shipped.
    """
    tinta = DATA / "graf.db"
    if tinta.exists():
        tinta.unlink()
    surse = ROOT / "graf.db"
    if not surse.is_file():
        return
    # `uri=True` on the connection, or `ATTACH 'file:…?mode=ro'` is read as a filename with a
    # question mark in it and fails to open.
    con = sqlite3.connect(str(tinta), uri=True)
    try:
        con.execute("ATTACH DATABASE ? AS plin", (f"file:{surse}?mode=ro",))
        # The acts actually shipped, read from the slice this build just wrote.
        con.execute("ATTACH DATABASE ? AS felie", (f"file:{DATA / 'corpus.db'}?mode=ro",))
        con.execute(
            "CREATE TABLE muchii AS SELECT m.* FROM plin.muchii m"
            " WHERE m.din_act IN (SELECT id FROM felie.acte)"
            "    OR m.catre_act IN (SELECT id FROM felie.acte)"
        )
        con.execute("CREATE INDEX idx_muchii_catre ON muchii(catre_act)")
        con.execute("CREATE INDEX idx_muchii_din ON muchii(din_act)")
        con.execute("CREATE INDEX idx_muchii_din_loc ON muchii(din_act, din_locator)")
        con.commit()
    finally:
        con.close()
    n = tinta.stat().st_size / 1e6
    print(f"  graf → {tinta} ({n:.1f} MB, doar muchiile care ating felia)")


def _finalizeaza_un_db(db: Path) -> None:
    con = sqlite3.connect(str(db))
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")
        con.commit()
    finally:
        con.close()
    for sidecar in (db.with_suffix(db.suffix + "-wal"), db.with_suffix(db.suffix + "-shm")):
        if sidecar.exists():
            sidecar.unlink()


def _initiative_goala(cale: Path) -> None:
    with depozit.deschide(str(cale)):
        pass
    _finalizeaza_un_db(cale)


def _ue_goala(cale: Path) -> None:
    from scripts import cellar

    with cellar.deschide(str(cale)):
        pass
    _finalizeaza_un_db(cale)


def _slice_ue() -> None:
    """Ship the local CELEX database where it exists; otherwise ship an empty searchable schema."""
    tinta = DATA / "eu.db"
    if tinta.exists():
        tinta.unlink()
    sursa = ROOT / "eu.db"
    if sursa.is_file():
        src = sqlite3.connect(f"file:{sursa}?mode=ro", uri=True)
        dst = sqlite3.connect(str(tinta))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        _finalizeaza_un_db(tinta)
        print(f"  UE → {tinta} ({tinta.stat().st_size / 1e6:.1f} MB)")
    else:
        _ue_goala(tinta)
        print(f"  UE (gol) → {tinta}")


def _copiaza_daca_exista(con, tabel: str) -> None:
    """Copy a table from the attached corpus, or skip it where that corpus predates it.

    A build must not fail because the machine it runs on collected its initiatives before the
    transcripts existed. A missing table is a missing panel, not a broken build.
    """
    are = con.execute(
        "SELECT 1 FROM plin.sqlite_master WHERE type='table' AND name=?", (tabel,)
    ).fetchone()
    if are:
        con.execute(f"INSERT INTO {tabel} SELECT * FROM plin.{tabel}")


def _date_din_corpus(*, tot_parlamentul: bool = False) -> None:
    """The slice path: a few hundred acts out of the collected corpus, plus the whole graph."""
    _slice_corpus()
    _slice_initiative(tot_parlamentul=tot_parlamentul)
    _slice_graf()
    _slice_ue()


def _date_din_fixturi() -> None:
    """The reproducible path: a small corpus parsed from the committed `sources/*.gz` pages.

    Every act here is a real portal page kept as a parser fixture, read to its article tree by
    `parsare.din_fisier` and stored by `depozit.scrie_act` — so search runs over real provisions,
    consolidation has its target and amending act, and `graf.construieste` derives real edges (the
    amending act's changes to Legea 98/2016). Needs nothing git-ignored, so CI builds the same
    bytes. The initiatives database is created empty — there is no committed initiative fixture,
    and an empty table is the honest state, not a fake row.
    """
    corpus = DATA / "corpus.db"
    if corpus.exists():
        corpus.unlink()
    from scripts.depozit import scrie_act

    n = 0
    with depozit.deschide(str(corpus)) as con:
        for gz in sorted(SOURCES.glob("*.gz")):
            scrie_act(con, din_fisier(gz))
            n += 1
        con.commit()
    print(f"  corpus din {n} fixturi → {corpus} ({corpus.stat().st_size / 1e6:.2f} MB)")

    ini = DATA / "initiative.db"
    if ini.exists():
        ini.unlink()
    _initiative_goala(ini)  # schema only — no committed initiative fixture, so it stays empty
    print(f"  initiative (gol) → {ini}")

    graf = DATA / "graf.db"
    if graf.exists():
        graf.unlink()
    muchii = construieste_graf(str(corpus), str(graf), log=lambda *_: None)
    print(f"  graf din corpus → {graf} ({muchii} muchii)")
    _slice_ue()


def _finalizeaza_db() -> None:
    """Fold each DB's WAL back into one file and drop the sidecars, so a static host serves a
    single self-contained file per database (a browser cannot stitch `-wal`/`-shm` back together).
    """
    for db in sorted(DATA.glob("*.db")):
        _finalizeaza_un_db(db)


def _parlament_json() -> None:
    """The groups and the directory, prebuilt as `data/parlament.json`.

    Built from the whole `initiative.db`, not the shipped slice, for the same reason the register
    is: the answer is small because Parliament has 818 members, not because the corpus is small.
    0,38 MB against a query that took 54,2 s over a mounted database — which the page rendered as
    an empty panel, since a panel cannot tell "slow" from "nothing here".
    """
    sursa = ROOT / "initiative.db"
    cale = sursa if sursa.is_file() else DATA / "initiative.db"
    if not Path(cale).is_file():
        return
    from scripts import servicii

    date = servicii.construieste_parlament(str(cale))
    (DATA / "parlament.json").write_text(json.dumps(date, ensure_ascii=False), encoding="utf-8")
    n = len(date.get("persoane", {}).get("", []))
    marime = (DATA / "parlament.json").stat().st_size / 1e6
    print(f"  parlament → {DATA / 'parlament.json'} ({n} persoane, {marime:.2f} MB)")


def _ue_acoperire_json() -> None:
    from scripts.acoperire_ue import raport

    corpus = ROOT / "corpus.db" if (ROOT / "corpus.db").is_file() else DATA / "corpus.db"
    initiative = (
        ROOT / "initiative.db" if (ROOT / "initiative.db").is_file() else DATA / "initiative.db"
    )
    eu = ROOT / "eu.db" if (ROOT / "eu.db").is_file() else DATA / "eu.db"
    out = raport(corpus, initiative, eu, limita=100)
    (DATA / "ue_acoperire.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(
        f"  acoperire UE → {DATA / 'ue_acoperire.json'} "
        f"({out['total']} CELEX, {out['neimportate']} lipsă)"
    )


def _vid_json() -> None:
    """The unmet-obligations report, precomputed over the sliced corpus + its graph and shipped as
    `data/vid.json`. Built here (with full corpus access) so the browser never scans for it."""
    from scripts import servicii

    vids = servicii.construieste_vid(str(DATA / "corpus.db"), str(DATA / "graf.db"))
    (DATA / "vid.json").write_text(json.dumps(vids, ensure_ascii=False), encoding="utf-8")
    print(f"  vid → {DATA / 'vid.json'} ({len(vids)} obligații fără implementare găsită)")


def _neconstitutional_json() -> None:
    """The struck-but-unrepaired register, shipped whole as `data/neconstitutional.json`.

    **Built from the full corpus when there is one, not from the demo slice** — the same call the
    build already makes for `graf.db`, and for the same reason. 183 rows over the whole national
    corpus is 97 KB; the slice holds a few hundred acts and almost no Curtea Constituțională
    decisions, so building from it would ship an empty register and quietly turn the
    constitutionality check into a feature that never fires. The register is small *because the
    Court struck few things*, not because the corpus is small, so slicing buys nothing and costs
    the whole answer.

    Falls back to the slice where no collected corpus exists (CI, a fresh clone), which yields an
    honestly empty register rather than a fabricated one.
    """
    from scripts import servicii

    plin, graf_plin = ROOT / "corpus.db", ROOT / "graf.db"
    intreg = plin.is_file() and graf_plin.is_file()
    corpus, graf = (plin, graf_plin) if intreg else (DATA / "corpus.db", DATA / "graf.db")
    if not intreg:
        print("  neconstituțional: fără corpus colectat, folosesc felia (registru gol e corect)")

    randuri = servicii.construieste_neconstitutional(str(corpus), str(graf))
    (DATA / "neconstitutional.json").write_text(
        json.dumps(randuri, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  neconstituțional → {DATA / 'neconstitutional.json'} "
        f"({len(randuri)} prevederi lovite fără reparație în corpus)"
    )

    # Every strike whose wording the corpus can quote — not only the unrepaired ones, because
    # art. 147 (4) catches a re-enactment through the original decision regardless of what
    # happened to the original text afterwards.
    norme = servicii.construieste_norme_lovite(str(corpus))
    (DATA / "norme_lovite.json").write_text(json.dumps(norme, ensure_ascii=False), encoding="utf-8")
    print(f"  norme lovite → {DATA / 'norme_lovite.json'} ({len(norme)} prevederi cu text)")

    # Shipped separately and fetched lazily: only the model pass reads the reasoning, and that pass
    # needs a model. An offline session should not download it to never open it.
    cons = servicii.construieste_considerente(str(corpus))
    (DATA / "considerente.json").write_text(json.dumps(cons, ensure_ascii=False), encoding="utf-8")
    print(f"  considerente → {DATA / 'considerente.json'} ({len(cons)} decizii)")


def _bundle() -> None:
    tinta = WEB / "bundle.zip"
    with zipfile.ZipFile(tinta, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT / "scripts").glob("*.py")):
            z.write(p, f"scripts/{p.name}")
        for p in sorted((ROOT / "sources").glob("*.gz")):
            z.write(p, f"sources/{p.name}")
    print(f"  bundle → {tinta} ({tinta.stat().st_size / 1e6:.1f} MB)")


def _worker(depozit: str = "") -> None:
    corpus = DATA / "corpus.db"
    local_corpus = not depozit and corpus.is_file() and corpus.stat().st_size <= 32 * 1024 * 1024
    text = (
        WORKER.replace("__PYODIDE__", PYODIDE)
        .replace("__LOCAL_CORPUS__", "true" if local_corpus else "false")
        .replace("__DEPOZIT__", depozit)
        # With a repository behind it the corpus is really there, so counts, titles and search
        # must come from the database and not from the slice manifest.
        .replace("__CORPUS_INTREG__", "True" if depozit else "False")
        # The same URL again, as a Python literal: the search runs inside Pyodide and fetches its
        # index shards from the repository, not from the shipped `data/` directory.
        .replace("__DEPOZIT_PY__", repr(depozit.rstrip("/")) if depozit else "None")
    )
    (WEB / "worker.js").write_text(text, encoding="utf-8")
    unde = depozit or "fără depozit — doar catalogul și feliile"
    print(f"  worker → {WEB / 'worker.js'} ({unde})")


def _versiune_si_sw() -> str:
    """A content hash of the corpus and graph, written into the service worker and the manifest.

    Same data → same version → the browser keeps its cache; changed data → new version → the new
    sw.js retires the old cache. The corpus file already reflects every provision, so hashing it
    (and the graph) captures any change that matters to what the app shows.
    """
    # Hash the browser-facing catalog, not the monolithic corpus.db — the corpus is not shipped to
    # the client and need not even be present (a dataset release carries only the shards). index.json
    # + manifest.json capture the act set and the counts; graf.db the amendment edges; eu.db the
    # optional CELEX source index, and ue_acoperire.json the missing-import queue.
    h = hashlib.sha256()
    for name in ("index.json", "manifest.json", "graf.db", "eu.db", "ue_acoperire.json"):
        p = DATA / name
        if p.is_file():
            h.update(p.read_bytes())
    versiune = h.hexdigest()[:12]

    # Precache exactly the fonts that were copied, rather than a list kept in sync by hand.
    fonturi = sorted(p.name for p in (WEB / "fonts").glob("*.woff2"))
    lista = ", ".join(f'"./fonts/{n}"' for n in fonturi)
    sw = SW.replace("__VERSION__", versiune).replace("__FONTURI__", lista)
    (WEB / "sw.js").write_text(sw, encoding="utf-8")
    manifest = DATA / "manifest.json"
    date = json.loads(manifest.read_text()) if manifest.is_file() else {}
    date["versiune"] = versiune
    manifest.write_text(json.dumps(date, ensure_ascii=False), encoding="utf-8")
    print(f"  sw + versiune → {versiune}")
    return versiune


def _fonturi() -> None:
    """Copy `app/fonts/` next to the built page.

    The page's `font-src 'self'` leaves no other option: a webfont must be served from this origin
    or it does not load. The files are committed, vendored by `scripts/fonturi.py`; this step only
    moves them, so a checkout with no network still builds a correctly-typeset page.
    """
    sursa = ROOT / "app" / "fonts"
    if not sursa.is_dir():
        raise SystemExit("app/fonts lipsește — rulează `uv run python -m scripts.fonturi`")
    tinta = WEB / "fonts"
    shutil.rmtree(tinta, ignore_errors=True)
    shutil.copytree(sursa, tinta)
    kb = sum(f.stat().st_size for f in tinta.glob("*.woff2")) / 1024
    print(f"  fonturi ({len(list(tinta.glob('*.woff2')))} fișiere, {kb:.0f} KB) → {tinta}")


# Pagefind ships a client and an index. The client is small and comes from our own origin, so
# `script-src \'self\'` stays as it is — only the index and the per-result fragments live in the
# repository, and those are data the CSP already allows as connect targets.
# The client kept in git, for builds that have no index to take it from — CI, above all.
CLIENT_COMIS = ROOT / "app" / "pagefind"

CLIENT_CAUTARE = (
    "pagefind.js",
    "pagefind-worker.js",
    "pagefind-entry.json",
    "wasm.ro.pagefind",
    "wasm.unknown.pagefind",
)


def _felii_cautare() -> list[Path]:
    """The search index directories, in the order the client merges them.

    An index built in one piece is `pagefind/`; one built in slices is `pagefind-0/`, `pagefind-1/`
    and so on, because Pagefind holds every record in memory until it writes and the whole corpus
    does not fit. Both shapes are read here, so nothing else has to know which one was built.
    """
    felii = sorted(
        (d for d in ROOT.glob("pagefind-*") if d.is_dir()),
        key=lambda d: int(d.name.split("-")[-1]),
    )
    if felii:
        return felii
    intreg = ROOT / "pagefind"
    return [intreg] if intreg.is_dir() else []


def _verifica_versiunea_clientului() -> None:
    """Refuse a committed client that no longer matches the indexer that writes the index.

    Pagefind's client and its index files are one version. Drift between them does not announce
    itself: the client loads, the query runs, and the answers are wrong or absent.
    """
    fisier = CLIENT_COMIS / "VERSIUNE"
    if not fisier.is_file():
        return
    comis = fisier.read_text(encoding="utf-8").strip()
    pin = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["dependencies"][
        "pagefind"
    ]
    if comis != pin:
        raise SystemExit(
            f"clientul din app/pagefind/ e Pagefind {comis}, dar indexul se face cu {pin}. "
            f"Reînnoiește-l dintr-o felie proaspătă și scrie {pin} în app/pagefind/VERSIUNE."
        )


def _client_cautare() -> None:
    """Copy Pagefind's client next to the page.

    The page imports the client from its own origin — `script-src 'self'` is what makes "the draft
    never leaves the tab" a rule, and loading a script from the repository would widen it. So the
    client has to be in the build.

    It comes from a freshly built index when there is one, and otherwise from `app/pagefind/`,
    which is in git for exactly this reason: CI has no index — it is git-ignored and lives in the
    object store — so a build there would otherwise ship a page whose first search 404s.
    """
    _verifica_versiunea_clientului()
    felii = _felii_cautare()
    # The client is one and the same in every slice — it is the data beside it that differs.
    sursa = felii[0] if felii else CLIENT_COMIS
    if not sursa.is_dir():
        return
    tinta = WEB / "pagefind"
    tinta.mkdir(parents=True, exist_ok=True)
    n = 0
    for nume in CLIENT_CAUTARE:
        f = sursa / nume
        if f.is_file():
            shutil.copy2(f, tinta / nume)
            n += 1
    # The language metadata is named with a content hash, so it is matched rather than listed.
    for f in sursa.glob("pagefind.*.pf_meta"):
        shutil.copy2(f, tinta / f.name)
        n += 1
    print(f"  client de căutare → {tinta} ({n} fișiere)")


def _pagina(depozit: str = "", felii_cautare: int = 0) -> None:
    sursa = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    if "<head>" not in sursa or "<body>" not in sursa:
        raise SystemExit("app/index.html nu are <head>/<body> — nu știu unde să injectez")
    csp = f'<meta http-equiv="Content-Security-Policy" content="{_csp(depozit)}">'
    pagina = sursa.replace("<head>", "<head>\n" + csp, 1)
    # Prepend the manager block right after <body> so it runs before the app's own inline script.
    # The slice count is baked in rather than discovered: the client would otherwise have to probe
    # for a directory that is not there, and a 404 on every load is a worse answer than a number.
    #
    # It cannot always be counted here. This runs in CI too, where the index is absent — it is not
    # in git — so a count taken from disk would silently come back 1 and the page would be built
    # against `pagefind/`, an index that may hold a fraction of the corpus and would answer every
    # query as if that fraction were the law. Rather than guess, refuse.
    felii = felii_cautare or len(_felii_cautare())
    if depozit and not felii:
        raise SystemExit(
            "nu știu în câte felii e indexul din depozit și nu găsesc niciun director pagefind* "
            "aici — dă --felii-cautare N. Fără el aș construi pagina pentru un singur index, "
            "care poate acoperi o mică parte din corpus fără să se vadă."
        )
    felii = felii or 1
    boot = BOOT.replace("__DEPOZIT__", depozit).replace("__FELII_CAUTARE__", str(felii))
    pagina = pagina.replace("<body>", "<body>\n" + boot, 1)
    # The shared page describes localhost storage; only the browser build changes this copy.
    pagina = pagina.replace(
        "Nu se salvează în browser și nu se trimite altor persoane.",
        "Se salveaza in acest browser; nu se trimite altor persoane. Exportati copii de siguranta: stergerea datelor site-ului elimina dosarele.",
    )
    shutil.copy2(ROOT / "app" / "browser-workspace.js", WEB / "browser-workspace.js")
    # Local update controls own their unsupported-endpoint state in the shared page.
    updates = ROOT / "app" / "dataset-updates.js"
    if updates.is_file():
        shutil.copy2(updates, WEB / updates.name)
    (WEB / "index.html").write_text(pagina, encoding="utf-8")
    print(f"  pagină (cu CSP) → {WEB / 'index.html'}")


def main(
    sursa: str, *, tot_parlamentul: bool = False, depozit: str = "", felii_cautare: int = 0
) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"construiesc web/ (sursă: {sursa}) …")
    if sursa == "gata":
        # The data is already in web/data — a dataset release was downloaded and extracted. Build
        # only the shell over it; do not rebuild or reshard what a slower job already produced.
        # The corpus itself is not needed here (the browser reads the shards); the catalog is.
        if not (DATA / "index.json").is_file() or not (DATA / "graf.db").is_file():
            raise SystemExit("--sursa gata: web/data este incomplet (release-ul nu a fost extras)")
        # A collection release may carry no initiatives; the engines still open initiative.db, so
        # give them an empty one rather than let the open fail.
        ini = DATA / "initiative.db"
        if not ini.is_file():
            _initiative_goala(ini)
            print(f"  initiative (gol, lipsea din release) → {ini}")
        eu = DATA / "eu.db"
        if not eu.is_file():
            _ue_goala(eu)
            print(f"  UE (gol, lipsea din release) → {eu}")
        if not (DATA / "ue_acoperire.json").is_file():
            _ue_acoperire_json()
        print(f"  folosesc datele deja prezente în {DATA}")
    else:
        if sursa == "fixturi":
            _date_din_fixturi()
        else:
            _date_din_corpus(tot_parlamentul=tot_parlamentul)
        _finalizeaza_db()
        # Sharded from the slice, because a static site cannot hold the corpus: `index.json` alone
        # reached **91 MB** on every first visit, and the per-act files ran **36 KB each**, about
        # **7,3 GB**. GitHub Pages tops out near a gigabyte.
        #
        # `--depozit` is the way out, and it does not need the shards at all. The browser mounts
        # `corpus.db` from object storage and SQLite reads the pages it wants over Range requests:
        # measured at **3,0 MB to open a 1.455-provision law** — the text itself — and **0,1 MB to
        # fetch an act by id**. The shards stay for builds without a repository behind them.
        shard.construieste(str(DATA / "corpus.db"), str(DATA))
        _vid_json()
        _neconstitutional_json()
        _parlament_json()
        _ue_acoperire_json()
    _bundle()
    _worker(depozit)
    _fonturi()
    _client_cautare()
    _pagina(depozit, felii_cautare)
    _versiune_si_sw()
    print("gata. servește cu:  uv run python -m http.server -d web 8080")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Construiește build-ul de browser (Pyodide).")
    implicit = "corpus" if (ROOT / "corpus.db").is_file() else "fixturi"
    ap.add_argument(
        "--tot-parlamentul",
        action="store_true",
        help=(
            "include rolul fiecărui vot și tot ce s-a spus în plen. Cresc build-ul de la ~17 MB "
            "la ~131 MB; fără ele, panourile respective spun că lipsesc."
        ),
    )
    ap.add_argument(
        "--sursa",
        choices=("fixturi", "corpus", "gata"),
        default=implicit,
        help=(
            "'fixturi' (reproductibil în CI, din sources/), 'corpus' (felie din corpus.db), "
            "sau 'gata' (datele sunt deja în web/data, dintr-un release descărcat)"
        ),
    )
    ap.add_argument(
        "--depozit",
        default="",
        metavar="URL",
        help=(
            "adresa depozitului de obiecte care ține corpus.db (ex. https://date.exemplu.ro). "
            "Cu ea, browserul citește tot corpusul prin cereri Range, fără să-l descarce; "
            "fără ea, rămâne pe catalogul mic și pe felii."
        ),
    )
    ap.add_argument(
        "--felii-cautare",
        type=int,
        default=0,
        metavar="N",
        help=(
            "în câte felii e tăiat indexul de căutare din depozit. Implicit: câte directoare "
            "pagefind* sunt aici. În CI nu e niciunul — indexul nu stă în git — deci acolo "
            "numărul trebuie dat, altfel construcția se oprește."
        ),
    )
    a = ap.parse_args()
    main(
        a.sursa, tot_parlamentul=a.tot_parlamentul, depozit=a.depozit, felii_cautare=a.felii_cautare
    )
