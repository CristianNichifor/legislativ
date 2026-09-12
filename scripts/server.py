"""The localhost transport over the services in `scripts/servicii.py`.

`http.server` from the standard library, the corpus in SQLite, the extractors that were built and
measured — nothing here is new logic, only wiring. The request-handling functions live in
`servicii.py` with no transport attached, so the browser build (Pyodide, no server) drives the
exact same functions; this module is one of two thin skins over them, not a place they get
reimplemented.

Corpus queries are read-only. User-triggered official document imports write immutable snapshots
to a separate `initiative.documente.db` beside the initiative database.

**Endpoints, one question each:**
- `POST /api/lint` — a pasted draft against the law: deadlines, defined terms it talks around,
  pending bills it may duplicate, acts it touches, repealed citations, and provisions since
  consolidated. The deterministic passes, in one answer.
- `GET /api/cauta?q=` — full-text search over every provision, diacritic-insensitive.
- `GET /api/redacteaza` — a structured intent into the mandated Legea 24/2000 phrasing.
- `GET /api/sugereaza?text=` — the legistic form of the line being written. No model, no corpus.
- `GET /api/consolidat[?act=]` — a provision's current wording with each change attributed, or the
  acts available to show. Reads locally synced pages, never a live portal fetch.
- `GET /api/cine-citeaza?act=&loc=` — what depends on a provision: which article of which act
  cites it, and the act's load-bearing provisions by how many sources rely on each.
- `GET /api/deputati[?q=|?idm=&leg=&camera=]` — the parliamentary groups, a name search, or one
  member's record. Identity is (legislature, chamber, id); anything less merges people.
- `GET /api/parcurs?plx=` — one bill's passage: sponsors, timeline, avize, recorded votes. A step
  that was debated carries the transcript's locator, `{ids, idm}` — the sitting and the item.
- `GET /api/lifecycle-proiecte[?q=&limit=&offset=&stale_days=]` — project lifecycle/status feed
  from local parliamentary metadata, including stale, unavailable and unknown-stage states.
- `GET /api/stenograma?ids=&idm=` — that debate, speech by speech, each speaker carrying the
  (legislature, chamber, id) their profile is keyed on. `gasit=false` where it has not been read.
- `POST /api/importa` — an uploaded `.docx`, `.md` or `.txt` into the editor's block tree. Base64
  in JSON, so the browser build calls the same function with no transport at all. PDF is refused
  with a way forward: reading one needs a text-extraction dependency this package does not take.
- `POST /api/docx` — the draft as a `.docx`, base64 for the same reason. PDF export needs no
  endpoint: the page carries a print stylesheet and the browser's own "Save as PDF".
- `GET /api/rol?idv=` — who voted which way in one division, grouped by parliamentary group. The
  tally on a Fișa is the room's answer and nobody's; this is the one a voter can act on.
- `GET /api/dezbateri?q=` — full-text over what was said in the Chamber, not over bill titles.
- `GET /api/domenii[?emitent=&tip=]` — the corpus grouped by the body that issued it, or one
  body's acts. By issuer and not by subject: the portal publishes no classification of any kind,
  and inventing one would present a guess as something read.
- `GET /api/matrice[?tip=&rang=&domeniu=&problema=&sort=]` — corpus-wide risk matrix by issuing
  body: gaps, unrepaired constitutional hits, pending initiatives and amendment pressure, each
  derived from existing registers rather than a model.
- `GET /api/matrice-acte?emitent=&tip=&rang=&domeniu=` — the concrete acts behind one matrix row,
  narrowed by the same filters.
- `GET /api/matrice-dosar?emitent=&tip=&rang=&domeniu=&problema=` — a printable work dossier for
  one matrix row.
- `GET /api/fisa-act?act=` — one law workbench: local gap/CCR/project/EU signals and next actions.
- `POST /api/ue` — candidate EU provisions from the local CELEX database (`eu.db`), with source
  links and an explicit retrieval-not-verdict limitation.
- `GET /api/ue/acoperire` — which CELEX ids cited by local laws/initiatives are already imported.
- `GET /api/ue/import-queue` — missing cited CELEX ids, with local references and Cellar import
  guidance.
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
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse

from scripts.servicii import (
    Stare,
    _acoperire_ue,
    _act,
    _cauta,
    _cine_citeaza,
    _citari,
    _compune,
    _conflicte_proiecte,
    _consolidat,
    _cronologie,
    _deputati,
    _dezbateri,
    _dictionar,
    _docx,
    _domenii,
    _fisa_act,
    _impact,
    _import_queue_ue,
    _importa,
    _lint,
    _matrice,
    _matrice_acte,
    _matrice_contradictii,
    _matrice_dosar,
    _matrice_proiecte,
    _norma,
    _opinie,
    _opinie_cerere,
    _parcurs,
    _parseaza,
    _prevedere,
    _redacteaza,
    _regula,
    _rol,
    _stenograma,
    _sugereaza,
    _supraveghere,
    _termeni,
    _ue,
    _vecini,
    rezumat,
)

APP = Path(__file__).resolve().parent.parent / "app"
# The largest request body this server will read into memory: a `.docx` at `fisiere.MAX_INCARCARE`
# plus the third that base64 adds, plus room for the rest of the JSON.
MAX_CERERE = 30 * 1024 * 1024
MAX_DATE_CERERE = 4096
ASSETS = {
    "/dataset-updates.js": ("dataset-updates.js", "text/javascript; charset=utf-8"),
    "/browser-workspace.js": ("browser-workspace.js", "text/javascript; charset=utf-8"),
    **{
        f"/fonts/{name}.woff2": (f"fonts/{name}.woff2", "font/woff2")
        for name in (
            "aileron-400",
            "aileron-400i",
            "aileron-600",
            "aileron-700",
            "plex-mono-400",
            "plex-mono-600",
            "spectral-400",
            "spectral-400i",
            "spectral-600",
            "spectral-700",
        )
    },
}


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind numeric loopback without the stdlib HTTPServer reverse-DNS lookup."""

    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def _incalzeste(stare: Stare) -> None:
    """Pay the first request's cost before anyone makes one.

    The passes import their engines lazily and SQLite has a 9 GB file to start reading, so the
    first lint is 4 s and the rest are 285 ms. This is that first lint, on a sentence that finds
    nothing, thrown away. Failures are ignored on purpose: a corpus too incomplete to warm up is
    still a corpus the server should serve, and the passes each report their own gaps.
    """
    with contextlib.suppress(Exception):
        _lint("Articolul 1 Prezenta lege intră în vigoare la 30 de zile de la publicare.", stare)


def face_handler(stare: Stare, *, runtime=None):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            if runtime is not None:
                self.connection.settimeout(30)

        def _dosare_permis(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if runtime is not None and (
                len(self.headers.get_all("Host", [])) != 1
                or len(self.headers.get_all("Origin", [])) > 1
            ):
                self._json({"error": "Origine nepermisa."}, 403)
                return False
            if self.headers.get("Host") not in hosts or (
                origin is not None and origin not in {"http://" + host for host in hosts}
            ):
                self._json({"error": "Origine nepermisă."}, 403)
                return False
            return True

        def _json(self, obj: dict, code: int = 200) -> None:
            corp = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corp)))
            if urlparse(self.path).path.startswith(
                (
                    "/api/dosare",
                    "/api/lifecycle-proiecte",
                    "/api/acoperire-surse",
                    "/api/surse-proiecte",
                    "/api/ue/surse",
                    "/api/date",
                )
            ):
                self.send_header("Cache-Control", "no-store")
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

        def _dispatch(self, method):
            if runtime is None:
                method(stare)
                return
            # Each complete operation, including private writes and response serialization,
            # sees exactly one state. Activation uses the same reentrant lock.
            with runtime.manager.runtime_lock:
                if not self._dosare_permis():
                    return
                current = runtime.manager.current_state
                try:
                    if urlparse(self.path).path == "/api/date":
                        self._date()
                        return
                    method(current)
                except TimeoutError:
                    self.close_connection = True
                    self._json({"error": "Cererea a expirat."}, 408)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Datele locale nu sunt disponibile."}, 503)
                except Exception:
                    self._json({"error": "Eroare interna a aplicatiei locale."}, 500)

        def _date(self):
            if self.command == "GET":
                try:
                    self._json(runtime.manager.status())
                except (ValueError, OSError) as exc:
                    self._json({"error": str(exc)}, 503)
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                self._json({"error": "Content-Length unic este necesar."}, 400)
                return
            if not lengths[0].isascii() or not lengths[0].isdecimal():
                self._json({"error": "Content-Length invalid."}, 400)
                return
            length = int(lengths[0])
            if length > MAX_DATE_CERERE:
                self._json({"error": "Cerere prea mare."}, 413)
                return
            if self.headers.get_content_type() != "application/json":
                self._json({"error": "Content-Type trebuie sa fie application/json."}, 415)
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._json({"error": "Cerere incompleta."}, 400)
                return
            try:
                body = json.loads(body)
            except (ValueError, UnicodeError, RecursionError):
                self._json({"error": "JSON invalid."}, 400)
                return
            from scripts.date_locale import CommittedWriteError
            from scripts.local_runtime import DatasetConflict

            try:
                self._json(runtime.command(body))
            except DatasetConflict as exc:
                self._json({"error": str(exc)}, 409)
            except CommittedWriteError as exc:
                self._json(
                    {"error": str(exc), "committed": True, "active": runtime.manager.active()}, 503
                )

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch(self._get)

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch(self._post)

        def _get(self, stare) -> None:
            ruta = urlparse(self.path)
            if ruta.path == "/":
                self._fisier("index.html", "text/html; charset=utf-8")
            elif ruta.path in ASSETS:
                self._fisier(*ASSETS[ruta.path])
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
            elif ruta.path == "/api/fisa-act":
                self._json(_fisa_act(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/redacteaza":
                self._json(_redacteaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/sugereaza":
                self._json(_sugereaza(parse_qs(ruta.query)))
            elif ruta.path == "/api/consolidat":
                self._json(_consolidat(parse_qs(ruta.query)))
            elif ruta.path == "/api/prevedere":
                self._json(_prevedere(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/cine-citeaza":
                self._json(_cine_citeaza(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/deputati":
                self._json(_deputati(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/parcurs":
                self._json(_parcurs(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/lifecycle-proiecte":
                from scripts.lifecycle import project_lifecycle_summary

                qs = parse_qs(ruta.query)
                try:
                    self._json(
                        project_lifecycle_summary(
                            stare,
                            query=qs.get("q", [""])[0],
                            limit=int(qs.get("limit", ["50"])[0] or 50),
                            offset=int(qs.get("offset", ["0"])[0] or 0),
                            stale_days=int(qs.get("stale_days", ["30"])[0] or 30),
                        )
                    )
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
            elif ruta.path == "/api/acoperire-surse":
                from scripts.acoperire_surse import raport

                qs = parse_qs(ruta.query)
                try:
                    self._json(raport(stare, stale_days=int(qs.get("stale_days", ["30"])[0] or 30)))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
            elif ruta.path == "/api/stenograma":
                self._json(_stenograma(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/rol":
                self._json(_rol(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/dezbateri":
                self._json(_dezbateri(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/domenii":
                self._json(_domenii(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/matrice":
                self._json(_matrice(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/matrice-acte":
                self._json(_matrice_acte(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/matrice-contradictii":
                self._json(_matrice_contradictii(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/matrice-dosar":
                self._json(_matrice_dosar(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/matrice-proiecte":
                self._json(_matrice_proiecte(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/documente-proiect":
                from scripts.documente_proiecte import lista

                try:
                    self._json(lista(stare, parse_qs(ruta.query).get("plx", [""])[0]))
                except (OSError, ValueError, sqlite3.Error) as exc:
                    self._json({"error": str(exc)}, 400)
            elif ruta.path == "/api/act":
                self._json(_act(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/ue/acoperire":
                self._json(_acoperire_ue(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/ue/import-queue":
                self._json(_import_queue_ue(parse_qs(ruta.query), stare))
            elif ruta.path == "/api/ue/surse":
                from scripts.achizitii_ue import detaliu

                if not self._dosare_permis():
                    return
                qs = parse_qs(ruta.query)
                try:
                    self._json(
                        detaliu(
                            stare,
                            qs.get("celex", [""])[0],
                            offset=int(qs.get("offset", ["0"])[0]),
                            snapshot_id=qs.get("instantanee", [None])[0],
                        )
                    )
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error, TypeError, KeyError, AttributeError):
                    self._json({"error": "Sursa UE locala nu este disponibila."}, 503)
            elif ruta.path == "/api/dictionar":
                self._json(_dictionar(stare))
            elif ruta.path == "/api/rezumat":
                self._json(rezumat(stare))
            elif ruta.path == "/api/inventar-surse":
                from scripts.servicii import _inventar_surse

                self._json(_inventar_surse(stare))
            elif ruta.path == "/api/registru-surse":
                from scripts.source_registry import lista

                if not self._dosare_permis():
                    return
                try:
                    self._json(lista(stare, parse_qs(ruta.query)))
                except (ValueError, OSError, sqlite3.Error):
                    self._json({"error": "Registrul surselor nu este disponibil."}, 503)
            elif ruta.path == "/api/surse-proiecte":
                from scripts import achizitii_proiecte

                if not self._dosare_permis():
                    return
                qs = parse_qs(ruta.query)
                try:
                    plx = qs.get("plx", [""])[0]
                    if plx and "versiune" in qs:
                        from scripts.documente_proiecte import citeste

                        out = citeste(stare, plx, qs["versiune"][0])
                    elif plx:
                        out = achizitii_proiecte.detaliu(stare, plx)
                    else:
                        out = achizitii_proiecte.lista(
                            stare, qs.get("q", [""])[0], int(qs.get("offset", ["0"])[0])
                        )
                    self._json(out)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Sursele locale nu sunt disponibile."}, 503)
            elif ruta.path in (
                "/api/dosare",
                "/api/dosare/metadate",
                "/api/dosare/ciorne",
                "/api/dosare/rulari",
                "/api/dosare/revizuiri",
                "/api/dosare/dovezi",
                "/api/dosare/verificari",
                "/api/dosare/afectate-proiect",
                "/api/dosare/coada",
                "/api/dosare/coada-ue",
                "/api/dosare/context",
                "/api/dosare/note",
                "/api/dosare/propuneri",
                "/api/dosare/propuneri/analize",
                "/api/dosare/propuneri/surse",
                "/api/dosare/propuneri/legaturi-ue",
                "/api/dosare/propuneri/legaturi-ue/obligatii",
            ):
                from scripts import dosare

                if not self._dosare_permis():
                    return
                try:
                    path = dosare.cale(stare)
                    qs = parse_qs(ruta.query)
                    ident = qs.get("id", [None])[0]
                    if ruta.path == "/api/dosare/propuneri/surse":
                        from scripts.surse_propuneri import citeste_cerere

                        out = citeste_cerere(stare, qs)
                    elif ruta.path == "/api/dosare/metadate":
                        out = dosare.metadata(path, ident)
                    elif ruta.path == "/api/dosare/ciorne":
                        out = (
                            dosare.citeste_ciorna(path, ident)
                            if ident
                            else dosare.lista_ciorne(path, int(qs.get("offset", ["0"])[0]))
                        )
                    elif ruta.path == "/api/dosare/propuneri/legaturi-ue/obligatii":
                        from scripts.legaturi_ue import obligatii

                        out = obligatii(
                            stare,
                            qs.get("celex", [None])[0],
                            qs.get("instantanee", [""])[0],
                            int(qs.get("offset", ["0"])[0]),
                        )
                    elif ruta.path == "/api/dosare/propuneri/legaturi-ue":
                        from scripts.legaturi_ue_store import citeste_cerere

                        out = citeste_cerere(path, qs)
                    elif ruta.path == "/api/dosare/propuneri/analize":
                        from scripts.analize_propuneri import citeste_cerere

                        out = citeste_cerere(path, qs)
                    elif ruta.path == "/api/dosare/propuneri":
                        from scripts.propuneri import citeste_cerere

                        out = citeste_cerere(path, qs)
                    elif ruta.path == "/api/dosare/context":
                        from scripts.revizuiri import context_istoric

                        out = context_istoric(
                            path,
                            ident,
                            qs.get("rulare_id", [None])[0],
                            qs.get("constatare_id", [None])[0],
                            qs.get("tinta", [None])[0],
                            int(qs.get("offset", ["0"])[0]),
                        )
                    elif ruta.path == "/api/dosare/verificari":
                        from scripts.verificari_dovezi import istoric

                        out = istoric(
                            path,
                            ident,
                            qs.get("rulare_id", [None])[0],
                            int(qs.get("offset", ["0"])[0]),
                            qs.get("verificare_id", [None])[0],
                        )
                    elif ruta.path == "/api/dosare/afectate-proiect":
                        out = dosare.rulari_afectate_proiect(
                            path,
                            qs.get("proiect", [""])[0],
                            int(qs.get("offset", ["0"])[0]),
                        )
                    elif ruta.path == "/api/dosare/coada-ue":
                        from scripts.coada_ue import lista

                        out = lista(
                            path, int(qs.get("offset", ["0"])[0]), qs.get("stare", ["toate"])[0]
                        )
                    elif ruta.path == "/api/dosare/coada":
                        from scripts.verificari_dovezi import coada

                        out = coada(
                            path, int(qs.get("offset", ["0"])[0]), qs.get("stare", ["toate"])[0]
                        )
                    elif ruta.path == "/api/dosare/note":
                        from scripts import note_manuale

                        note_id = qs.get("note_id", [None])[0]
                        out = (
                            note_manuale.citeste(path, ident, note_id)
                            if note_id
                            else note_manuale.lista(
                                path,
                                ident,
                                int(qs.get("offset", ["0"])[0]),
                                qs.get("status", [None])[0],
                            )
                        )
                    elif ruta.path == "/api/dosare/dovezi":
                        from scripts.dependente_dovezi import verifica

                        out = verifica(stare, ident, qs.get("rulare_id", [None])[0])
                    elif ruta.path == "/api/dosare/revizuiri":
                        from scripts.revizuiri import istoric, lista

                        run_id = qs.get("rulare_id", [None])[0]
                        if "constatare_id" in qs:
                            out = istoric(
                                path,
                                ident,
                                run_id,
                                qs["constatare_id"][0],
                                int(qs.get("offset", ["0"])[0]),
                            )
                        else:
                            out = lista(path, ident, run_id)
                    elif ruta.path == "/api/dosare/rulari":
                        out = dosare.rulari(path, ident, qs.get("rulare_id", [None])[0])
                    elif ident:
                        out = dosare.citeste(path, ident)
                    else:
                        out = dosare.lista(
                            path, int(qs.get("offset", ["0"])[0]), qs.get("stare", ["active"])[0]
                        )
                    self._json(out)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Depozitul de dosare nu este disponibil."}, 503)
            else:
                self._json({"error": "not found"}, 404)

        def _post(self, stare) -> None:
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
                "/api/ue",
                "/api/importa",
                "/api/docx",
                "/api/conflicte-proiecte",
                "/api/importa-proiect",
                "/api/diferente-versiuni",
                "/api/actualizare-proiect",
                "/api/surse-proiecte",
                "/api/ue/surse",
                "/api/registru-surse",
                "/api/dosare",
                "/api/dosare/metadate",
                "/api/dosare/ciorne",
                "/api/dosare/rulari",
                "/api/dosare/revizuiri",
                "/api/dosare/verificari",
                "/api/dosare/context",
                "/api/dosare/note",
                "/api/dosare/propuneri",
                "/api/dosare/propuneri/previzualizare",
                "/api/dosare/propuneri/analize",
                "/api/dosare/propuneri/legaturi-ue",
                "/api/dosare/propuneri/legaturi-ue/previzualizare",
            ):
                self._json({"error": "not found"}, 404)
                return
            # Bounded before it is read, not after. `Content-Length` is a number the client
            # chooses, and `rfile.read(n)` will happily allocate whatever it says — so a request
            # that claims a gigabyte costs a gigabyte before any handler decides it is nonsense.
            # 30 MB is a `.docx` at the import ceiling plus its base64 overhead.
            try:
                lung = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._json({"error": "content-length invalid"}, 400)
                return
            if lung < 0:
                self._json({"error": "content-length invalid"}, 400)
                return
            if lung > (
                210000
                if ruta == "/api/dosare/ciorne"
                else 80000
                if ruta in ("/api/dosare/propuneri", "/api/dosare/propuneri/previzualizare")
                else 16000
                if ruta.startswith(
                    ("/api/dosare", "/api/surse-proiecte", "/api/ue/surse", "/api/registru-surse")
                )
                else MAX_CERERE
            ):
                self._json({"error": "cerere prea mare"}, 413)
                return
            try:
                cerere = json.loads(self.rfile.read(lung) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json({"error": "json invalid"}, 400)
                return
            if not isinstance(cerere, dict):
                self._json({"error": "cererea trebuie sa fie un obiect JSON"}, 400)
                return
            if ruta == "/api/ue/surse":
                from scripts.achizitii_ue import importa

                if not self._dosare_permis():
                    return
                try:
                    self._json(importa(stare, cerere))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Sursa UE locala nu este disponibila."}, 503)
                return
            if ruta == "/api/surse-proiecte":
                from scripts.achizitii_proiecte import executa

                if not self._dosare_permis():
                    return
                try:
                    self._json(executa(stare, cerere))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Sursele locale nu sunt disponibile."}, 503)
                return
            if ruta == "/api/registru-surse":
                from scripts.source_registry import executa

                if not self._dosare_permis():
                    return
                try:
                    self._json(executa(stare, cerere))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Registrul surselor nu este disponibil."}, 503)
                return
            if ruta in (
                "/api/dosare",
                "/api/dosare/metadate",
                "/api/dosare/ciorne",
                "/api/dosare/rulari",
                "/api/dosare/revizuiri",
                "/api/dosare/verificari",
                "/api/dosare/context",
                "/api/dosare/note",
                "/api/dosare/propuneri",
                "/api/dosare/propuneri/previzualizare",
                "/api/dosare/propuneri/analize",
                "/api/dosare/propuneri/legaturi-ue",
                "/api/dosare/propuneri/legaturi-ue/previzualizare",
            ):
                from scripts import dosare

                if not self._dosare_permis():
                    return
                try:
                    path = dosare.cale(stare)
                    if ruta == "/api/dosare/metadate":
                        out = dosare.modifica(path, cerere)
                    elif ruta == "/api/dosare/ciorne":
                        out = dosare.salveaza_ciorna(path, cerere)
                    elif ruta == "/api/dosare/propuneri/legaturi-ue/previzualizare":
                        from scripts.legaturi_ue import preview

                        out = preview(stare, cerere)
                    elif ruta == "/api/dosare/propuneri/legaturi-ue":
                        from scripts.legaturi_ue_store import salveaza

                        out = salveaza(stare, cerere)
                    elif ruta == "/api/dosare/propuneri/analize":
                        from scripts.analize_propuneri import salveaza

                        out = salveaza(stare, cerere)
                    elif ruta == "/api/dosare/propuneri/previzualizare":
                        from scripts.propuneri import previzualizeaza

                        out = previzualizeaza(stare, cerere)
                    elif ruta == "/api/dosare/propuneri":
                        from scripts.propuneri import salveaza

                        out = salveaza(path, cerere, stare)
                    elif ruta == "/api/dosare/context":
                        from scripts.revizuiri import context_salveaza

                        out = context_salveaza(path, cerere)
                    elif ruta == "/api/dosare/note":
                        from scripts.note_manuale import salveaza

                        out = salveaza(path, cerere)
                    elif ruta == "/api/dosare/verificari":
                        from scripts.verificari_dovezi import salveaza

                        out = salveaza(stare, cerere)
                    elif ruta == "/api/dosare/revizuiri":
                        from scripts.revizuiri import salveaza

                        out = salveaza(path, cerere)
                    elif ruta == "/api/dosare":
                        out = dosare.creeaza(path, cerere)
                    else:
                        out = dosare.salveaza_rulare(stare, cerere)
                    self._json(out)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                except (OSError, sqlite3.Error):
                    self._json({"error": "Depozitul de dosare nu este disponibil."}, 503)
                return
            if ruta in (
                "/api/importa-proiect",
                "/api/diferente-versiuni",
                "/api/actualizare-proiect",
            ):
                from scripts.documente_proiecte import (
                    citeste,
                    diferente,
                    importa,
                    verifica_actualizari,
                )

                origin = self.headers.get("Origin")
                allowed = {
                    f"http://127.0.0.1:{self.server.server_port}",
                    f"http://localhost:{self.server.server_port}",
                }
                if origin and origin not in allowed:
                    self._json({"error": "Origine nepermisă."}, 403)
                    return
                if not isinstance(cerere, dict) or not isinstance(cerere.get("plx"), str):
                    self._json({"error": "Cerere invalidă."}, 400)
                    return
                try:
                    if ruta == "/api/diferente-versiuni":
                        if not all(isinstance(cerere.get(k), str) for k in ("inainte", "dupa")):
                            raise ValueError("Selectează două versiuni.")
                        out = diferente(stare, cerere["plx"], cerere["inainte"], cerere["dupa"])
                    elif ruta == "/api/actualizare-proiect":
                        if not isinstance(cerere.get("versiune"), str):
                            raise ValueError("Selectează o versiune importată.")
                        out = verifica_actualizari(stare, cerere["plx"], cerere["versiune"])
                    elif isinstance(cerere.get("versiune"), str):
                        out = citeste(stare, cerere["plx"], cerere["versiune"])
                    else:
                        out = importa(stare, cerere["plx"], cerere.get("url"))
                    self._json(out)
                except (OSError, ValueError, sqlite3.Error) as exc:
                    self._json({"error": str(exc)}, 400)
                return
            if ruta == "/api/conflicte-proiecte":
                self._json(_conflicte_proiecte(cerere, stare))
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
            if ruta == "/api/importa":
                self._json(
                    _importa(str(cerere.get("nume", "")), str(cerere.get("continut_b64", "")))
                )
                return
            if ruta == "/api/docx":
                self._json(_docx(str(cerere.get("titlu", "")), str(cerere.get("text", ""))))
                return
            draft = str(cerere.get("draft", "")).strip()
            if not draft:
                self._json({"error": "draft gol"}, 400)
                return
            if ruta == "/api/ue":
                self._json(
                    _ue(draft, stare, limita=cerere.get("limita", 12), limba=cerere.get("limba"))
                )
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
    eu: str = "eu.db",
    *,
    data_home: str | None = None,
    data_channel: str | None = None,
):
    if data_home is not None:
        from scripts.local_runtime import DEFAULT_CHANNEL, open_runtime

        with open_runtime(data_home, data_channel or DEFAULT_CHANNEL) as runtime:
            return _serveste_local(port, runtime, deschide_browser)
    stare = Stare(corpus, initiative, graf, eu)
    server = ThreadingHTTPServer(("127.0.0.1", port), face_handler(stare))
    grafic = "cu graf" if stare.are_graf() else "fără graf"
    europa = "cu UE" if stare.are_ue() else "fără UE"
    url = f"http://127.0.0.1:{port}"

    # One throwaway lint before announcing the port. Measured on the full corpus, the first request
    # costs 4 s and every one after it 285 ms — the difference is module imports done lazily inside
    # the passes and SQLite warming its page cache over a 9 GB file. Paid here it lands on a line
    # that says it is starting; paid on the first request it lands on somebody's first question.
    _incalzeste(stare)
    print(f"legislativ pe {url}  ({len(stare.termeni)} termeni în dicționar, {grafic}, {europa})")
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


def _serveste_local(port, runtime, deschide_browser):
    import threading
    import webbrowser

    handler = face_handler(runtime.manager.current_state, runtime=runtime)
    with LoopbackHTTPServer(("127.0.0.1", port), handler) as server:
        server.daemon_threads = False
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"legislativ pe {url}\nDate locale: {runtime.home}", flush=True)
        timer = None
        if deschide_browser:
            timer = threading.Timer(0.5, lambda: webbrowser.open(url))
            timer.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\noprit.")
        finally:
            if timer is not None:
                timer.cancel()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--initiative", default="initiative.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument("--eu", default="eu.db")
    ap.add_argument("--fara-browser", action="store_true", help="nu deschide browserul")
    ap.add_argument("--data-home", help="directorul persistent de date locale")
    ap.add_argument("--data-channel", help="canalul HTTPS de actualizare configurat")
    a = ap.parse_args()
    if a.data_channel and not a.data_home:
        ap.error("--data-channel necesita --data-home")
    try:
        serveste(
            a.port,
            a.corpus,
            a.initiative,
            a.graf,
            deschide_browser=not a.fara_browser,
            eu=a.eu,
            data_home=a.data_home,
            data_channel=a.data_channel,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        ap.exit(1, f"Pornirea aplicatiei a esuat: {exc}\n")
