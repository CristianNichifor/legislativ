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
- `GET /api/vecini?act=` / `GET /api/rezumat` — the connections canvas and the corpus headline.
- `GET /` — the page that drives them.

The contradiction pass is deliberately absent. It needs a model, it is the one output that can be
confidently wrong, and it belongs behind the validator and a clear "experimental" label.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.servicii import (
    Stare,
    _cauta,
    _consolidat,
    _lint,
    _redacteaza,
    _sugereaza,
    _vecini,
    rezumat,
)

APP = Path(__file__).resolve().parent.parent / "app"


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
            elif ruta.path == "/api/vecini":
                act = parse_qs(ruta.query).get("act", [""])[0]
                self._json(_vecini(act, stare) if act else {"error": "act lipsă"})
            elif ruta.path == "/api/redacteaza":
                self._json(_redacteaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/sugereaza":
                self._json(_sugereaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/consolidat":
                self._json(_consolidat(parse_qs(ruta.query)))
            elif ruta.path == "/api/rezumat":
                self._json(rezumat(stare))
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
