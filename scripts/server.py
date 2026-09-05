"""A thin local backend over the two engines.

Everything the package can do is a function over a read-only corpus; this exposes three of them
to a browser without adding a dependency or a database server. `http.server` from the standard
library, the corpus in SQLite, the extractors that were built and measured — nothing here is new
logic, only wiring, which is the point: the hard parts are done and tested, and a UI should be a
thin skin over them rather than a place they get reimplemented.

**Read-only, so it runs while the corpus fills.** Every open is `mode=ro`; the server never
writes, so it coexists with the collectors and simply answers from more law each time they land
a page. The one piece of state it holds is the terminology dictionary, built once at startup from
the acts collected so far — rebuilding it per request would read the whole corpus on every
keystroke, and a dictionary that is a few hours stale is a fine trade for a check that answers
instantly.

**Three endpoints, one question each:**
- `POST /api/lint` — a pasted draft against the law: the deadlines it imposes, the defined terms
  it talks around, and the pending bills it may duplicate. The three deterministic passes, in one
  answer.
- `GET /api/cauta?q=` — full-text search over every provision, diacritic-insensitive.
- `GET /` — the page that drives them.

The contradiction pass is deliberately absent. It needs a model, it is the one output that can be
confidently wrong, and it belongs behind the validator and a clear "experimental" label — not in
the first cut of a backend whose value is that everything it returns is checkable.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts import depozit
from scripts.definitii import Termen, jargon
from scripts.dublura import dubluri
from scripts.termene import obligatii

APP = Path(__file__).resolve().parent.parent / "app"


class Stare:
    """What the server holds open: the two corpora and the terminology dictionary.

    Connections are per-request in the handler (SQLite connections are not thread-safe to share),
    but the term dictionary is built once here — it is the only expensive thing, and it changes
    only as slowly as the corpus grows.
    """

    def __init__(self, corpus: str = "corpus.db", initiative: str = "initiative.db"):
        self.corpus = corpus
        self.initiative = initiative
        self.termeni: list[Termen] = self._dictionar()

    # Built from the most recent acts only, not the whole corpus: definitions over a
    # quarter-million acts would take minutes at startup, and the terminology check must answer
    # instantly. The recent N carry the vocabulary a current draft is most likely to talk
    # around; the bound is declared, not hidden, and raising it is config, not an edit.
    def _dictionar(self, limita: int = 800) -> list[Termen]:
        from scripts.analiza import termeni_corpus

        try:
            with depozit.deschide(self.corpus, readonly=True) as con:
                return termeni_corpus(con, limita=limita)
        except Exception:
            return []


def _lint(draft: str, stare: Stare) -> dict:
    """The three deterministic passes over a pasted draft, each carrying its own provenance."""
    obs = obligatii(draft)
    deadlines = [
        {
            "text": o.text[:300],
            "instrument": o.tip_asteptat,
            "termen_zile": o.termen_zile,
            "ancora": o.ancora,
            "institutie": o.institutie_text or o.institutie,
        }
        for o in obs
    ]
    termen_hits = [
        {
            "fragment": a.fragment,
            "termen_definit": a.termen.termen,
            "regula": a.regula,
            "explicatie": a.explicatie,
        }
        for a in jargon(draft, stare.termeni)
    ]
    with depozit.deschide(stare.initiative, readonly=True) as con:
        dup = [
            {
                "plx_id": p.plx_id,
                "senat_id": p.senat_id,
                "titlu": p.titlu,
                "stadiu": p.stadiu,
                "motiv": p.motiv,
                "incredere": p.increderea,
            }
            for p in dubluri(draft, con)[:10]
        ]
    return {"deadlines": deadlines, "terminology": termen_hits, "duplicates": dup}


def _cauta(q: str, stare: Stare) -> dict:
    if not q.strip():
        return {"results": []}
    with depozit.deschide(stare.corpus, readonly=True) as con:
        rows = depozit.cauta(con, q, 25)
    return {"results": [dict(r) for r in rows]}


def face_handler(stare: Stare):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj: dict, code: int = 200) -> None:
            corp = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corp)))
            self.end_headers()
            self.wfile.write(corp)

        def _fisier(self, nume: str, tip: str) -> None:
            cale = APP / nume
            if not cale.is_file():
                self._json({"error": "not found"}, 404)
                return
            corp = cale.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", tip)
            self.send_header("Content-Length", str(len(corp)))
            self.end_headers()
            self.wfile.write(corp)

        def do_GET(self) -> None:  # noqa: N802
            ruta = urlparse(self.path)
            if ruta.path == "/":
                self._fisier("index.html", "text/html; charset=utf-8")
            elif ruta.path == "/api/cauta":
                q = parse_qs(ruta.query).get("q", [""])[0]
                self._json(_cauta(q, stare))
            elif ruta.path == "/api/rezumat":
                with depozit.deschide(stare.corpus, readonly=True) as con:
                    r = depozit.rezumat(con)
                with depozit.deschide(stare.initiative, readonly=True) as con:
                    r["initiative"] = depozit.rezumat(con)["initiative"]
                self._json(r)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/lint":
                self._json({"error": "not found"}, 404)
                return
            lung = int(self.headers.get("Content-Length", 0))
            try:
                cerere = json.loads(self.rfile.read(lung) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "json invalid"}, 400)
                return
            draft = str(cerere.get("draft", "")).strip()
            if not draft:
                self._json({"error": "draft gol"}, 400)
                return
            self._json(_lint(draft, stare))

        def log_message(self, *a):  # keep the console quiet
            return

    return Handler


def serveste(port: int = 8000, corpus: str = "corpus.db", initiative: str = "initiative.db"):
    stare = Stare(corpus, initiative)
    server = ThreadingHTTPServer(("127.0.0.1", port), face_handler(stare))
    print(f"legislativ pe http://127.0.0.1:{port}  ({len(stare.termeni)} termeni în dicționar)")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--initiative", default="initiative.db")
    a = ap.parse_args()
    serveste(a.port, a.corpus, a.initiative)
