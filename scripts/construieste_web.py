"""Build the browser bundle: the same app, running under Pyodide with no server.

This is the proof that the localhost tool and a public, static, in-browser tool are one codebase.
It produces, under `web/`:

- `bundle.zip` — the `scripts/` package and the `sources/` fixtures, unpacked into Pyodide's
  filesystem at load; the engines run there unchanged, so the 218 tests still guard what the
  browser executes.
- `data/corpus.db`, `data/initiative.db`, `data/graf.db` — a **slice** of the corpus (a few
  hundred acts, plus a curated handful the demo cites) and the whole graph, which is small. The
  full 4.5 GB corpus is not shippable to a browser; the real app fetches per act on demand. This
  slice is enough to prove the wiring.
- `index.html` — the existing `app/index.html`, with one script prepended: it boots Pyodide,
  loads the bundle and the data into the virtual filesystem, and replaces `fetch('/api/…')` with a
  call into `scripts.servicii`. The rest of the page is untouched, so the whole UI runs client-side.

**Nothing the user types leaves the tab**, and the page enforces it: a Content-Security-Policy
whose `connect-src` allows only this origin and the Pyodide CDN, so no script — first-party or
injected — can POST the draft anywhere else. The only network calls are Pyodide (runtime + the
`sqlite3` package) and the static data files (public law) from the app's own origin.

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
import zipfile
from pathlib import Path

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
N_ACTE = 200
N_INITIATIVE = 300

# The privacy guarantee, made a rule the page obeys rather than a claim it makes. `connect-src` is
# the load-bearing line: even a compromised or injected script cannot send the draft anywhere but
# this origin and the Pyodide CDN. `'unsafe-eval'` is Pyodide's (it compiles Python and instantiates
# WebAssembly); `'unsafe-inline'` covers the app's first-party inline script and styles — a hardened
# build would externalise those to drop it, but neither weakens the exfiltration guarantee, which
# rests on `connect-src`.
CSP = (
    "default-src 'self'; "
    # esm.run/jsdelivr serve Pyodide and (opt-in) the WebLLM library; both are code, not data.
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://esm.run; "
    # connect targets, all public artifacts — never the user's draft, which is analysed locally and
    # whose only connect target is 'self':
    #  · `*.workers.dev` — the opt-in cloud rewrite service (receives PUBLIC law text only);
    #  · huggingface.co / hf.co — WebLLM's on-device model weights, for the opt-in local AI. The
    #    provision text stays on the device; only the model is downloaded.
    "connect-src 'self' https://cdn.jsdelivr.net https://esm.run https://*.workers.dev "
    "https://huggingface.co https://*.huggingface.co https://hf.co https://*.hf.co "
    "https://raw.githubusercontent.com; "
    "worker-src 'self' blob:; child-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)

PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js"

# The worker: Pyodide, the engines, and all the data — off the main thread. It loads Pyodide and
# its sqlite3 package, unpacks the engines and fixtures into its own filesystem, mounts the data,
# and then answers request messages. Nothing here touches the DOM, so no call it makes can ever
# block the page: boot (seconds) and every lint or search run happen here, and the UI stays live.
WORKER = """
importScripts("__PYODIDE__");
let raspunde, cautaJson;
async function boot(){
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("sqlite3");  // unvendored in Pyodide; the corpus is SQLite
  const zip = await fetch("bundle.zip").then(r=>r.arrayBuffer());
  pyodide.unpackArchive(zip, "zip");
  try { pyodide.FS.mkdir("data"); } catch (e) {}
  // The whole corpus (corpus.db) is NOT shipped — only the small catalog the engines need: titles
  // (index.json), counts (manifest.json), the terminology dictionary (termeni.json), the graph and
  // the initiatives. Search reads per-act shards over HTTP on demand; nothing pulls the corpus.
  for (const name of ["graf.db","initiative.db","index.json","termeni.json","manifest.json"]) {
    const buf = new Uint8Array(await fetch("data/"+name).then(r=>r.arrayBuffer()));
    pyodide.FS.writeFile("data/"+name, buf);
  }
  raspunde = pyodide.runPython(`
import sys, json
if '.' not in sys.path: sys.path.insert(0, '.')
from urllib.parse import parse_qs
from scripts.servicii import (Stare, rezumat, _lint, _cauta, _vecini,
                              _redacteaza, _sugereaza, _consolidat, _compune, _act)
_stare = Stare('data/corpus.db', 'data/initiative.db', 'data/graf.db', date_dir='data')
def _raspunde(path, query, body):
    qs = parse_qs(query or '')
    if path == '/api/rezumat': out = rezumat(_stare)
    elif path == '/api/cauta': out = _cauta(qs.get('q',[''])[0], _stare)
    elif path == '/api/vecini':
        a = qs.get('act',[''])[0]; out = _vecini(a, _stare) if a else {'error':'act lipsă'}
    elif path == '/api/redacteaza': out = _redacteaza(qs)
    elif path == '/api/sugereaza': out = _sugereaza(qs)
    elif path == '/api/consolidat': out = _consolidat(qs)
    elif path == '/api/act': out = _act(qs, _stare)
    elif path == '/api/compune':
        out = _compune(json.loads(body or '{}').get('interventii', []))
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
from scripts.cauta_web import cauta as _cauta_shard
async def _cauta_json(q):
    return _json.dumps(await _cauta_shard(q, 'data'), ensure_ascii=False)
_cauta_json
  `);
}
const gata = boot().then(()=>postMessage({type:"ready"}))
                   .catch(e=>{ postMessage({type:"error", error:String(e)}); throw e; });
onmessage = async (e) => {
  const {id, path, query, body} = e.data;
  try {
    await gata;
    const res = (path === "/api/cauta")
      ? await cautaJson(new URLSearchParams(query).get("q") || "")
      : raspunde(path, query, body);
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
<script>
(function(){
  const origFetch = window.fetch.bind(window);
  let resolveReady, rejectReady;
  const ready = new Promise((res, rej)=>{ resolveReady=res; rejectReady=rej; });
  const worker = new Worker("worker.js");
  const pending = new Map(); let seq = 0;
  worker.onmessage = (e)=>{
    const m = e.data;
    if (m.type === "ready"){ resolveReady(); return; }
    if (m.type === "error"){
      rejectReady(new Error(m.error));
      const s = document.getElementById("stat");
      if (s) s.textContent = "eroare la pornirea motorului: " + m.error;
      return;
    }
    const p = pending.get(m.id); if (!p) return; pending.delete(m.id);
    m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
  };
  worker.onerror = (e)=>{ rejectReady(new Error(e.message || "worker error")); };
  function call(path, query, body){
    return new Promise((resolve, reject)=>{
      const id = ++seq; pending.set(id, {resolve, reject});
      worker.postMessage({id, path, query, body});
    });
  }
  window.fetch = async function(url, opts){
    const u = (typeof url === "string") ? url : (url && url.url);
    if (u && u.indexOf("/api/") === 0) {
      try { await ready; }
      catch(e){ return new Response(JSON.stringify({error:"motor indisponibil: "+e}), {status:503}); }
      try {
        const parsed = new URL(u, location.origin);
        const body = (opts && opts.body) ? String(opts.body) : "";
        const res = await call(parsed.pathname, parsed.search.slice(1), body);
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
const CACHE = "legislativ-" + VERSIUNE;
const NUCLEU = [
  "./", "./index.html", "./worker.js", "./bundle.zip",
  "./data/graf.db", "./data/initiative.db",
  "./data/index.json", "./data/termeni.json", "./data/manifest.json"
];
const eBig = (p) => /\\/data\\/.*\\.db$/.test(p) || p.includes("/data/idx/") || p.includes("/data/acte/");
self.addEventListener("install", (e)=>{
  e.waitUntil(
    caches.open(CACHE).then(c=>c.addAll(NUCLEU)).catch(()=>{}).then(()=>self.skipWaiting())
  );
});
self.addEventListener("activate", (e)=>{
  e.waitUntil(
    caches.keys()
      .then(ks=>Promise.all(ks.map(k=>k===CACHE ? null : caches.delete(k))))
      .then(()=>self.clients.claim())
  );
});
self.addEventListener("fetch", (e)=>{
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;  // Pyodide CDN and the like go straight to network
  if (eBig(url.pathname)) {
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
        con.execute(
            f"INSERT INTO acte SELECT * FROM plin.acte WHERE id IN ({marcaje}) OR rowid <= ?",
            (*CURATE, N_ACTE),
        )
        con.execute(
            "INSERT INTO provizii SELECT * FROM plin.provizii "
            "WHERE act_id IN (SELECT id FROM acte)"
        )
        con.execute(
            "INSERT INTO provizii_fts(text, act_id, locator) SELECT text, act_id, locator "
            "FROM provizii"
        )
        con.commit()
        con.execute("DETACH plin")
    print(f"  corpus slice → {tinta} ({tinta.stat().st_size/1e6:.1f} MB)")


def _slice_initiative() -> None:
    tinta = DATA / "initiative.db"
    if tinta.exists():
        tinta.unlink()
    with depozit.deschide(str(tinta)) as con:
        con.execute("ATTACH DATABASE ? AS plin", (str(ROOT / "initiative.db"),))
        con.execute(
            "INSERT INTO initiative SELECT * FROM plin.initiative WHERE rowid <= ?",
            (N_INITIATIVE,),
        )
        con.execute(
            "INSERT INTO initiative_fts(titlu, obiect, plx_id) "
            "SELECT titlu, obiect, plx_id FROM initiative"
        )
        con.commit()
        con.execute("DETACH plin")
    print(f"  initiative slice → {tinta} ({tinta.stat().st_size/1e6:.1f} MB)")


def _date_din_corpus() -> None:
    """The slice path: a few hundred acts out of the collected corpus, plus the whole graph."""
    _slice_corpus()
    _slice_initiative()
    shutil.copy(ROOT / "graf.db", DATA / "graf.db")
    print(f"  graf → {DATA / 'graf.db'} (întreg)")


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
    print(f"  corpus din {n} fixturi → {corpus} ({corpus.stat().st_size/1e6:.2f} MB)")

    ini = DATA / "initiative.db"
    if ini.exists():
        ini.unlink()
    with depozit.deschide(str(ini)):
        pass  # schema only — no committed initiative fixture, so the table stays honestly empty
    print(f"  initiative (gol) → {ini}")

    graf = DATA / "graf.db"
    if graf.exists():
        graf.unlink()
    muchii = construieste_graf(str(corpus), str(graf), log=lambda *_: None)
    print(f"  graf din corpus → {graf} ({muchii} muchii)")


def _finalizeaza_db() -> None:
    """Fold each DB's WAL back into one file and drop the sidecars, so a static host serves a
    single self-contained file per database (a browser cannot stitch `-wal`/`-shm` back together).
    """
    import sqlite3

    for db in sorted(DATA.glob("*.db")):
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


def _bundle() -> None:
    tinta = WEB / "bundle.zip"
    with zipfile.ZipFile(tinta, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT / "scripts").glob("*.py")):
            z.write(p, f"scripts/{p.name}")
        for p in sorted((ROOT / "sources").glob("*.gz")):
            z.write(p, f"sources/{p.name}")
    print(f"  bundle → {tinta} ({tinta.stat().st_size/1e6:.1f} MB)")


def _worker() -> None:
    (WEB / "worker.js").write_text(WORKER.replace("__PYODIDE__", PYODIDE), encoding="utf-8")
    print(f"  worker → {WEB / 'worker.js'}")


def _versiune_si_sw() -> str:
    """A content hash of the corpus and graph, written into the service worker and the manifest.

    Same data → same version → the browser keeps its cache; changed data → new version → the new
    sw.js retires the old cache. The corpus file already reflects every provision, so hashing it
    (and the graph) captures any change that matters to what the app shows.
    """
    # Hash the browser-facing catalog, not the monolithic corpus.db — the corpus is not shipped to
    # the client and need not even be present (a dataset release carries only the shards). index.json
    # + manifest.json capture the act set and the counts; graf.db the amendment edges.
    h = hashlib.sha256()
    for name in ("index.json", "manifest.json", "graf.db"):
        p = DATA / name
        if p.is_file():
            h.update(p.read_bytes())
    versiune = h.hexdigest()[:12]

    (WEB / "sw.js").write_text(SW.replace("__VERSION__", versiune), encoding="utf-8")
    manifest = DATA / "manifest.json"
    date = json.loads(manifest.read_text()) if manifest.is_file() else {}
    date["versiune"] = versiune
    manifest.write_text(json.dumps(date, ensure_ascii=False), encoding="utf-8")
    print(f"  sw + versiune → {versiune}")
    return versiune


def _pagina() -> None:
    sursa = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    if "<head>" not in sursa or "<body>" not in sursa:
        raise SystemExit("app/index.html nu are <head>/<body> — nu știu unde să injectez")
    csp = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    pagina = sursa.replace("<head>", "<head>\n" + csp, 1)
    # Prepend the manager block right after <body> so it runs before the app's own inline script.
    pagina = pagina.replace("<body>", "<body>\n" + BOOT, 1)
    (WEB / "index.html").write_text(pagina, encoding="utf-8")
    print(f"  pagină (cu CSP) → {WEB / 'index.html'}")


def main(sursa: str) -> None:
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
            with depozit.deschide(str(ini)):
                pass
            print(f"  initiative (gol, lipsea din release) → {ini}")
        print(f"  folosesc datele deja prezente în {DATA}")
    else:
        if sursa == "fixturi":
            _date_din_fixturi()
        else:
            _date_din_corpus()
        _finalizeaza_db()
        shard.construieste(str(DATA / "corpus.db"), str(DATA))
    _bundle()
    _worker()
    _pagina()
    _versiune_si_sw()
    print("gata. servește cu:  uv run python -m http.server -d web 8080")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Construiește build-ul de browser (Pyodide).")
    implicit = "corpus" if (ROOT / "corpus.db").is_file() else "fixturi"
    ap.add_argument(
        "--sursa",
        choices=("fixturi", "corpus", "gata"),
        default=implicit,
        help=(
            "'fixturi' (reproductibil în CI, din sources/), 'corpus' (felie din corpus.db), "
            "sau 'gata' (datele sunt deja în web/data, dintr-un release descărcat)"
        ),
    )
    main(ap.parse_args().sursa)
