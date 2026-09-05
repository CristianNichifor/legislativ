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
import shutil
import zipfile
from pathlib import Path

from scripts import depozit
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
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "worker-src blob:; child-src blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)

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


def _pagina() -> None:
    sursa = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    if "<head>" not in sursa or "<body>" not in sursa:
        raise SystemExit("app/index.html nu are <head>/<body> — nu știu unde să injectez")
    csp = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    boot = BOOT.replace("__PYODIDE__", PYODIDE)
    pagina = sursa.replace("<head>", "<head>\n" + csp, 1)
    # Prepend the boot block right after <body> so it runs before the app's own inline script.
    pagina = pagina.replace("<body>", "<body>\n" + boot, 1)
    (WEB / "index.html").write_text(pagina, encoding="utf-8")
    print(f"  pagină (cu CSP) → {WEB / 'index.html'}")


def main(sursa: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"construiesc web/ (sursă: {sursa}) …")
    if sursa == "fixturi":
        _date_din_fixturi()
    else:
        _date_din_corpus()
    _finalizeaza_db()
    _bundle()
    _pagina()
    print("gata. servește cu:  uv run python -m http.server -d web 8080")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Construiește build-ul de browser (Pyodide).")
    implicit = "corpus" if (ROOT / "corpus.db").is_file() else "fixturi"
    ap.add_argument(
        "--sursa",
        choices=("fixturi", "corpus"),
        default=implicit,
        help="'fixturi' (reproductibil în CI, din sources/) sau 'corpus' (felie din corpus.db)",
    )
    main(ap.parse_args().sursa)
