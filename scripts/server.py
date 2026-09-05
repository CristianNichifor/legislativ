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

**Endpoints, one question each:**
- `POST /api/lint` — a pasted draft against the law: the deadlines it imposes, the defined terms
  it talks around, and the pending bills it may duplicate. The three deterministic passes, in one
  answer.
- `GET /api/cauta?q=` — full-text search over every provision, diacritic-insensitive.
- `GET /api/redacteaza` — a structured intent into the mandated Legea 24/2000 phrasing.
- `GET /api/sugereaza?text=` — the legistic form of the line being written, offered as it is
  typed: plain-language restatement plus the mandated formula. Deterministic, no model, no corpus.
- `GET /api/consolidat[?act=]` — a provision's current wording with each change attributed, or the
  acts available to show. Reads locally synced pages, never a live portal fetch.
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

    def __init__(
        self,
        corpus: str = "corpus.db",
        initiative: str = "initiative.db",
        graf: str = "graf.db",
    ):
        self.corpus = corpus
        self.initiative = initiative
        self.graf = graf
        self.termeni: list[Termen] = self._dictionar()

    def are_graf(self) -> bool:
        return Path(self.graf).is_file()

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
    from scripts.redactare import conformitate

    drafting = [
        {"gasit": a.gasit, "operatie": a.operatie, "explicatie": a.explicatie}
        for a in conformitate(draft)
    ]
    return {
        "deadlines": deadlines,
        "terminology": termen_hits,
        "duplicates": dup,
        "targets": _targets(draft, stare),
        "repealed": _repealed(draft, stare),
        "drafting": drafting,
        "consolidare": _consolidare_semnale(draft),
    }


def _consolidare_semnale(draft: str) -> list[dict]:
    """Where the draft cites a provision that has since been rewritten — check the current text.

    The linter's other passes reason over acts as published; this one reasons over what they say
    *now*. For each provision the draft cites whose act can be consolidated locally, it reports the
    changes that provision (or a unit inside it) has undergone, so a drafter amending or relying on
    `art. 187` is told alin. (8) was rewritten in 2022 and points them at the consolidated text
    rather than the original. Silent where no consolidated form is synced — never a false "current".
    """
    from scripts.consolidat import modificari_pentru
    from scripts.referinte import referinte

    vazute: set[tuple[str, str]] = set()
    out: list[dict] = []
    for ref in referinte(draft):
        if ref.act is None or not ref.locator:
            continue
        loc_id = ref.locator.id
        cheie = (ref.act.id, loc_id)
        if cheie in vazute:
            continue
        touched = modificari_pentru(ref.act.id)
        if not touched:
            continue
        # provisions changed at the cited locator, or at a unit inside it (cite art. 187, alin. (8)
        # changed). Only those that actually carry a change or a refusal are worth surfacing.
        relevante = [
            (lid, r)
            for lid, r in touched.items()
            if (lid == loc_id or lid.startswith(loc_id + "."))
            and (r.schimbari or r.abrogat or not r.complet)
        ]
        if not relevante:
            continue
        vazute.add(cheie)
        prin = sorted({s.act for _, r in relevante for s in r.schimbari})
        date_ = [s.data.isoformat() for _, r in relevante for s in r.schimbari if s.data]
        out.append(
            {
                "act_id": ref.act.id,
                "locator": loc_id,
                "abrogat": any(r.abrogat for _, r in relevante),
                "neconsolidat": any(not r.complet for _, r in relevante),
                "unitati": sorted(lid for lid, _ in relevante),
                "prin": prin,
                "ultima": max(date_, default=None),
            }
        )
    return out


def _repealed(draft: str, stare: Stare) -> list[dict]:
    """References in the draft to a repealed act or article — the citation it must not build on.

    Read from the graph's `abroga` edges, so it appears only once a graph is built and only for
    repeals whose acts are collected: silent where the data cannot reach, never a false "in
    force". The highest-severity thing the linter can say, so it leads the answer in the UI.
    """
    if not stare.are_graf():
        return []
    from scripts.graf import _deschide_graf
    from scripts.vigoare import citari_moarte

    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        return [
            {
                "act_id": cm.act_id,
                "locator": cm.locator,
                "motiv": cm.motiv,
                "intregul_act": cm.abrogare.este_intregul_act,
            }
            for cm in citari_moarte(draft, graf)
        ]
    finally:
        graf.close()


def _targets(draft: str, stare: Stare) -> list[dict]:
    """For each act the draft amends or cites, what the graph knows about it.

    The single most useful thing to tell someone amending a law is how amended it already is: a
    provision on its twelfth revision is one to consolidate against, not to patch blind. Cheap —
    one graph lookup per target act — and it is where in-force awareness will land once the graph
    carries dates on every edge. Silent when no graph is built yet, rather than pretending.
    """
    if not stare.are_graf():
        return []
    from scripts.dublura import tinte
    from scripts.graf import _deschide_graf, inbound

    acte = sorted({t.split(" ")[0] for t in tinte(draft)})
    if not acte:
        return []
    from scripts.imbogateste import initiative_pe_act

    out: list[dict] = []
    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        with (
            depozit.deschide(stare.corpus, readonly=True) as con,
            depozit.deschide(stare.initiative, readonly=True) as ini,
        ):
            for act_id in acte:
                amend = inbound(graf, act_id, doar_amendamente=True)
                rand = con.execute("SELECT titlu FROM acte WHERE id = ?", (act_id,)).fetchone()
                try:
                    pendinte = initiative_pe_act(ini, act_id)
                except Exception:
                    pendinte = []
                out.append(
                    {
                        "act_id": act_id,
                        "titlu": (rand["titlu"] if rand else ""),
                        "in_corpus": rand is not None,
                        "amendat_de": len(amend),
                        "ultima": max(
                            (m.de_la.isoformat() for m in amend if m.de_la), default=None
                        ),
                        # pending bills already touching this act: the "someone's on it" signal
                        "initiative_in_lucru": len(pendinte),
                    }
                )
    finally:
        graf.close()
    return out


def _redacteaza(qs: dict) -> dict:
    """Turn a structured drafting intent into the mandated legistic text and title.

    The visible half of the drafting-form layer: a form supplies the operation, the act and the
    element, this returns the phrasing Legea 24/2000 requires, ready to paste. Pure — no corpus,
    no graph — so it answers instantly and works before any collection.
    """
    from scripts.redactare import redacteaza, titlu_modificator

    def g(k: str) -> str | None:
        v = qs.get(k, [""])[0].strip()
        return v or None

    op = g("op") or "modifica"
    act = g("act") or "…"
    try:
        text = redacteaza(
            op,
            act,
            articol=g("articol"),
            alineat=g("alineat"),
            litera=g("litera"),
            text_nou=g("text") or "…",
            articol_nou=g("articol_nou"),
        )
        titlu = titlu_modificator(op, act, articol=g("articol"))
        return {"text": text, "titlu": titlu}
    except ValueError as e:
        return {"error": str(e)}


def _sugereaza(qs: dict) -> dict:
    """The legistic form of the line being written — deterministic, no corpus, no model.

    Pure over `sugestii.sugereaza`: it answers from the sentence alone, so it works before any
    collection and adds no network call. Nothing recognised is a first-class answer, not an error —
    the client simply shows no tooltip."""
    from scripts.sugestii import sugereaza

    text = qs.get("text", [""])[0]
    s = sugereaza(text)
    if s is None:
        return {"detectat": False}
    return {
        "detectat": True,
        "fel": s.fel,
        "act_id": s.act_id,
        "locator_id": s.locator_id,
        "simplu": s.simplu,
        "formula": s.formula,
        "nestandard": s.nestandard,
    }


def _consolidat(qs: dict) -> dict:
    """A provision's current wording with each change attributed, or the acts available to show.

    With no `act`, it lists what this install can consolidate — the acts whose pages are synced
    locally. With an `act`, it returns each touched provision as text-in-force plus attribution, or
    an honest note where the engine refused. `la_data` is the as-of date; the operations carry
    their own effective dates, so a past `la_data` correctly hides a later change.
    """
    from datetime import date

    from scripts.consolidat import acte_disponibile, consolideaza_local

    act_id = qs.get("act", [""])[0].strip()
    if not act_id:
        return {"acte": acte_disponibile()}

    brut = qs.get("la_data", [""])[0].strip()
    try:
        la_data = date.fromisoformat(brut) if brut else None
    except ValueError:
        return {"error": f"dată invalidă: {brut}"}

    try:
        tinta, rez = consolideaza_local(act_id, la_data=la_data)
    except KeyError:
        return {"error": f"actul «{act_id}» nu este disponibil local pentru consolidare"}

    provizii = [
        {
            "locator": r.locator,
            "complet": r.complet,
            "abrogat": r.abrogat,
            "text": r.text,
            "schimbari": [
                {"act": s.act, "fel": s.fel, "data": s.data.isoformat() if s.data else None}
                for s in r.schimbari
            ],
            "limitari": list(r.limitari),
        }
        for r in sorted(rez.values(), key=lambda r: r.locator)
    ]
    consolidate = sum(1 for p in provizii if p["complet"])
    return {
        "act_id": act_id,
        "titlu": tinta.titlu,
        "la_data": (la_data or date.today()).isoformat(),
        "provizii": provizii,
        "rezumat": {"atinse": len(provizii), "consolidate": consolidate,
                    "refuzate": len(provizii) - consolidate},
    }


def _cauta(q: str, stare: Stare) -> dict:
    if not q.strip():
        return {"results": []}
    with depozit.deschide(stare.corpus, readonly=True) as con:
        rows = depozit.cauta(con, q, 25)
    return {"results": [dict(r) for r in rows]}


def _vecini(act_id: str, stare: Stare, *, limita: int = 10) -> dict:
    """One act's graph neighbourhood: who amends it, and what it amends or references.

    The second hop of the connections canvas — click a law and see its own links, so the panel
    becomes something to explore rather than glance at. Bounded per side (`limita`) because a
    long-lived law is amended dozens of times and the point is the shape, not the census; inbound
    is returned most-recent-first so the cap keeps what matters. Titles are looked up from the
    corpus for the neighbours actually returned, so it stays cheap.
    """
    if not stare.are_graf():
        return {"act": act_id, "inbound": [], "outbound": []}
    from scripts.graf import _deschide_graf, inbound, outbound

    def _dedup(muchii, other_of):
        # One node per neighbouring act: the same act amending several articles is one amender,
        # not five. Keep the first (most significant / most recent) edge, count the rest.
        vazut: dict[str, object] = {}
        for m in muchii:
            other = other_of(m)
            if other == act_id:
                continue
            if other not in vazut:
                vazut[other] = m
        return vazut

    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        intra = _dedup(reversed(inbound(graf, act_id)), lambda m: m.din_act)
        iese = _dedup(outbound(graf, act_id), lambda m: m.catre_act)
        with depozit.deschide(stare.corpus, readonly=True) as con:

            def shape(other, m):
                r = con.execute("SELECT titlu FROM acte WHERE id = ?", (other,)).fetchone()
                return {
                    "act_id": other,
                    "fel": m.fel,
                    "locator": m.locator,
                    "de_la": m.de_la.isoformat() if m.de_la else None,
                    "titlu": (r["titlu"] if r else "") or "",
                }

            inb = [shape(o, m) for o, m in list(intra.items())[:limita]]
            outb = [shape(o, m) for o, m in list(iese.items())[:limita]]
    finally:
        graf.close()
    return {"act": act_id, "inbound": inb, "outbound": outb}


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
