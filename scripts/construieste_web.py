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

**Nothing the user types leaves the tab.** The only network calls are Pyodide (from its CDN) and
these static data files (public law) from the app's own origin. The draft is analysed in-process.

Standard library only. Run: `uv run python -m scripts.construieste_web`.
"""
# ruff: noqa: E501  — this module embeds an HTML/JS boot blob where line length is not meaningful.

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from scripts import depozit

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = WEB / "data"

# Acts the demo cites, kept in the slice no matter where they fall in the corpus, plus the first
# N by insertion order so search has a body to work against.
CURATE = ["lege-98-2016", "lege-99-2016", "lege-100-2016", "lege-24-2000", "oug-57-2019"]
N_ACTE = 200
N_INITIATIVE = 300

PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js"

# The one script the browser build adds. It runs before the app's own inline script (document
# order), so `window.fetch` is already redirected by the time the page calls `/api/…`. Every API
# call is answered in-process by `scripts.servicii`; only Pyodide and the static data cross the
# network, never the draft.
BOOT = """
<script src="__PYODIDE__"></script>
<script>
(function(){
  const origFetch = window.fetch.bind(window);
  let resolveReady, rejectReady;
  const pyReady = new Promise((res, rej)=>{ resolveReady=res; rejectReady=rej; });
  window.fetch = async function(url, opts){
    const u = (typeof url === "string") ? url : (url && url.url);
    if (u && u.indexOf("/api/") === 0) {
      let py;
      try { py = await pyReady; }
      catch(e){ return new Response(JSON.stringify({error:"Pyodide indisponibil: "+e}), {status:503}); }
      try {
        const parsed = new URL(u, location.origin);
        const body = (opts && opts.body) ? String(opts.body) : "";
        const res = py.raspunde(parsed.pathname, parsed.search.slice(1), body);
        return new Response(res, {status:200, headers:{"Content-Type":"application/json; charset=utf-8"}});
      } catch(e){
        return new Response(JSON.stringify({error:String(e)}), {status:500});
      }
    }
    return origFetch(url, opts);
  };
  async function boot(){
    try {
      const pyodide = await loadPyodide();
      // sqlite3 is unvendored in Pyodide — the corpus is SQLite, so load it before the engines.
      await pyodide.loadPackage("sqlite3");
      const zip = await origFetch("bundle.zip").then(r=>r.arrayBuffer());
      pyodide.unpackArchive(zip, "zip");
      for (const name of ["corpus.db","initiative.db","graf.db"]) {
        const buf = new Uint8Array(await origFetch("data/"+name).then(r=>r.arrayBuffer()));
        pyodide.FS.writeFile(name, buf);
      }
      const raspunde = pyodide.runPython(`
import sys, json
if '.' not in sys.path: sys.path.insert(0, '.')
from urllib.parse import parse_qs
from scripts.servicii import (Stare, rezumat, _lint, _cauta, _vecini,
                              _redacteaza, _sugereaza, _consolidat)
_stare = Stare('corpus.db', 'initiative.db', 'graf.db')
def _raspunde(path, query, body):
    qs = parse_qs(query or '')
    if path == '/api/rezumat': out = rezumat(_stare)
    elif path == '/api/cauta': out = _cauta(qs.get('q',[''])[0], _stare)
    elif path == '/api/vecini':
        a = qs.get('act',[''])[0]; out = _vecini(a, _stare) if a else {'error':'act lipsă'}
    elif path == '/api/redacteaza': out = _redacteaza(qs)
    elif path == '/api/sugereaza': out = _sugereaza(qs)
    elif path == '/api/consolidat': out = _consolidat(qs)
    elif path == '/api/lint':
        draft = (json.loads(body or '{}').get('draft') or '').strip()
        out = _lint(draft, _stare) if draft else {'error':'draft gol'}
    else: out = {'error':'not found'}
    return json.dumps(out, ensure_ascii=False)
_raspunde
      `);
      resolveReady({ raspunde: (p,q,b)=>raspunde(p,q,b) });
    } catch(e){
      console.error(e);
      const s = document.getElementById("stat");
      if (s) s.textContent = "eroare la pornirea motorului în browser: " + e;
      rejectReady(e);
    }
  }
  boot();
})();
</script>
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


def _bundle() -> None:
    tinta = WEB / "bundle.zip"
    with zipfile.ZipFile(tinta, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT / "scripts").glob("*.py")):
            z.write(p, f"scripts/{p.name}")
        for p in sorted((ROOT / "sources").glob("*.gz")):
            z.write(p, f"sources/{p.name}")
    print(f"  bundle → {tinta} ({tinta.stat().st_size/1e6:.1f} MB)")


def _pagina() -> None:
    sursa = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    boot = BOOT.replace("__PYODIDE__", PYODIDE)
    # Prepend the boot block right after <body> so it runs before the app's own inline script.
    if "<body>" not in sursa:
        raise SystemExit("app/index.html nu are <body> — nu știu unde să inserez bootstrap-ul")
    pagina = sursa.replace("<body>", "<body>\n" + boot, 1)
    (WEB / "index.html").write_text(pagina, encoding="utf-8")
    print(f"  pagină → {WEB / 'index.html'}")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    print("construiesc web/ …")
    _slice_corpus()
    _slice_initiative()
    shutil.copy(ROOT / "graf.db", DATA / "graf.db")
    print(f"  graf → {DATA / 'graf.db'} (întreg)")
    _bundle()
    _pagina()
    print("gata. servește cu:  python -m http.server -d web 8080")


if __name__ == "__main__":
    main()
