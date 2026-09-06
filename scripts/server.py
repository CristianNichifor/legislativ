"""The localhost transport over the services in `scripts/servicii.py`.

`http.server` from the standard library, the corpus in SQLite, the extractors that were built and
measured — nothing here is new logic, only wiring. The request-handling functions live in
`servicii.py` with no transport attached, so the browser build (Pyodide, no server) drives the
exact same functions; this module is one of two thin skins over them, not a place they get
reimplemented.

**Read-only, so it runs while the corpus fills.** Every open is `mode=ro`; the server never
writes, so it coexists with the collectors and answers from more law each time they land a page.

**Endpoints, one question each:**
- `POST /api/lint` — a pasted draft against the law: deadlines, defined terms it talks around,
  pending bills it may duplicate, acts it touches, repealed citations, and provisions since
  consolidated. The deterministic passes, in one answer.
- `GET /api/cauta?q=` — full-text search over every provision, diacritic-insensitive.
- `GET /api/redacteaza` — a structured intent into the mandated Legea 24/2000 phrasing.
- `GET /api/sugereaza?text=` — the legistic form of the line being written. No model, no corpus.
- `GET /api/consolidat[?act=]` — a provision's current wording with each change attributed, or the
  acts available to show. Reads locally synced pages, never a live portal fetch.
- `GET /api/prevedere?act=&loc=` — one provision's stored text, for the citation chips to show a
  target the consolidation view does not list. `gasit=false` where the corpus does not hold it.
- `GET /api/vecini?act=` / `GET /api/rezumat` — the connections canvas and the corpus headline.
- `GET /` — the page that drives them.

The contradiction pass is deliberately absent. It needs a model, it is the one output that can be
confidently wrong, and it belongs behind the validator and a clear "experimental" label.
"""

from __future__ import annotations

import contextlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.servicii import (
    Stare,
    _act,
    _cauta,
    _citari,
    _compune,
    _consolidat,
    _cronologie,
    _dictionar,
    _impact,
    _lint,
    _norma,
    _opinie,
    _opinie_cerere,
    _parseaza,
    _prevedere,
    _redacteaza,
    _regula,
    _sugereaza,
    _supraveghere,
    _termeni,
    _vecini,
    rezumat,
)

APP = Path(__file__).resolve().parent.parent / "app"


def _incalzeste(stare: Stare) -> None:
    """Pay the first request's cost before anyone makes one.

    The passes import their engines lazily and SQLite has a 9 GB file to start reading, so the
    first lint is 4 s and the rest are 285 ms. This is that first lint, on a sentence that finds
    nothing, thrown away. Failures are ignored on purpose: a corpus too incomplete to warm up is
    still a corpus the server should serve, and the passes each report their own gaps.
    """
    with contextlib.suppress(Exception):
        _lint("Articolul 1 Prezenta lege intră în vigoare la 30 de zile de la publicare.", stare)


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
                qs = parse_qs(ruta.query)

                def _int(k):
                    v = qs.get(k, [""])[0]
                    try:
                        return int(v) if v else None
                    except ValueError:
                        return None

                self._json(
                    _cauta(
                        qs.get("q", [""])[0],
                        stare,
                        tip=(qs.get("tip", [""])[0] or None),
                        an_min=_int("an_min"),
                        an_max=_int("an_max"),
                        limita=_int("limita") or 25,
                        offset=_int("offset") or 0,
                    )
                )
            elif ruta.path == "/api/vecini":
                act = parse_qs(ruta.query).get("act", [""])[0]
                self._json(_vecini(act, stare) if act else {"error": "act lipsă"})
            elif ruta.path == "/api/cronologie":
                self._json(_cronologie(parse_qs(ruta.query).get("act", [""])[0], stare))
            elif ruta.path == "/api/citari":
                self._json(_citari(parse_qs(ruta.query).get("act", [""])[0], stare))
            elif ruta.path == "/api/supraveghere":
                self._json(_supraveghere(parse_qs(ruta.query).get("act", [""])[0], stare))
            elif ruta.path == "/api/redacteaza":
                self._json(_redacteaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/sugereaza":
                self._json(_sugereaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/consolidat":
                self._json(_consolidat(parse_qs(ruta.query)))
            elif ruta.path == "/api/prevedere":
                self._json(_prevedere(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/act":
                self._json(_act(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/dictionar":
                self._json(_dictionar(stare))
            elif ruta.path == "/api/rezumat":
                self._json(rezumat(stare))
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            ruta = urlparse(self.path).path
            if ruta not in (
                "/api/lint",
                "/api/opinie",
                "/api/opinie-cerere",
                "/api/compune",
                "/api/parseaza",
                "/api/norma",
                "/api/termeni",
                "/api/regula",
                "/api/impact",
            ):
                self._json({"error": "not found"}, 404)
                return
            lung = int(self.headers.get("Content-Length", 0))
            try:
                cerere = json.loads(self.rfile.read(lung) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "json invalid"}, 400)
                return
            if ruta == "/api/compune":
                self._json(_compune(cerere.get("interventii", [])))
                return
            if ruta == "/api/parseaza":
                self._json(_parseaza(str(cerere.get("text", "")).strip()))
                return
            if ruta == "/api/norma":
                self._json(_norma(str(cerere.get("text", "")).strip()))
                return
            if ruta == "/api/termeni":
                self._json(_termeni(str(cerere.get("text", "")).strip(), stare))
                return
            if ruta == "/api/regula":
                self._json(_regula(str(cerere.get("text", "")).strip()))
                return
            draft = str(cerere.get("draft", "")).strip()
            if not draft:
                self._json({"error": "draft gol"}, 400)
                return
            if ruta == "/api/impact":
                self._json(_impact(draft, stare))
                return
            if ruta == "/api/opinie-cerere":
                self._json(_opinie_cerere(draft, stare))
                return
            if ruta == "/api/opinie":
                # On-device or not at all: `model_local` returns None unless a model is configured
                # on this machine, and `_opinie` reports that as a pass that did not run.
                from scripts.opinie import model_local

                # A reply the caller already obtained (the browser path) is validated as-is;
                # otherwise a model on this machine is asked, if one is configured.
                brut = cerere.get("brut")
                self._json(_opinie(draft, stare, model=None if brut else model_local(), brut=brut))
                return
            self._json(_lint(draft, stare))

        def log_message(self, *a):  # keep the console quiet
            return

    return Handler


def serveste(
    port: int = 8000,
    corpus: str = "corpus.db",
    initiative: str = "initiative.db",
    graf: str = "graf.db",
    deschide_browser: bool = True,
):
    stare = Stare(corpus, initiative, graf)
    server = ThreadingHTTPServer(("127.0.0.1", port), face_handler(stare))
    grafic = "cu graf" if stare.are_graf() else "fără graf"
    url = f"http://127.0.0.1:{port}"

    # One throwaway lint before announcing the port. Measured on the full corpus, the first request
    # costs 4 s and every one after it 285 ms — the difference is module imports done lazily inside
    # the passes and SQLite warming its page cache over a 9 GB file. Paid here it lands on a line
    # that says it is starting; paid on the first request it lands on somebody's first question.
    _incalzeste(stare)
    print(f"legislativ pe {url}  ({len(stare.termeni)} termeni în dicționar, {grafic})")
    print(
        "proiectul lipit nu părăsește această mașină."
    )  # localhost; lint face zero cereri externe
    if deschide_browser:
        # Bound to 127.0.0.1 only, so this is a local tool a researcher opens, not a service.
        # A timer, because serve_forever blocks and the browser should open once it is listening.
        import threading
        import webbrowser

        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\noprit.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--initiative", default="initiative.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument("--fara-browser", action="store_true", help="nu deschide browserul")
    a = ap.parse_args()
    serveste(a.port, a.corpus, a.initiative, a.graf, deschide_browser=not a.fara_browser)
