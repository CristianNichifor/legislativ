"""The engine-facing services, with no transport attached.

Everything the app can answer is a function over a read-only corpus. These are those functions —
one per question the UI asks — shaped into plain dicts ready to serialise, and nothing more. They
know about the engines and the corpus; they know nothing about HTTP, sockets, or a browser.

That separation is what lets the same logic run two ways from one implementation: `server.py`
wraps these in `http.server` for the localhost tool, and the browser build drives them under
Pyodide with no server at all. Neither is a second copy of the honesty-critical logic — both call
these, so the tests that guard them guard both surfaces. Importing this module pulls in no
transport, which is the point: it loads where `http.server`'s `socket` import would not.

**Read-only.** Every corpus open is `mode=ro`; these never write, so they coexist with the
collectors and answer from more law each time a page lands. The one held piece of state is the
terminology dictionary, built once from the most recent acts, because rebuilding it per request
would read the whole corpus on every keystroke.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from scripts import depozit, nomenclator
from scripts.definitii import Termen, jargon
from scripts.dublura import dubluri
from scripts.termene import obligatii


def _data(brut: str | None) -> date | None:
    """An ISO date off either backing, or None when it is absent or unparseable.

    Unparseable reads as absent on purpose: a malformed republication date must not be treated as a
    renumbering boundary, and it must not raise in the middle of a lint either.
    """
    if not brut:
        return None
    try:
        return date.fromisoformat(str(brut)[:10])
    except ValueError:
        return None


class Stare:
    """What a session holds open: the data, and the terminology dictionary built from it.

    Two backings, one interface. On the **localhost** server `corpus.db` is the source of truth —
    titles, counts and the dictionary come from it by SQL. In the **browser** the whole corpus is
    not shippable, so a `date_dir` of shards backs the same three needs instead: titles from
    `index.json`, counts from `manifest.json`, and the dictionary from a prebuilt `termeni.json`.
    Everything else the engines read — the amendment graph and the initiatives — is small enough to
    stay a real database either way. The point of the seam is that no engine below cares which
    backing it has; they call `titlu`, `cunoscut`, `termeni`, `rezumat`, and get an answer.

    Corpus connections (localhost) are per-request — SQLite connections are not safe to share
    across threads — but the dictionary is built once here, the one expensive thing.
    """

    def __init__(
        self,
        corpus: str = "corpus.db",
        initiative: str = "initiative.db",
        graf: str = "graf.db",
        eu: str = "eu.db",
        *,
        date_dir: str | None = None,
        reports_dir: str | None = None,
        corpus_intreg: bool = False,
    ):
        self.corpus = corpus
        self.initiative = initiative
        self.graf = graf
        self.eu = eu
        self.date_dir = Path(date_dir) if date_dir else None
        self.reports_dir = Path(reports_dir) if reports_dir is not None else None
        self.corpus_intreg = corpus_intreg
        self._titluri: dict[str, str] | None = None
        self._urls: dict[str, str] | None = None
        self._republicari: dict[str, str] | None = None
        self._ids: set[str] | None = None
        self._alias: dict[str, str] | None = None
        self.termeni: list[Termen] = self._dictionar()
        self.vid: list[dict] = self._incarca_raport("vid.json")
        self.neconstitutional: list[dict] = self._incarca_raport("neconstitutional.json")
        self.norme_lovite: list[dict] = self._incarca_raport("norme_lovite.json")
        # The groups and the directory, settled at publish time. See `construieste_parlament`.
        parlament = self._incarca_raport("parlament.json")
        self.parlament: dict = parlament if isinstance(parlament, dict) else {}
        # Lazy: only the model pass reads the reasoning, and that pass needs a model. Loading it
        # eagerly would make every offline session pay for a feature it is not using.
        self._considerente: dict[str, str] | None = None

    @property
    def pe_shard(self) -> bool:
        """Whether corpus questions must be answered from prebuilt slices instead of the corpus.

        `date_dir` used to decide this on its own, which conflated two different things: where the
        precomputed reports live, and whether there is a corpus to query at all. Once the browser
        mounts the whole corpus over the network there is one — so the reports still come from
        `date_dir`, but every count, title and search goes to the database. Leaving them on the
        slice is what made a build with 203.353 acts announce four.
        """
        return self.date_dir is not None and not self.corpus_intreg

    @property
    def report_root(self) -> Path | None:
        return self.reports_dir if self.reports_dir is not None else self.date_dir

    @property
    def are_rapoarte(self) -> bool:
        """An explicit report root, independent of whether corpus queries use shards."""
        return self.report_root is not None

    def are_graf(self) -> bool:
        return Path(self.graf).is_file()

    def are_ue(self) -> bool:
        return Path(self.eu).is_file()

    # Built from the most recent acts only, not the whole corpus: definitions over a
    # quarter-million acts would take minutes, and the terminology check must answer instantly. The
    # recent N carry the vocabulary a current draft is most likely to talk around. On shards the
    # same bounded dictionary arrives prebuilt as `termeni.json`.
    def _dictionar(self, limita: int = 800) -> list[Termen]:
        if self.are_rapoarte:
            cale = self.report_root / "termeni.json"
            if not cale.is_file():
                return []
            brut = json.loads(cale.read_text(encoding="utf-8"))
            return [Termen(termen=t["termen"], definitie=t["definitie"]) for t in brut]
        from scripts.analiza import termeni_corpus

        try:
            with depozit.deschide(self.corpus, readonly=True) as con:
                return termeni_corpus(con, limita=limita)
        except Exception:
            return []

    # Two corpus-wide reports are precomputed at build time — a scan of the whole corpus is far
    # too slow per request — and shipped as JSON, exactly like the dictionary: the unmet
    # obligations (`vid.py`) and the struck-but-unrepaired register (`neconstitutional.py`).
    # Absent (a localhost that has not been built) → the pass is silently empty, like every other
    # data-gated pass. The linter filters each to what the current draft touches.
    def _incarca_raport(self, nume: str):
        """A prebuilt report. Returns whatever the file holds — the older ones are lists, the
        Parliament one is an object keyed by legislature."""
        cai = (
            [self.report_root / nume]
            if self.are_rapoarte
            else [Path("web/data") / nume, Path(nume)]
        )
        for cale in cai:
            if cale.is_file():
                try:
                    return json.loads(cale.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return []
        return []

    def considerente(self) -> dict[str, str]:
        """Excerpts of the Court's reasoning, keyed by decision. Empty when none was shipped."""
        if self._considerente is None:
            brut = self._incarca_raport("considerente.json")
            self._considerente = brut if isinstance(brut, dict) else {}
        return self._considerente

    def _index(self) -> dict[str, str]:
        if self._titluri is None:
            cale = self.date_dir / "index.json" if self.pe_shard else None
            if cale and cale.is_file():
                index = json.loads(cale.read_text(encoding="utf-8"))
                self._titluri = {a["id"]: a.get("titlu", "") for a in index}
                self._urls = {a["id"]: a.get("url", "") for a in index}
                # absent for all but the few republished acts, so only the keys that carry one
                self._republicari = {
                    a["id"]: a["republicat_din"] for a in index if a.get("republicat_din")
                }
            else:
                self._titluri, self._urls, self._republicari = {}, {}, {}
        return self._titluri

    def sursa_url(self, act_id: str) -> str:
        """The public portal URL for an act — from the shard index in the browser, or the corpus's
        stored source / portal id on localhost. Empty when the act carries neither."""
        act_id = self.rezolva_nume(act_id)
        if self.pe_shard:
            self._index()
            return (self._urls or {}).get(act_id, "")
        with depozit.deschide(self.corpus, readonly=True) as con:
            r = con.execute(
                "SELECT sursa_url, id_act_portal FROM acte WHERE id = ?", (act_id,)
            ).fetchone()
            return depozit.url_document(r["sursa_url"], r["id_act_portal"]) if r else ""

    def republicari(self, act_ids: set[str]) -> dict[str, date | None]:
        """When each of these acts was republished, where the corpus records it.

        `vigoare.py` needs this to know whether a locator-level repeal predates a renumbering. Read
        for the handful of acts a draft actually cites, not the whole corpus. Both backings, like
        `titlu` and `sursa_url`: the `acte` table on localhost, the shard index in the browser —
        `shard.py` carries `republicat_din` in `index.json` for exactly this.
        """
        if not act_ids:
            return {}
        if self.pe_shard:
            self._index()
            return {a: _data((self._republicari or {}).get(a)) for a in act_ids}
        with depozit.deschide(self.corpus, readonly=True) as con:
            marci = ",".join("?" * len(act_ids))
            randuri = con.execute(
                f"SELECT id, republicat_din FROM acte WHERE id IN ({marci})", tuple(act_ids)
            ).fetchall()
        return {r["id"]: _data(r["republicat_din"]) for r in randuri}

    def titlu(self, act_id: str) -> str:
        """The act's title, from the shard index in the browser or `acte` on localhost."""
        act_id = self.rezolva_nume(act_id)
        if self.pe_shard:
            return self._index().get(act_id, "")
        with depozit.deschide(self.corpus, readonly=True) as con:
            rand = con.execute("SELECT titlu FROM acte WHERE id = ?", (act_id,)).fetchone()
            return (rand["titlu"] if rand else "") or ""

    def _toate_id(self) -> set[str]:
        """Every act id the backing holds. Only the named-act resolver needs the whole set, and
        only for the handful of names it knows, so it is read on demand and kept."""
        if self._ids is None:
            if self.pe_shard:
                self._ids = set(self._index())
            else:
                try:
                    with depozit.deschide(self.corpus, readonly=True) as con:
                        self._ids = {r[0] for r in con.execute("SELECT id FROM acte")}
                except Exception:
                    self._ids = set()
        return self._ids

    def _alias_an(self) -> dict[str, str]:
        """Acts filed under the year they were republished rather than the year they were passed.

        Built once, and only when a lookup has already missed — it is a scan of `documente`, which
        the shard backing does not have at all, and most sessions never need it.
        """
        if self._alias is None:
            if self.pe_shard:
                self._alias = {}
            else:
                try:
                    with depozit.deschide(self.corpus, readonly=True) as con:
                        self._alias = nomenclator.alias_an(con)
                except Exception:
                    self._alias = {}
        return self._alias

    def rezolva_nume(self, act_id: str, la_data: date | None = None) -> str:
        """A named act (`constitutie`, `cod-penal`) mapped onto the version the corpus stores.

        Citations name these acts; the collector keys them from their own titles, so the two write
        different ids for the same law and a quarter of everything the corpus cites looked absent.
        Anything that is not a name is returned unchanged, so callers can apply this blindly.
        """
        if nomenclator.este_nume(act_id):
            return nomenclator.rezolva(act_id, self._toate_id(), la_data) or act_id
        # Only after a miss: an id the corpus really holds is never looked up in the alias map, so
        # the scan behind it stays unpaid for every citation that already resolves.
        if act_id in self._toate_id():
            return act_id
        return self._alias_an().get(act_id, act_id)

    def cunoscut(self, act_id: str) -> bool:
        """Whether the corpus carries this act at all — the honest 'in corpus' signal."""
        act_id = self.rezolva_nume(act_id)
        if self.pe_shard:
            return act_id in self._index()
        with depozit.deschide(self.corpus, readonly=True) as con:
            return con.execute("SELECT 1 FROM acte WHERE id = ?", (act_id,)).fetchone() is not None


def _inventar_surse(stare: Stare) -> dict:
    if stare.date_dir is not None:
        return {
            "schema_version": 1,
            "mod": "static",
            "acoperire_juridica": "necunoscuta",
            "surse": {},
            "limitari": ["Inventarul bazei locale nu este disponibil în versiunea statică."],
        }
    from scripts.inventar_surse import raport

    return raport(stare.corpus, stare.initiative, stare.eu)


def rezumat(stare: Stare) -> dict:
    """The corpus headline the page opens with: how much law, how many bills.

    Read from the manifest whenever there is one. These counts are settled when the dataset is
    published; recounting them per request costs nothing locally and reads most of the corpus when
    it is behind byte-range requests.
    """
    if not getattr(stare, "dataset_available", True):
        return {
            "acte": 0,
            "provizii": 0,
            "acte_structurate": 0,
            "acte_normative": 0,
            "initiative": 0,
            "dataset_available": False,
            "limitari": ["Setul public de date nu este instalat."],
            **_rezumat_ue(stare),
        }
    cale = stare.report_root / "manifest.json" if stare.are_rapoarte else None
    if cale is not None and (stare.pe_shard or cale.is_file()):
        m = json.loads(cale.read_text(encoding="utf-8")) if cale.is_file() else {}
        r = {
            "acte": m.get("acte", 0),
            "provizii": m.get("provizii", 0),
            # Counted at build time by `shard.py`; free to read here, where the corpus is absent.
            "acte_structurate": m.get("acte_structurate", 0),
            "acte_normative": m.get("acte_normative", 0),
        }
    else:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            r = depozit.rezumat(con)
    with depozit.deschide(stare.initiative, readonly=True) as con:
        r["initiative"] = depozit.rezumat(con)["initiative"]
    r |= _rezumat_ue(stare)
    return r


def _lint(draft: str, stare: Stare) -> dict:
    """The deterministic passes over a pasted draft, each carrying its own provenance."""
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
    from scripts.redactare import conformitate, interventii_conflictuale

    # `conformitate` returns both kinds of departure in one list, and they answer different
    # questions: an operation-form error says the intent was named with the wrong verb, a `limbaj`
    # one says the verb is right but the sentence is not written the way a norm is written. Reported
    # together they shared a heading and a count, so "redactare: 4" could mean four wrong verbs, or
    # four occurrences of «etc.», or any mix. Partitioned here — one pass, each finding in exactly
    # one bucket, no double-reporting.
    abateri = conformitate(draft)
    drafting = [
        {"gasit": a.gasit, "operatie": a.operatie, "explicatie": a.explicatie}
        for a in abateri
        if a.operatie != "limbaj"
    ]
    limbaj = [
        {"gasit": a.gasit, "fragment": a.fragment, "explicatie": a.explicatie}
        for a in abateri
        if a.operatie == "limbaj"
    ]
    conflicte = [
        {"fel": c.fel, "act": c.act, "locator": c.locator, "explicatie": c.explicatie}
        for c in interventii_conflictuale(draft)
    ]
    return {
        "deadlines": deadlines,
        "terminology": termen_hits,
        "duplicates": dup,
        "targets": _targets(draft, stare),
        # Ahead of `repealed` deliberately: a repealed provision is law that ended, which is
        # orderly; a struck and unrepaired one is text still printed in the official version that
        # has had no legal effect since a date in the 1990s. Building on the second is worse.
        "neconstitutional": _neconstitutional(draft, stare),
        # Distinct from the pass above, and the distinction is the point: that one asks whether the
        # draft *cites* a struck provision, this one whether it *re-enacts* one. A draft can do the
        # second while citing nothing at all.
        "reluare": _reluare(draft, stare),
        "repealed": _repealed(draft, stare),
        "calificate": _calificate(draft, stare),
        "drafting": drafting,
        "limbaj": limbaj,
        "conflicte": conflicte,
        "consolidare": _consolidare_semnale(draft),
        "obligatii_neindeplinite": _obligatii_neindeplinite(draft, stare),
    }


def _obligatii_neindeplinite(draft: str, stare: Stare) -> list[dict]:
    """From the prebuilt gap report, the unmet obligations of the acts this draft touches.

    `vid.py` asks which obligations in the law have no implementing act in the corpus. That report
    is corpus-wide and precomputed (`stare.vid`); here it is filtered to the acts the draft amends
    or cites, so a drafter patching Legea 98/2016 is told which of its own delegated norms were
    never issued. Silent when no report is shipped or the draft touches nothing in it."""
    if not stare.vid:
        return []
    from scripts.dublura import tinte

    acte = {t.split(" ")[0] for t in tinte(draft)}
    return [v for v in stare.vid if v.get("act_id") in acte]


def _impact(draft: str, stare: Stare) -> dict:
    """The downstream reach of a draft's amendments — structural, definitional, obligational — so a
    small change with a large effect is visible (see `scripts.impact`).

    Structural reach comes from the graph (both surfaces ship it); the definitional usage count
    needs the corpus and so is filled only on localhost, left `null` on the browser, not faked."""
    from scripts.definitii import jargon
    from scripts.impact import raza_de_impact

    def categorii(text: str) -> list[dict]:
        return [
            {"fragment": a.fragment, "termen": a.termen.termen, "explicatie": a.explicatie}
            for a in jargon(text, stare.termeni)
            if a.regula == "categorie-paralela"
        ]

    if not stare.are_graf():
        return raza_de_impact(draft or "", categorii_fn=categorii)
    from scripts.graf import _deschide_graf, inbound

    graf = _deschide_graf(stare.graf, readonly=True)

    def citari(act_id: str) -> tuple[int, int]:
        muchii = inbound(graf, act_id)
        toate = {m.din_act for m in muchii}
        amend = {m.din_act for m in muchii if m.fel != "refera"}
        return len(toate), len(amend)

    try:
        if stare.pe_shard:
            return raza_de_impact(draft or "", citari_fn=citari, categorii_fn=categorii)
        with depozit.deschide(stare.corpus, readonly=True) as con:

            def numara(termen: str) -> int | None:
                try:
                    return depozit.cauta_numar(con, f'"{termen}"')
                except Exception:
                    return None

            def text_orig(act_id: str, locator: str) -> str | None:
                try:
                    r = con.execute(
                        "SELECT text FROM provizii WHERE act_id = ? AND locator = ? "
                        "ORDER BY ord LIMIT 1",
                        (act_id, locator),
                    ).fetchone()
                    return r["text"] if r else None
                except Exception:
                    return None

            return raza_de_impact(
                draft or "",
                citari_fn=citari,
                numara_termen=numara,
                text_original=text_orig,
                categorii_fn=categorii,
            )
    finally:
        graf.close()


def _cronologie(act_id: str, stare: Stare) -> dict:
    """The amendment timeline of an act: every act that amended it, in date order, so an incremental
    reform — a series of small edits pushed over years — shows its cumulative arc. From the graph's
    inbound amendment edges (their `de_la` is the amending act's own entry into force)."""
    if not stare.are_graf() or not act_id:
        return {"act": act_id, "evenimente": []}
    from scripts.graf import _deschide_graf, inbound

    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        ev = [
            {
                "act_id": m.din_act,
                "fel": m.fel,
                "de_la": m.de_la.isoformat() if m.de_la else None,
                "locator": m.locator,
                "titlu": stare.titlu(m.din_act),
            }
            for m in inbound(graf, act_id, doar_amendamente=True)
        ]
    finally:
        graf.close()
    # newest last so the arc reads top-to-bottom; undated events sink to the end
    ev.sort(key=lambda e: e["de_la"] or "9999")
    return {"act": act_id, "evenimente": ev}


def _citari(act_id: str, stare: Stare) -> dict:
    """How many acts reference / amend `act_id` — the "landmine" signal while drafting: editing a
    provision many acts depend on propagates widely."""
    if not stare.are_graf() or not act_id:
        return {"act_id": act_id, "citari": 0, "amendat": 0}
    from scripts.graf import _deschide_graf, inbound

    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        muchii = inbound(graf, act_id)
        return {
            "act_id": act_id,
            "citari": len({m.din_act for m in muchii}),
            "amendat": len({m.din_act for m in muchii if m.fel != "refera"}),
        }
    finally:
        graf.close()


def _supraveghere(act_id: str, stare: Stare) -> dict:
    """The watch-state of one act: the pending bills that touch it, its amendment activity, and how
    heavily it is cited — everything a drafter tracking a law (their own or a rival's) needs in one
    card. The client keeps the watchlist (offline, no account); this answers per act on demand."""
    if not act_id:
        return {"act_id": act_id, "cunoscut": False, "initiative": []}
    out: dict = {
        "act_id": act_id,
        "titlu": stare.titlu(act_id),
        "cunoscut": stare.cunoscut(act_id),
        "citari": 0,
        "amendat": 0,
        "ultima_modificare": None,
        "initiative": [],
        "initiative_status": "necunoscut",
        "limitari": [],
    }
    if stare.are_graf():
        from scripts.graf import _deschide_graf, inbound

        graf = _deschide_graf(stare.graf, readonly=True)
        try:
            muchii = inbound(graf, act_id)
            amend = [m for m in muchii if m.fel != "refera"]
            out["citari"] = len({m.din_act for m in muchii})
            out["amendat"] = len({m.din_act for m in amend})
            date = [m.de_la.isoformat() for m in amend if m.de_la]
            out["ultima_modificare"] = max(date) if date else None
        finally:
            graf.close()
    try:
        from scripts.imbogateste import initiative_pe_act

        with depozit.deschide(stare.initiative, readonly=True) as ini:
            tables = {
                r[0] for r in ini.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "initiative" not in tables:
                out["initiative_status"] = "surse_indisponibile"
                out["limitari"].append("Registrul inițiativelor nu este instalat.")
                return out
            if "initiative_tinta" not in tables:
                out["initiative_status"] = "index_indisponibil"
                out["limitari"].append("Indexul actelor atinse de inițiative nu este instalat.")
                return out
            out["initiative"] = initiative_pe_act(ini, act_id)
            out["initiative_status"] = "ok"
    except Exception:
        out["initiative_status"] = "surse_indisponibile"
        out["limitari"].append("Registrul inițiativelor nu este disponibil.")
        out["initiative"] = []
    return out


def _raport_lista(raport) -> list[dict]:
    """A prebuilt report if it is list-shaped; anything else is absent for this endpoint."""
    return raport if isinstance(raport, list) else []


def _numar_qs(qs: dict, cheie: str, implicit: int) -> int:
    try:
        return int((qs.get(cheie, [""])[0] or "").strip() or implicit)
    except (TypeError, ValueError):
        return implicit


def _bucati(valori: set[str], marime: int = 400):
    """SQLite's variable limit is finite; query report ids in small batches."""
    lista = sorted(v for v in valori if v)
    for i in range(0, len(lista), marime):
        yield lista[i : i + marime]


def _meta_acte(con: sqlite3.Connection, act_ids: set[str]) -> dict[str, list[dict]]:
    """Map report/graph citation keys back to the issuing body and instrument the corpus states.

    Report rows usually carry the citation key (`lege-98-2016`). After namesake support an `acte.id`
    may be qualified (`hotarare-1-2016-senatul`), while `cheie_citare` stays what a reader writes.
    So both are read; an exact id wins later, otherwise the bare citation remains a limited but
    useful grouping.
    """
    gasite: dict[str, list[dict]] = {}
    if not act_ids:
        return gasite
    for bucata in _bucati(act_ids):
        cautate = set(bucata)
        marci = ",".join("?" * len(bucata))
        for r in con.execute(
            "SELECT id, cheie_citare, tip, titlu, emitent, an, publicat FROM acte"
            f" WHERE id IN ({marci}) OR cheie_citare IN ({marci})",
            (*bucata, *bucata),
        ):
            meta = {
                "id": r["id"],
                "cheie_citare": r["cheie_citare"] or r["id"],
                "tip": r["tip"],
                "titlu": r["titlu"],
                "emitent": r["emitent"] or "(emitent necunoscut)",
                "an": r["an"],
                "publicat": r["publicat"],
            }
            for cheie in {meta["id"], meta["cheie_citare"]} & cautate:
                gasite.setdefault(cheie, []).append(meta)
    return gasite


def _alege_meta(act_id: str, meta: dict[str, list[dict]]) -> dict | None:
    candidati = meta.get(act_id) or []
    exact = [m for m in candidati if m["id"] == act_id]
    return (exact or candidati or [None])[0]


def _rand_matrice(emitent: str) -> dict:
    return {
        "emitent": emitent or "(emitent necunoscut)",
        "acte": 0,
        "de_la": None,
        "pana_la": None,
        "_tipuri": {},
        "_ranguri": {},
        "viduri": 0,
        "viduri_blocking": 0,
        "viduri_material": 0,
        "neconstitutionale": 0,
        "amendamente_primite": 0,
        "acte_amendate": 0,
        "initiative_in_lucru": 0,
        "_vid_exemple": [],
        "_neconst_exemple": [],
        "_domeniu_exemple": [],
    }


def _adauga_rang_matrice(rand: dict, tip: str, acte: int) -> None:
    from scripts import rang_normativ

    info = rang_normativ.info(tip)
    item = rand["_ranguri"].setdefault(
        info["categorie"],
        {
            "categorie": info["categorie"],
            "eticheta": info["eticheta"],
            "rang": info["rang"],
            "acte": 0,
            "_note": set(),
        },
    )
    item["acte"] += acte
    if info.get("nota"):
        item["_note"].add(info["nota"])


def _ranguri_matrice(rand: dict) -> list[dict]:
    return [
        {
            "categorie": r["categorie"],
            "eticheta": r["eticheta"],
            "rang": r["rang"],
            "acte": r["acte"],
            "note": sorted(r["_note"]),
        }
        for r in sorted(rand["_ranguri"].values(), key=lambda x: (x["rang"], x["categorie"]))
    ]


def _rezumat_ranguri_matrice(randuri: list[dict]) -> list[dict]:
    total: dict[str, dict] = {}
    for rand in randuri:
        for rang in rand["ranguri"]:
            item = total.setdefault(
                rang["categorie"],
                {
                    "categorie": rang["categorie"],
                    "eticheta": rang["eticheta"],
                    "rang": rang["rang"],
                    "acte": 0,
                    "_note": set(),
                },
            )
            item["acte"] += rang["acte"]
            item["_note"].update(rang["note"])
    return [
        {
            "categorie": r["categorie"],
            "eticheta": r["eticheta"],
            "rang": r["rang"],
            "acte": r["acte"],
            "note": sorted(r["_note"]),
        }
        for r in sorted(total.values(), key=lambda x: (x["rang"], x["categorie"]))
    ]


def _pune_exemplu(lista: list[dict], exemplu: dict, *, fel: str) -> None:
    lista.append(exemplu)
    if fel == "vid":
        lista.sort(
            key=lambda e: (
                -(e.get("zile_intarziere") or 0),
                0 if e.get("severitate") == "blocking" else 1,
                e.get("act_id", ""),
            )
        )
    else:
        lista.sort(key=lambda e: (-(e.get("zile_de_la_termen") or 0), e.get("act_id", "")))
    del lista[3:]


def _actiuni_prevedere(act_id: str, locator: str | None) -> list[dict]:
    act_id = (act_id or "").strip()
    locator = (locator or "").strip()
    if not act_id or not locator:
        return []
    return [
        {
            "fel": "prevedere",
            "eticheta": "vezi prevederea",
            "act_id": act_id,
            "locator": locator,
        }
    ]


def _adauga_exemplu_domeniu(rand: dict, exemplu: dict) -> None:
    if len(rand["_domeniu_exemple"]) < 3:
        rand["_domeniu_exemple"].append(exemplu)


def _amendamente_pe_act(stare: Stare) -> dict[str, dict[str, int]]:
    if not stare.are_graf():
        return {}
    from scripts.graf import _deschide_graf

    try:
        graf = _deschide_graf(stare.graf, readonly=True)
    except sqlite3.OperationalError:
        return {}
    try:
        try:
            return {
                r["catre_act"]: {"muchii": r["muchii"], "surse": r["surse"]}
                for r in graf.execute(
                    "SELECT catre_act, count(*) muchii, count(DISTINCT din_act) surse"
                    " FROM muchii"
                    " WHERE fel != 'refera' AND catre_act IS NOT NULL AND catre_act != ''"
                    " GROUP BY catre_act"
                )
            }
        except sqlite3.OperationalError:
            return {}
    finally:
        graf.close()


def _initiative_matrice(stare: Stare) -> dict[str, int]:
    """Pending initiatives per target act, from the precomputed reverse index when it exists."""
    try:
        from scripts.dublura import STADII_MOARTE
        from scripts.text import cheie

        gasite: dict[str, set[str]] = {}
        with depozit.deschide(stare.initiative, readonly=True) as con:
            for r in con.execute(
                "SELECT t.act_id, t.plx_id, i.stadiu FROM initiative_tinta t"
                " JOIN initiative i ON i.plx_id = t.plx_id"
            ):
                stadiu = cheie(r["stadiu"] or "")
                if any(m in stadiu for m in STADII_MOARTE):
                    continue
                gasite.setdefault(r["act_id"], set()).add(r["plx_id"])
        return {act_id: len(plx) for act_id, plx in gasite.items()}
    except sqlite3.OperationalError:
        return {}


PROBLEME_MATRICE = (
    {"cheie": "semnale", "eticheta": "orice semnal"},
    {"cheie": "viduri", "eticheta": "lacune legislative"},
    {"cheie": "viduri_blocking", "eticheta": "lacune blocante"},
    {"cheie": "neconstitutionale", "eticheta": "CCR nereparat"},
    {"cheie": "initiative", "eticheta": "inițiative pendinte"},
    {"cheie": "amendamente", "eticheta": "amendări primite"},
)


def _probleme_matrice() -> list[dict]:
    return [dict(p) for p in PROBLEME_MATRICE]


def _filtru_problema_matrice(rand: dict, problema: str | None) -> bool:
    if not problema:
        return True
    semnale = rand["semnale"]
    if problema == "semnale":
        return any(
            semnale[k]
            for k in (
                "viduri",
                "neconstitutionale",
                "initiative_in_lucru",
                "amendamente_primite",
            )
        )
    if problema == "viduri":
        return semnale["viduri"] > 0
    if problema == "viduri_blocking":
        return semnale["viduri_blocking"] > 0
    if problema == "neconstitutionale":
        return semnale["neconstitutionale"] > 0
    if problema == "initiative":
        return semnale["initiative_in_lucru"] > 0
    if problema == "amendamente":
        return semnale["amendamente_primite"] > 0
    return True


def _matrice(qs: dict, stare: Stare) -> dict:
    """A deterministic risk matrix by legally stated issuing body and instrument.

    It is deliberately not a subject taxonomy. The row axis is the issuer written on the document;
    the columns are counts the corpus, graph, initiative index and prebuilt reports can defend.
    """
    tip = (qs.get("tip", [""])[0] or "").strip() or None
    sortare = (qs.get("sort", ["semnale"])[0] or "semnale").strip()
    rang = (qs.get("rang", [""])[0] or "").strip() or None
    domeniu = (qs.get("domeniu", [""])[0] or "").strip() or None
    problema = (qs.get("problema", [""])[0] or "").strip() or None
    limita = max(1, min(_numar_qs(qs, "limita", 80), 200))
    viduri = _raport_lista(stare.vid)
    neconst = _raport_lista(stare.neconstitutional)
    amendamente = _amendamente_pe_act(stare)
    initiative = _initiative_matrice(stare)
    act_ids = (
        {v.get("act_id", "") for v in viduri}
        | {n.get("act_id", "") for n in neconst}
        | set(amendamente)
        | set(initiative)
    )

    from scripts import domenii_juridice, rang_normativ

    ranguri_valide = {v[0] for v in rang_normativ.CATEGORII.values()}
    rang_filtru = rang if rang in ranguri_valide else None
    domeniu_filtru = domeniu if domeniu in domenii_juridice.chei_valide() else None
    probleme_valide = {p["cheie"] for p in PROBLEME_MATRICE}
    problema_filtru = problema if problema in probleme_valide else None

    def tip_acceptat(tip_act: str | None) -> bool:
        if tip and tip_act != tip:
            return False
        return not (rang_filtru and rang_normativ.categorie(tip_act) != rang_filtru)

    def domeniu_din_meta(m: dict | None) -> dict:
        return domenii_juridice.clasifica(
            titlu=(m or {}).get("titlu", ""),
            emitent=(m or {}).get("emitent", ""),
        )

    def domeniu_acceptat(m: dict | None) -> bool:
        return not domeniu_filtru or (
            m is not None and domeniu_din_meta(m)["cheie"] == domeniu_filtru
        )

    try:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            randuri: dict[str, dict] = {}
            if domeniu_filtru:
                for r in con.execute(
                    "SELECT id, cheie_citare, tip, titlu,"
                    " COALESCE(NULLIF(trim(emitent), ''), '(emitent necunoscut)') emitent,"
                    " an, publicat FROM acte"
                ):
                    tip_act = r["tip"] or ""
                    if not tip_acceptat(tip_act):
                        continue
                    m = {
                        "id": r["id"],
                        "cheie_citare": r["cheie_citare"] or r["id"],
                        "tip": r["tip"],
                        "titlu": r["titlu"],
                        "emitent": r["emitent"],
                        "an": r["an"],
                        "publicat": r["publicat"],
                    }
                    domeniu_act = domeniu_din_meta(m)
                    if domeniu_act["cheie"] != domeniu_filtru:
                        continue
                    rand = randuri.setdefault(r["emitent"], _rand_matrice(r["emitent"]))
                    rand["acte"] += 1
                    rand["_tipuri"][tip_act] = rand["_tipuri"].get(tip_act, 0) + 1
                    _adauga_rang_matrice(rand, tip_act, 1)
                    if r["an"]:
                        rand["de_la"] = (
                            min(rand["de_la"], r["an"]) if rand["de_la"] is not None else r["an"]
                        )
                        rand["pana_la"] = (
                            max(rand["pana_la"], r["an"])
                            if rand["pana_la"] is not None
                            else r["an"]
                        )
                    _adauga_exemplu_domeniu(
                        rand,
                        {
                            "act_id": r["cheie_citare"] or r["id"],
                            "titlu": r["titlu"],
                            "dovezi": domeniu_act["dovezi"]
                            or ["fără indicator cunoscut în titlu/emitent"],
                        },
                    )
            else:
                conditie = " AND tip = ?" if tip else ""
                params = (tip,) if tip else ()
                for r in con.execute(
                    "SELECT COALESCE(NULLIF(trim(emitent), ''), '(emitent necunoscut)') emitent,"
                    " tip, count(*) acte, min(an) de_la, max(an) pana_la FROM acte"
                    f" WHERE 1 = 1{conditie} GROUP BY emitent, tip",
                    params,
                ):
                    tip_act = r["tip"] or ""
                    if not tip_acceptat(tip_act):
                        continue
                    rand = randuri.setdefault(r["emitent"], _rand_matrice(r["emitent"]))
                    rand["acte"] += r["acte"]
                    rand["_tipuri"][tip_act] = rand["_tipuri"].get(tip_act, 0) + r["acte"]
                    _adauga_rang_matrice(rand, tip_act, r["acte"])
                    ani = [x for x in (r["de_la"], r["pana_la"]) if x]
                    if ani:
                        rand["de_la"] = (
                            min([rand["de_la"], *ani]) if rand["de_la"] is not None else min(ani)
                        )
                        rand["pana_la"] = (
                            max([rand["pana_la"], *ani])
                            if rand["pana_la"] is not None
                            else max(ani)
                        )
            meta = _meta_acte(con, act_ids)
    except sqlite3.OperationalError:
        return {
            "tip": tip,
            "rang": rang_filtru,
            "domeniu": domeniu_filtru,
            "domenii": domenii_juridice.optiuni(),
            "problema": problema_filtru,
            "probleme": _probleme_matrice(),
            "sort": sortare,
            "limita": limita,
            "total": 0,
            "rezumat": {
                "emitenti": 0,
                "acte": 0,
                "viduri": len(viduri),
                "neconstitutionale": len(neconst),
                "amendamente_primite": 0,
                "initiative_in_lucru": 0,
            },
            "randuri": [],
            "limitari": ["Corpusul nu este disponibil; matricea nu poate grupa pe emitent."],
        }

    def rand_pentru(act_id: str) -> dict | None:
        m = _alege_meta(act_id, meta)
        tip_act = (m or {}).get("tip") or act_id.split("-", 1)[0]
        if not tip_acceptat(tip_act) or not domeniu_acceptat(m):
            return None
        emitent = (m or {}).get("emitent") or "(act negăsit în corpus)"
        return randuri.setdefault(emitent, _rand_matrice(emitent))

    for v in viduri:
        act_id = v.get("act_id") or ""
        rand = rand_pentru(act_id)
        if rand is None:
            continue
        rand["viduri"] += 1
        if v.get("severitate") == "blocking":
            rand["viduri_blocking"] += 1
        else:
            rand["viduri_material"] += 1
        _pune_exemplu(
            rand["_vid_exemple"],
            {
                "act_id": act_id,
                "locator": v.get("locator", ""),
                "text": v.get("text", ""),
                "instrument": v.get("instrument", ""),
                "scadenta": v.get("scadenta"),
                "zile_intarziere": v.get("zile_intarziere"),
                "severitate": v.get("severitate", ""),
                "actiuni": _actiuni_prevedere(
                    (_alege_meta(act_id, meta) or {}).get("id") or act_id,
                    v.get("locator", ""),
                ),
            },
            fel="vid",
        )

    for n in neconst:
        act_id = n.get("act_id") or ""
        rand = rand_pentru(act_id)
        if rand is None:
            continue
        rand["neconstitutionale"] += 1
        _pune_exemplu(
            rand["_neconst_exemple"],
            {
                "act_id": act_id,
                "locator": n.get("locator", ""),
                "text": n.get("text", ""),
                "decizie": n.get("decizie", ""),
                "termen": n.get("termen"),
                "zile_de_la_termen": n.get("zile_de_la_termen"),
                "severitate": n.get("severitate", ""),
                "actiuni": _actiuni_prevedere(
                    (_alege_meta(act_id, meta) or {}).get("id") or act_id,
                    n.get("locator", ""),
                ),
            },
            fel="neconst",
        )

    for act_id, cnt in amendamente.items():
        rand = rand_pentru(act_id)
        if rand is not None:
            rand["amendamente_primite"] += cnt["muchii"]
            rand["acte_amendate"] += 1

    for act_id, cnt in initiative.items():
        rand = rand_pentru(act_id)
        if rand is not None:
            rand["initiative_in_lucru"] += cnt

    iesire = []
    for rand in randuri.values():
        scor = (
            rand["viduri_blocking"] * 80
            + rand["viduri_material"] * 55
            + rand["neconstitutionale"] * 70
            + rand["initiative_in_lucru"] * 8
            + min(rand["amendamente_primite"], 200)
        )
        if rand["neconstitutionale"] or rand["viduri_blocking"]:
            nivel = "blocking"
        elif rand["viduri_material"] or rand["initiative_in_lucru"]:
            nivel = "material"
        elif rand["amendamente_primite"]:
            nivel = "note"
        else:
            nivel = "ok"
        rand_public = {
            "emitent": rand["emitent"],
            "acte": rand["acte"],
            "tipuri": [
                {"tip": t, "acte": n}
                for t, n in sorted(rand["_tipuri"].items(), key=lambda x: (-x[1], x[0]))[:8]
            ],
            "ranguri": _ranguri_matrice(rand),
            "de_la": rand["de_la"],
            "pana_la": rand["pana_la"],
            "semnale": {
                "viduri": rand["viduri"],
                "viduri_blocking": rand["viduri_blocking"],
                "viduri_material": rand["viduri_material"],
                "neconstitutionale": rand["neconstitutionale"],
                "amendamente_primite": rand["amendamente_primite"],
                "acte_amendate": rand["acte_amendate"],
                "initiative_in_lucru": rand["initiative_in_lucru"],
            },
            "scor": scor,
            "nivel": nivel,
            "exemple": {
                "viduri": rand["_vid_exemple"],
                "neconstitutionale": rand["_neconst_exemple"],
            },
            "domeniu": next(
                (d for d in domenii_juridice.optiuni() if d["cheie"] == domeniu_filtru),
                None,
            ),
            "domeniu_exemple": rand["_domeniu_exemple"],
        }
        if _filtru_problema_matrice(rand_public, problema_filtru):
            iesire.append(rand_public)

    chei = {
        "acte": lambda r: (-r["acte"], -r["scor"], r["emitent"]),
        "viduri": lambda r: (-r["semnale"]["viduri"], -r["scor"], r["emitent"]),
        "neconstitutionale": lambda r: (
            -r["semnale"]["neconstitutionale"],
            -r["scor"],
            r["emitent"],
        ),
        "initiative": lambda r: (-r["semnale"]["initiative_in_lucru"], -r["scor"], r["emitent"]),
        "amendamente": lambda r: (-r["semnale"]["amendamente_primite"], -r["scor"], r["emitent"]),
    }
    iesire.sort(key=chei.get(sortare, lambda r: (-r["scor"], -r["acte"], r["emitent"])))
    rez = {
        "emitenti": len(iesire),
        "acte": sum(r["acte"] for r in iesire),
        "ranguri": _rezumat_ranguri_matrice(iesire),
        "viduri": sum(r["semnale"]["viduri"] for r in iesire),
        "neconstitutionale": sum(r["semnale"]["neconstitutionale"] for r in iesire),
        "amendamente_primite": sum(r["semnale"]["amendamente_primite"] for r in iesire),
        "initiative_in_lucru": sum(r["semnale"]["initiative_in_lucru"] for r in iesire),
    }
    return {
        "tip": tip,
        "rang": rang_filtru,
        "domeniu": domeniu_filtru,
        "domenii": domenii_juridice.optiuni(),
        "problema": problema_filtru,
        "probleme": _probleme_matrice(),
        "sort": sortare,
        "limita": limita,
        "total": len(iesire),
        "rezumat": rez,
        "randuri": iesire[:limita],
        "limitari": [
            "Axa «arie» este emitentul scris pe document, nu o clasificare materială inventată.",
            (
                "Filtrul de domeniu este orientativ: se aplică doar când titlul sau emitentul "
                "conține un indicator cunoscut; restul rămâne «domeniu necunoscut»."
            ),
        ],
    }


def _matrice_acte(qs: dict, stare: Stare) -> dict:
    """Concrete acts behind one matrix row, with the same filters the matrix used."""
    from scripts import domenii_juridice, rang_normativ

    emitent = (qs.get("emitent", [""])[0] or "").strip()
    tip = (qs.get("tip", [""])[0] or "").strip() or None
    rang = (qs.get("rang", [""])[0] or "").strip() or None
    domeniu = (qs.get("domeniu", [""])[0] or "").strip() or None
    limita = max(1, min(_numar_qs(qs, "limita", 40), 100))
    ranguri_valide = {v[0] for v in rang_normativ.CATEGORII.values()}
    rang_filtru = rang if rang in ranguri_valide else None
    domeniu_filtru = domeniu if domeniu in domenii_juridice.chei_valide() else None
    if not emitent:
        return {
            "emitent": "",
            "tip": tip,
            "rang": rang_filtru,
            "domeniu": domeniu_filtru,
            "total": 0,
            "acte": [],
            "limitari": ["Alege un rând din matrice."],
        }

    def accepta_tip(tip_act: str | None) -> bool:
        if tip and tip_act != tip:
            return False
        return not (rang_filtru and rang_normativ.categorie(tip_act) != rang_filtru)

    try:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            conditie = " AND tip = ?" if tip else ""
            params = [emitent] + ([tip] if tip else [])
            randuri = con.execute(
                "SELECT id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
                " sursa_url, id_act_portal"
                " FROM acte"
                " WHERE COALESCE(NULLIF(trim(emitent), ''), '(emitent necunoscut)') = ?"
                f"{conditie}"
                " ORDER BY an DESC, publicat DESC, numar DESC, id DESC",
                params,
            ).fetchall()
    except sqlite3.OperationalError:
        return {
            "emitent": emitent,
            "tip": tip,
            "rang": rang_filtru,
            "domeniu": domeniu_filtru,
            "total": 0,
            "acte": [],
            "limitari": ["Corpusul nu este disponibil; actele rândului nu pot fi listate."],
        }

    acte = []
    for r in randuri:
        if not accepta_tip(r["tip"]):
            continue
        domeniu_act = domenii_juridice.clasifica(titlu=r["titlu"] or "", emitent=r["emitent"] or "")
        if domeniu_filtru and domeniu_act["cheie"] != domeniu_filtru:
            continue
        rang_act = rang_normativ.info(r["tip"])
        acte.append(
            {
                "act_id": r["id"],
                "cheie_citare": r["cheie_citare"] or r["id"],
                "tip": r["tip"],
                "numar": r["numar"],
                "an": r["an"],
                "titlu": r["titlu"],
                "publicat": r["publicat"],
                "sursa_url": depozit.url_document(r["sursa_url"], r["id_act_portal"]),
                "rang": rang_act,
                "domeniu": domeniu_act,
            }
        )
    return {
        "emitent": emitent,
        "tip": tip,
        "rang": rang_filtru,
        "domeniu": domeniu_filtru,
        "total": len(acte),
        "acte": acte[:limita],
        "limitari": [
            "Lista folosește aceleași filtre de tip, rang și domeniu ca matricea.",
            (
                "Domeniul este orientativ: apare numai când titlul sau emitentul conține un "
                "indicator cunoscut."
            ),
        ],
    }


def _matrice_contradictii(qs: dict, stare: Stare) -> dict:
    """Bounded, same-domain definition/deadline/authority candidates; never a legal verdict."""
    from scripts.contradictii_termene import termen_comparabil, termene_diferite
    from scripts.definitii import definitii
    from scripts.suprapuneri_autoritati import atributie_comparabila
    from scripts.text import cheie

    selectie = _matrice_acte({**qs, "limita": ["100"]}, stare)
    acte = selectie["acte"]
    limita = max(1, min(_numar_qs(qs, "limita", 40), 100))
    out = {
        "candidati": [],
        "acte_selectate": len(acte),
        "acte_total": selectie["total"],
        "prevederi_analizate": 0,
        "definitii_analizate": 0,
        "termene_analizate": 0,
        "atributii_analizate": 0,
        "trunchiat": selectie["total"] > len(acte),
        "limitari": [
            "Candidați neconfirmați; necesită jurist. "
            + "Diferența textuală nu dovedește contradicția.",
            "Se compară definiții, termene și atribuții din maximum 100 de acte ale rândului, "
            + "în același domeniu "
            + "orientativ cunoscut. Domeniile necunoscute sunt excluse.",
            "Limite: 1000 prevederi per act, 5000 definiții și 5000 termene comparabile; "
            + "fragmentele definițiilor pot fi scurtate.",
            "Termenele se compară doar pentru formulări identice ale obligației și "
            + "evenimentului explicit. Lunile și anii nu sunt convertiți în zile. "
            + "Excepțiile explicite și ancorele ambigue sunt excluse.",
            "Atribuții: maximum 5000 formulări comparabile; sunt excluse rolurile comune, "
            + "delegate și autoritățile locale/teritoriale. Sfera de aplicare necesită verificare.",
            "Verifică domeniul de aplicare, excepțiile, rangul și forma în vigoare; "
            + "absența candidaților nu dovedește compatibilitatea.",
            *selectie["limitari"],
        ],
    }
    grupe = {}
    grupe_termene = {}
    grupe_atributii = {}
    try:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            for act in acte:
                domeniu = act["domeniu"]["cheie"]
                if domeniu == "necunoscut":
                    continue
                rows = con.execute(
                    "SELECT locator, text FROM provizii WHERE act_id = ? ORDER BY ord LIMIT 1001",
                    (act["act_id"],),
                ).fetchall()
                out["trunchiat"] |= len(rows) > 1000
                for row in rows[:1000]:
                    out["prevederi_analizate"] += 1
                    atributie = atributie_comparabila(row["text"])
                    if atributie:
                        if out["atributii_analizate"] >= 5000:
                            out["trunchiat"] = True
                            return out
                        out["atributii_analizate"] += 1
                        grup_atributii = grupe_atributii.setdefault(
                            (domeniu, atributie.pop("cheie")), []
                        )
                        dovada_atributie = {
                            **atributie,
                            "act_id": act["act_id"],
                            "locator": row["locator"],
                            "rang": act["rang"],
                            "actiuni": _actiuni_prevedere(act["act_id"], row["locator"]),
                        }
                        for anterior in grup_atributii:
                            if anterior["act_id"] == act["act_id"] or (
                                anterior["autoritate"] == atributie["autoritate"]
                            ):
                                continue
                            if len(out["candidati"]) == limita:
                                out["trunchiat"] = True
                                return out
                            out["candidati"].append(
                                {
                                    "tip": "competenta_suprapusa",
                                    "status": "candidat_neconfirmat",
                                    "termen": atributie["actiune"] + " " + atributie["obiect"],
                                    "domeniu": act["domeniu"],
                                    "a": anterior,
                                    "b": dovada_atributie,
                                    "verificari": [
                                        "Verifică dacă responsabilitatea comună este intenționată.",
                                        "Verifică teritoriul, obiectul și sfera de aplicare.",
                                        "Verifică delegările, excepțiile și eventualele "
                                        + "redenumiri ale autorităților în formele în vigoare.",
                                    ],
                                }
                            )
                        if dovada_atributie not in grup_atributii:
                            grup_atributii.append(dovada_atributie)
                    termen_limita = termen_comparabil(row["text"])
                    if termen_limita:
                        if out["termene_analizate"] >= 5000:
                            out["trunchiat"] = True
                            return out
                        out["termene_analizate"] += 1
                        grup_termene = grupe_termene.setdefault(
                            (domeniu, termen_limita.pop("cheie")), []
                        )
                        dovada_termen = {
                            **termen_limita,
                            "act_id": act["act_id"],
                            "locator": row["locator"],
                            "rang": act["rang"],
                            "actiuni": _actiuni_prevedere(act["act_id"], row["locator"]),
                        }
                        for anterior in grup_termene:
                            if anterior["act_id"] == act["act_id"] or not termene_diferite(
                                anterior, dovada_termen
                            ):
                                continue
                            if len(out["candidati"]) == limita:
                                out["trunchiat"] = True
                                return out
                            out["candidati"].append(
                                {
                                    "tip": "termen_divergent",
                                    "status": "candidat_neconfirmat",
                                    "termen": termen_limita["responsabil"]
                                    + " "
                                    + termen_limita["actiune"],
                                    "domeniu": act["domeniu"],
                                    "a": anterior,
                                    "b": dovada_termen,
                                    "verificari": [
                                        "Verifică sfera de aplicare și excepțiile din ambele acte.",
                                        "Verifică dacă evenimentul declanșator este același "
                                        + "în fapt.",
                                        "Verifică zilele lucrătoare/calendaristice și "
                                        + "regulile de calcul; baza neprecizată nu este presupusă.",
                                    ],
                                }
                            )
                        if dovada_termen not in grup_termene:
                            grup_termene.append(dovada_termen)
                    for termen in definitii(row["text"]):
                        if out["definitii_analizate"] >= 5000:
                            out["trunchiat"] = True
                            return out
                        out["definitii_analizate"] += 1
                        dovada = {
                            "act_id": act["act_id"],
                            "locator": row["locator"],
                            "definitie": termen.definitie,
                            "rang": act["rang"],
                            "actiuni": _actiuni_prevedere(act["act_id"], row["locator"]),
                        }
                        grup = grupe.setdefault((domeniu, termen.cheia), [])
                        for anterior in grup:
                            if anterior["act_id"] == act["act_id"] or cheie(
                                anterior["definitie"]
                            ) == cheie(termen.definitie):
                                continue
                            if len(out["candidati"]) == limita:
                                out["trunchiat"] = True
                                return out
                            out["candidati"].append(
                                {
                                    "tip": "definitie_divergenta",
                                    "status": "candidat_neconfirmat",
                                    "termen": termen.termen,
                                    "domeniu": act["domeniu"],
                                    "a": anterior,
                                    "b": dovada,
                                }
                            )
                        if dovada not in grup:
                            grup.append(dovada)
    except sqlite3.OperationalError:
        out["limitari"].append("Corpus indisponibil; comparația nu a putut fi finalizată.")
        out["trunchiat"] = True
    return out


def _matrice_proiecte(qs: dict, stare: Stare) -> dict:
    from scripts.dublura import STADII_MOARTE
    from scripts.text import cheie

    selectie = _matrice_acte({**qs, "limita": ["100"]}, stare)
    tinte = {a["cheie_citare"] for a in selectie["acte"]}
    out = {
        "initiative": [],
        "tinte": sorted(tinte),
        "trunchiat": selectie["total"] > len(selectie["acte"]),
        "limitari": list(selectie["limitari"]),
    }
    if not tinte:
        return out
    try:
        with depozit.deschide(stare.initiative, readonly=True) as con:
            rows = con.execute(
                "SELECT DISTINCT i.plx_id, i.titlu, i.stadiu, i.sursa_url, i.citit_la "
                "FROM initiative i JOIN initiative_tinta t ON t.plx_id = i.plx_id "
                f"WHERE t.act_id IN ({','.join('?' for _ in tinte)}) "
                "ORDER BY i.plx_id LIMIT 501",
                sorted(tinte),
            ).fetchall()
        out["trunchiat"] |= len(rows) > 500
        out["initiative"] = [
            dict(r)
            for r in rows[:500]
            if cheie(r["stadiu"] or "") not in {"", "necunoscut", "unknown"}
            and not any(m in cheie(r["stadiu"]) for m in STADII_MOARTE)
        ]
    except sqlite3.OperationalError:
        out["limitari"].append("Registrul inițiativelor nu este disponibil.")
        out["trunchiat"] = True
    return out


def _conflicte_proiecte(cerere: dict, stare: Stare) -> dict:
    from scripts.conflicte_proiecte import MAX_TEXT, compara, operatii

    if not isinstance(cerere, dict):
        return {"error": "Cerere invalidă."}
    cerere = dict(cerere)
    provenienta = {}
    for parte in ("a", "b"):
        id = cerere.get(f"versiune_{parte}")
        if id:
            from scripts.documente_proiecte import citeste

            try:
                if not isinstance(id, str) or not isinstance(cerere.get(f"plx_{parte}"), str):
                    return {"error": "Versiune invalidă."}
                doc = citeste(stare, cerere[f"plx_{parte}"], id)
                if doc["status"] != "extras":
                    return {"error": "Documentul necesită OCR sau verificare manuală."}
                cerere[f"text_{parte}"] = doc.pop("text")
                provenienta[parte] = doc
            except (OSError, ValueError, sqlite3.Error):
                return {
                    "error": "Versiunea importată nu este disponibilă pentru această inițiativă."
                }
    for key in ("emitent", "plx_a", "plx_b", "text_a", "text_b"):
        if not isinstance(cerere.get(key), str) or not cerere[key].strip():
            return {"error": "Alege două inițiative și completează ambele texte."}
    if any(len(cerere[k]) > MAX_TEXT for k in ("text_a", "text_b")):
        return {"error": f"Maximum {MAX_TEXT} caractere pentru fiecare proiect."}
    if cerere["plx_a"] == cerere["plx_b"]:
        return {"error": "Alege două inițiative diferite."}
    qs = {
        k: [cerere[k]]
        for k in ("emitent", "tip", "rang", "domeniu", "problema")
        if isinstance(cerere.get(k), str)
    }
    selectie = _matrice_proiecte(qs, stare)
    ini = {r["plx_id"]: r for r in selectie["initiative"]}
    if any(cerere[k] not in ini for k in ("plx_a", "plx_b")):
        return {"error": "Inițiativă indisponibilă, închisă sau în afara selecției."}
    a, ta = operatii(cerere["text_a"], set(selectie["tinte"]))
    b, tb = operatii(cerere["text_b"], set(selectie["tinte"]))
    pairs, truncated = compara(a, b)
    dosar = _matrice_dosar(qs, stare)
    if not dosar["gasit"]:
        return {"error": "Rândul matricei nu este disponibil."}
    raport = {
        "candidati": [],
        "operatii_a": len(a),
        "operatii_b": len(b),
        "trunchiat": ta or tb or truncated or selectie["trunchiat"],
        "limitari": [
            "Texte furnizate de utilizator; versiunea oficială nu este verificată automat.",
            "Stadiile sunt cele colectate; verifică actualitatea lor în fișa parlamentară.",
            "Se compară maximum 200 operații pe proiect și se afișează 40 de perechi.",
            "Absența candidaților nu dovedește compatibilitatea proiectelor.",
        ],
    }
    for pair in pairs:
        x, y = pair["a"], pair["b"]
        eticheta = {
            "abrogare_modificare": "Abrogare / modificare",
            "numerotare_dublata": "Numerotare dublată",
            "inlocuiri_diferite": "Înlocuiri diferite",
        }[pair["tip"]]
        c = {
            "tip": pair["tip"],
            "status": "candidat_neconfirmat",
            "termen": f"{eticheta}: {x['act_tinta']}",
            "domeniu": {"eticheta": "proiecte parlamentare"},
            "tinta": {
                "act_id": x["act_tinta"],
                "locator": x["locator"],
                "actiuni": _actiuni_prevedere(x["act_tinta"], x["locator"]),
            },
        }
        for parte, op in (("a", x), ("b", y)):
            meta = ini[cerere[f"plx_{parte}"]]
            c[parte] = {
                **op,
                "act_id": meta["plx_id"],
                "stadiu": meta["stadiu"],
                "citit_la": meta["citit_la"],
                "sursa_url": meta["sursa_url"],
                "actiuni": [],
            }
            if parte in provenienta:
                c[parte]["versiune_id"] = provenienta[parte]["id"]
        raport["candidati"].append(c)
    dosar["conflicte_proiecte"] = raport
    raport["documente"] = provenienta
    if provenienta:
        raport["limitari"][0] = (
            "Versiunile importate sunt identificate prin sursă și SHA-256; "
            "restul textelor sunt furnizate de utilizator. Extragerea necesită verificare."
        )
    dosar["markdown"] = _markdown_dosar_matrice(dosar)
    return dosar


def _prima(qs: dict, cheie: str, default: str = "") -> str:
    return str(qs.get(cheie, [default])[0] or default)


def _referinte_ue_dosar(stare: Stare, act_ids: set[str], limita: int = 20) -> list[dict]:
    if not act_ids:
        return []
    try:
        raport = _acoperire_ue({"limita": ["500"]}, stare)
    except sqlite3.Error:
        return []
    iesire = []
    for ref in raport.get("referinte") or []:
        exemple = [
            e
            for e in ref.get("exemple") or []
            if e.get("sursa") == "corpus" and e.get("id") in act_ids
        ]
        if not exemple:
            continue
        rand = dict(ref)
        rand["exemple"] = exemple[:3]
        iesire.append(rand)
        if len(iesire) >= limita:
            break
    return iesire


def _pasi_dosar_matrice(rand: dict, problema: str | None, referinte_ue: list[dict]) -> list[str]:
    semnale = rand.get("semnale") or {}
    pasi = ["Pornește de la actele listate; fiecare constatare trebuie legată de o prevedere."]
    if problema in (None, "semnale", "viduri", "viduri_blocking") and semnale.get("viduri"):
        pasi.append(
            "Pentru lacune: verifică obligația, termenul și instrumentul lipsă, apoi notează "
            "autoritatea care trebuia să adopte actul."
        )
    if problema in (None, "semnale", "neconstitutionale") and semnale.get("neconstitutionale"):
        pasi.append(
            "Pentru CCR: compară textul actual cu decizia și marchează dacă reparația lipsește "
            "sau doar nu a fost legată în corpus."
        )
    if problema in (None, "semnale", "initiative") and semnale.get("initiative_in_lucru"):
        pasi.append(
            "Pentru inițiative: verifică PL-x-urile pendinte înainte de a propune text nou."
        )
    if problema in (None, "semnale", "amendamente") and semnale.get("amendamente_primite"):
        pasi.append(
            "Pentru amendări: verifică dacă intervențiile repetate indică instabilitate reală."
        )
    if referinte_ue:
        pasi.append("Pentru UE: importă CELEX-urile lipsă și verifică prevederile candidate.")
    return pasi


def _markdown_dosar_matrice(dosar: dict) -> str:
    rand = dosar.get("rand") or {}
    semnale = rand.get("semnale") or {}
    linii = [
        f"# Dosar matrice: {dosar.get('emitent') or ''}",
        "",
        f"Problemă: {dosar.get('problema_eticheta') or 'toate'}",
        f"Acte în rând: {semnale.get('acte') or rand.get('acte') or 0}",
        (
            "Semnale: "
            f"{semnale.get('viduri', 0)} lacune, "
            f"{semnale.get('neconstitutionale', 0)} CCR, "
            f"{semnale.get('initiative_in_lucru', 0)} inițiative, "
            f"{semnale.get('amendamente_primite', 0)} amendări"
        ),
        "",
        "## Pași",
        *[f"- {p}" for p in dosar.get("pasi") or []],
    ]
    if dosar.get("referinte_ue"):
        linii += ["", "## Referințe UE"]
        for ref in dosar["referinte_ue"]:
            stare = "importat" if ref.get("importat") else "lipsește"
            linii.append(f"- {ref.get('celex')} ({stare}) — {ref.get('mentionari', 0)} menționări")
    contradictii = dosar.get("contradictii") or {}
    linii += ["", "## Contradicții candidate (neconfirmate; necesită jurist)"]
    for c in contradictii.get("candidati", []):
        linii.append(f"- {c['termen']} ({c['domeniu']['eticheta']})")
        for parte in ("a", "b"):
            d = c[parte]
            linii.append(
                f"  - {d['act_id']} / {d['locator']}: {d.get('text') or d.get('definitie', '')}"
            )
            if c["tip"] == "termen_divergent":
                linii.append(f"    Termen: {d['termen_text']} (bază: {d['baza']})")
            if c["tip"] == "competenta_suprapusa":
                linii.append(f"    Autoritate: {d['autoritate']}")
        linii.extend(f"  - {v}" for v in c.get("verificari", []))
    if contradictii.get("trunchiat"):
        linii.append("Rezultate parțiale: limita de analiză sau afișare a fost atinsă.")
    linii.extend(contradictii.get("limitari", []))
    proiecte = dosar.get("conflicte_proiecte") or {}
    if proiecte:
        linii += ["", "## Conflicte între proiecte (neconfirmate)"]
        for parte, doc in proiecte.get("documente", {}).items():
            linii.append(
                f"Proiect {parte.upper()}: {doc['url']} | {doc['preluat_la']} | "
                f"SHA-256: {doc['sha256']}"
            )
        for c in proiecte["candidati"]:
            linii.append(f"- {c['termen']}")
            for parte in ("a", "b"):
                d = c[parte]
                linii.append(
                    f"  - {d['act_id']} ({d['stadiu']}; {d['citit_la']}): "
                    f"{d['act_tinta']} / {d['locator']}: {d['text']}"
                )
        if proiecte["trunchiat"]:
            linii.append("Rezultate parțiale: limita de analiză sau afișare a fost atinsă.")
        linii.extend(proiecte["limitari"])
    return "\n".join(linii).strip()


def _matrice_dosar(qs: dict, stare: Stare) -> dict:
    emitent = _prima(qs, "emitent").strip()
    tip = _prima(qs, "tip").strip()
    rang = _prima(qs, "rang").strip()
    domeniu = _prima(qs, "domeniu").strip()
    problema = _prima(qs, "problema").strip()
    limita_acte = max(1, min(_numar_qs(qs, "limita", 80), 100))
    if not emitent:
        return {
            "gasit": False,
            "emitent": "",
            "rand": None,
            "acte": {"total": 0, "acte": []},
            "referinte_ue": [],
            "pasi": [],
            "markdown": "",
            "limitari": ["Alege un rând din matrice pentru dosar."],
        }

    matrix_qs = {"limita": ["200"], "sort": [_prima(qs, "sort", "semnale") or "semnale"]}
    for cheie, valoare in (
        ("tip", tip),
        ("rang", rang),
        ("domeniu", domeniu),
        ("problema", problema),
    ):
        if valoare:
            matrix_qs[cheie] = [valoare]
    matrice = _matrice(matrix_qs, stare)
    rand = next((r for r in matrice.get("randuri") or [] if r.get("emitent") == emitent), None)
    if not rand:
        return {
            "gasit": False,
            "emitent": emitent,
            "tip": matrice.get("tip"),
            "rang": matrice.get("rang"),
            "domeniu": matrice.get("domeniu"),
            "problema": matrice.get("problema"),
            "problema_eticheta": "",
            "rand": None,
            "acte": {"total": 0, "acte": []},
            "referinte_ue": [],
            "pasi": [],
            "markdown": "",
            "limitari": [
                "Rândul nu există pentru filtrele curente.",
                *list(matrice.get("limitari") or []),
            ],
        }

    acte_qs = {"emitent": [emitent], "limita": [str(limita_acte)]}
    for cheie, valoare in (("tip", tip), ("rang", rang), ("domeniu", domeniu)):
        if valoare:
            acte_qs[cheie] = [valoare]
    acte = _matrice_acte(acte_qs, stare)
    act_ids = {a.get("act_id") or "" for a in acte.get("acte") or []}
    referinte_ue = _referinte_ue_dosar(stare, act_ids)
    problema_eticheta = next(
        (
            p["eticheta"]
            for p in matrice.get("probleme") or []
            if p["cheie"] == matrice.get("problema")
        ),
        "",
    )
    dosar = {
        "gasit": True,
        "emitent": emitent,
        "tip": matrice.get("tip"),
        "rang": matrice.get("rang"),
        "domeniu": matrice.get("domeniu"),
        "problema": matrice.get("problema"),
        "problema_eticheta": problema_eticheta,
        "rand": rand,
        "acte": acte,
        "referinte_ue": referinte_ue,
        "contradictii": _matrice_contradictii(acte_qs, stare),
        "pasi": _pasi_dosar_matrice(rand, matrice.get("problema"), referinte_ue),
        "limitari": [
            "Dosarul este o listă de lucru, nu un verdict juridic.",
            *list(matrice.get("limitari") or []),
            *list(acte.get("limitari") or []),
        ],
    }
    dosar["markdown"] = _markdown_dosar_matrice(dosar)
    return dosar


LIMITARE_UE = (
    "Potrivirile UE sunt căutare textuală în actele CELEX importate local; "
    "nu sunt verdict de conformitate."
)


def _limita_ue(valoare) -> int:
    try:
        return max(1, min(int(valoare), 50))
    except (TypeError, ValueError):
        return 12


def _limba_ue(valoare) -> str | None:
    limba = str(valoare or "").strip().upper()
    return limba if re.fullmatch(r"[A-Z]{3}", limba) else None


def _schema_ue(con: sqlite3.Connection) -> bool:
    tabele = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE name IN"
            " ('eu_acte', 'eu_provizii', 'eu_provizii_fts')"
        )
    }
    return {"eu_acte", "eu_provizii", "eu_provizii_fts"} <= tabele


def _rezumat_ue(stare: Stare) -> dict:
    zero = {"ue_disponibil": False, "ue_acte": 0, "ue_prevederi": 0, "ue_limbi": []}
    if not stare.are_ue():
        return zero

    from scripts import cellar

    try:
        with cellar.deschide(stare.eu, readonly=True) as con:
            if not _schema_ue(con):
                return zero
            limbi = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT limba FROM eu_acte WHERE limba IS NOT NULL ORDER BY limba"
                )
            ]
            return {
                "ue_disponibil": True,
                "ue_acte": con.execute("SELECT count(*) FROM eu_acte").fetchone()[0],
                "ue_prevederi": con.execute("SELECT count(*) FROM eu_provizii").fetchone()[0],
                "ue_limbi": limbi,
            }
    except sqlite3.Error:
        return zero


def _dosare_ue(rezultate: list[dict]) -> list[dict]:
    dosare: dict[str, dict] = {}
    for rand in rezultate:
        celex = rand.get("celex") or ""
        if not celex:
            continue
        dosar = dosare.setdefault(
            celex,
            {
                "celex": celex,
                "titlu": rand.get("act_titlu") or "",
                "limba": rand.get("limba") or "",
                "sursa_url": rand.get("sursa_url") or "",
                "item_url": rand.get("item_url") or "",
                "prevederi": 0,
                "articole": 0,
                "considerente": 0,
                "anexe": 0,
                "locatori": [],
                "termeni": [],
                "feluri": {},
                "scor": rand.get("scor"),
            },
        )
        dosar["prevederi"] += 1
        fel = rand.get("fel") or ""
        dosar["feluri"][fel] = dosar["feluri"].get(fel, 0) + 1
        if fel == "articol":
            dosar["articole"] += 1
        elif fel == "considerent":
            dosar["considerente"] += 1
        elif fel == "anexa":
            dosar["anexe"] += 1
        locator = rand.get("locator") or ""
        if locator and locator not in dosar["locatori"] and len(dosar["locatori"]) < 8:
            dosar["locatori"].append(locator)
        for termen in rand.get("termeni") or []:
            if termen not in dosar["termeni"]:
                dosar["termeni"].append(termen)
        scor = rand.get("scor")
        if scor is not None and (dosar["scor"] is None or scor < dosar["scor"]):
            dosar["scor"] = scor

    iesire = []
    for dosar in dosare.values():
        dosar["feluri"] = [
            {"fel": fel, "prevederi": n}
            for fel, n in sorted(dosar["feluri"].items(), key=lambda x: (-x[1], x[0]))
            if fel
        ]
        iesire.append(dosar)
    return iesire


def _referinte_ue(text: str) -> list[dict]:
    from scripts.referinte_ue import referinte_dict

    return referinte_dict(text)


def _celex_importate_ue(con: sqlite3.Connection, referinte: list[dict]) -> set[str]:
    celexuri = {r.get("celex") for r in referinte if r.get("celex")}
    gasite: set[str] = set()
    for bucata in _bucati(celexuri):
        marci = ",".join("?" * len(bucata))
        for rand in con.execute(f"SELECT celex FROM eu_acte WHERE celex IN ({marci})", bucata):
            gasite.add(rand["celex"])
    return gasite


def _fragment_ue(text: str, limita: int = 360) -> str:
    fragment = re.sub(r"\s+", " ", text or "").strip()
    if len(fragment) <= limita:
        return fragment
    return fragment[: limita - 1].rstrip() + "…"


def _prevederi_ue_referite(
    con: sqlite3.Connection,
    referinte: list[dict],
    *,
    limita: int,
    limba: str | None,
) -> tuple[list[dict], list[dict]]:
    if not referinte:
        return [], []

    importate = _celex_importate_ue(con, referinte)
    neimportate = [r for r in referinte if r.get("celex") not in importate]
    if not importate:
        return [], neimportate

    referinte_pe_celex: dict[str, list[dict]] = {}
    for ref in referinte:
        celex = ref.get("celex") or ""
        if celex in importate:
            referinte_pe_celex.setdefault(celex, []).append(ref)

    rezultate: list[dict] = []
    ordine = list(referinte_pe_celex)
    for celex in ordine:
        if len(rezultate) >= limita:
            break
        params: list[object] = [celex]
        clauza_limba = ""
        if limba:
            clauza_limba = " AND p.limba = ?"
            params.append(limba)
        randuri = con.execute(
            "SELECT p.celex, p.locator, p.fel, p.titlu, p.text, p.limba,"
            " a.titlu AS act_titlu, a.sursa_url, a.item_url"
            " FROM eu_provizii p"
            " JOIN eu_acte a ON a.celex = p.celex"
            f" WHERE p.celex = ?{clauza_limba}"
            " ORDER BY p.ord LIMIT ?",
            (*params, min(4, limita - len(rezultate))),
        ).fetchall()
        for r in randuri:
            rezultate.append(
                {
                    "celex": r["celex"],
                    "locator": r["locator"],
                    "fel": r["fel"],
                    "titlu": r["titlu"] or "",
                    "limba": r["limba"],
                    "act_titlu": r["act_titlu"] or "",
                    "sursa_url": r["sursa_url"] or "",
                    "item_url": r["item_url"] or "",
                    "fragment": _fragment_ue(r["text"]),
                    "scor": None,
                    "termeni": [],
                    "potrivire": "referinta",
                    "referinte": referinte_pe_celex[celex],
                }
            )
    return rezultate, neimportate


def _imbina_rezultate_ue(exacte: list[dict], textuale: list[dict], limita: int) -> list[dict]:
    rezultate: list[dict] = []
    vazute: set[tuple[str, str, str]] = set()
    for rand in [*exacte, *textuale]:
        cheie = (rand.get("celex") or "", rand.get("locator") or "", rand.get("limba") or "")
        if cheie in vazute:
            continue
        vazute.add(cheie)
        rezultate.append(rand)
        if len(rezultate) >= limita:
            break
    return rezultate


def _ue(draft: str, stare: Stare, *, limita=12, limba=None) -> dict:
    """Candidate EU provisions, from the local CELEX database.

    This is retrieval, not compatibility analysis: it finds official EU provisions that use the
    same legal terms as the draft and sends every row back with a CELEX locator and source link.
    The caller can then decide whether the draft conflicts, derogates or merely touches the same
    matter.
    """
    text = (draft or "").strip()
    limita_i = _limita_ue(limita)
    limba_filtru = _limba_ue(limba)
    referinte = _referinte_ue(text)
    from scripts import triage_ue

    semnale = triage_ue.semnale_draft(text, referinte)
    if not text:
        return {
            "sursa": "eu.db",
            "limba": limba_filtru,
            "total": 0,
            "dosare": [],
            "rezultate": [],
            "referinte": referinte,
            "referinte_neimportate": [],
            "semnale": semnale,
            "matrice": triage_ue.matrice_analiza([], [], semnale, referinte=referinte),
            "limitari": ["Textul proiectului este gol.", LIMITARE_UE],
        }
    if not stare.are_ue():
        triage_ue.aplica_triere_lipsa(referinte)
        return {
            "sursa": "absent",
            "limba": limba_filtru,
            "total": 0,
            "dosare": [],
            "rezultate": [],
            "referinte": referinte,
            "referinte_neimportate": referinte,
            "semnale": semnale,
            "matrice": triage_ue.matrice_analiza([], referinte, semnale, referinte=referinte),
            "limitari": [
                "Dreptul UE nu este încărcat local; importă acte CELEX în eu.db cu "
                "`uv run python -m scripts.cellar 32018R1805 --db eu.db`.",
                LIMITARE_UE,
            ],
        }

    from scripts import cellar

    try:
        with cellar.deschide(stare.eu, readonly=True) as con:
            if not _schema_ue(con):
                triage_ue.aplica_triere_lipsa(referinte)
                return {
                    "sursa": "eu.db",
                    "limba": limba_filtru,
                    "total": 0,
                    "dosare": [],
                    "rezultate": [],
                    "referinte": referinte,
                    "referinte_neimportate": referinte,
                    "semnale": semnale,
                    "matrice": triage_ue.matrice_analiza(
                        [], referinte, semnale, referinte=referinte
                    ),
                    "limitari": [
                        "eu.db există, dar nu are indexul de prevederi UE; rulează importul CELEX "
                        "sau reindexarea cu "
                        "`uv run python -m scripts.cellar --indexeaza --db eu.db`.",
                        LIMITARE_UE,
                    ],
                }
            exacte, neimportate = _prevederi_ue_referite(
                con, referinte, limita=limita_i, limba=limba_filtru
            )
            textuale = cellar.cauta_ue(con, text, limita=limita_i, limba=limba_filtru)
            for rand in textuale:
                rand.setdefault("potrivire", "text")
            rezultate = _imbina_rezultate_ue(exacte, textuale, limita_i)
            triage_ue.aplica_triere(rezultate)
            triage_ue.aplica_triere_lipsa(neimportate)
    except sqlite3.Error as e:
        triage_ue.aplica_triere_lipsa(referinte)
        return {
            "sursa": "eu.db",
            "limba": limba_filtru,
            "total": 0,
            "dosare": [],
            "rezultate": [],
            "referinte": referinte,
            "referinte_neimportate": referinte,
            "semnale": semnale,
            "matrice": triage_ue.matrice_analiza([], referinte, semnale, referinte=referinte),
            "limitari": [f"eu.db nu a putut fi citit: {e}", LIMITARE_UE],
        }

    limitari = (
        [LIMITARE_UE]
        if rezultate
        else [
            "Nu s-au găsit prevederi UE candidate pentru termenii din text.",
            LIMITARE_UE,
        ]
    )
    if neimportate:
        ids = ", ".join(sorted({r["celex"] for r in neimportate}))
        limitari = [f"Acte UE citate explicit, dar neimportate local în eu.db: {ids}.", *limitari]

    return {
        "sursa": "eu.db",
        "limba": limba_filtru,
        "total": len(rezultate),
        "dosare": _dosare_ue(rezultate),
        "rezultate": rezultate,
        "referinte": referinte,
        "referinte_neimportate": neimportate,
        "semnale": semnale,
        "matrice": triage_ue.matrice_analiza(rezultate, neimportate, semnale, referinte=referinte),
        "limitari": limitari,
    }


def _raport_acoperire_ue(stare: Stare, limita: int) -> dict:
    if stare.are_rapoarte:
        brut = stare._incarca_raport("ue_acoperire.json")
        if isinstance(brut, dict) and isinstance(brut.get("referinte"), list):
            out = dict(brut)
            out["sursa"] = "raport"
            out["referinte"] = brut["referinte"]
            return out

    from scripts.acoperire_ue import raport

    return raport(stare.corpus, stare.initiative, stare.eu, limita=limita)


def _acoperire_ue(qs: dict, stare: Stare) -> dict:
    limita = _numar_qs(qs, "limita", 50)
    out = _raport_acoperire_ue(stare, limita)
    out["referinte"] = out.get("referinte", [])[:limita]
    return out


def _import_queue_ue(qs: dict, stare: Stare) -> dict:
    limita = max(1, min(_numar_qs(qs, "limita", 50), 200))
    acoperire = _raport_acoperire_ue(stare, max(limita, 100))
    limbi = qs.get("limbi", ["RON,ENG"])[0]

    from scripts.import_queue_ue import coada_import

    return coada_import(
        acoperire,
        stare.eu,
        limita=limita,
        limbi=limbi,
        sursa=acoperire.get("sursa", "calculat"),
    )


def _vid_dict(v) -> dict:
    """One `vid.Vid` finding as a plain dict for the UI / the shipped report."""
    ob = v.obligatie
    return {
        "act_id": ob.act.id if ob.act else "",
        "locator": ob.locator.id if ob.locator else "",
        "text": ob.text[:300],
        "instrument": ob.tip_asteptat,
        "scadenta": v.scadenta.isoformat() if v.scadenta else None,
        "zile_intarziere": v.zile_intarziere,
        "severitate": v.severitate,
        "cautat": v.cautat,
        "candidati": list(v.candidati),
        "limitari": list(v.limitari),
    }


def construieste_vid(corpus_db: str, graf_db: str, limita: int | None = None) -> list[dict]:
    """Build the shipped unmet-obligations report from a corpus + its graph.

    `complet_pentru` is left empty on purpose: a shipped slice (or a still-collecting corpus) cannot
    vouch that any instrument type was gathered exhaustively, so every finding is `blocking` and
    says on its face it cannot tell a legislative gap from a gap in the collection. That is the
    honest default until a finished collection earns a stronger claim (see `vid_corpus.py`)."""
    import re

    from scripts.vid_corpus import raport_vid

    # Drop findings whose "obligation" is really a consolidation annotation the extractor caught
    # from the amending-history block (`(la 13-07-2020, … a fost completat de …)`) — it is not a
    # delegated norm, and showing it as an unmet obligation would be noise, not a finding.
    nota = re.compile(r"^\(la \d{2}-\d{2}-\d{4}")
    vids = raport_vid(corpus_db, graf_db, complet_pentru=frozenset(), limita=limita)
    return [_vid_dict(v) for v in vids if not nota.match(v.obligatie.text.strip())]


def _nereparat_dict(n, norma=None, temeiuri: list[dict] | None = None) -> dict:
    """One `neconstitutional.Nereparat` row as a plain dict for the shipped register.

    `severitate` travels as the register means it — *evidential*: `blocking` says the corpus
    cannot tell an unrepaired provision from a repair it never collected. `coliziune.py` reads it
    that way and refuses to let such a row block a bill. It is not the linter's severity and must
    not be rendered as one.

    `norma` is the recovered text of the struck provision (`prevedere.py`), when the corpus can
    produce it. `text` is only the citation the decision used — `art. 5 alin. (7) din Legea nr.
    59/1993`, a median of 24 characters — which identifies the provision and does not show anyone
    what was actually struck. Two thirds of the register can be quoted; the rest ships without,
    and `norma_granularitate` says which, because a row quoting the containing article must not
    look like one quoting the paragraph.
    """
    p = n.lovitura.proviziune
    rand = {
        "act_id": p.act or "",
        "locator": p.locator or "",
        "fel": p.fel,
        "text": p.text[:300],
        "decizie": n.lovitura.decizie,
        "publicat": n.lovitura.publicat.isoformat() if n.lovitura.publicat else None,
        "definitiva": n.lovitura.definitiva,
        "termen": n.termen.isoformat() if n.termen else None,
        "zile_de_la_termen": n.zile_de_la_termen,
        "severitate": n.severitate,
        "limitari": list(n.limitari),
        "norma": "",
        "norma_granularitate": "",
        "norma_nota": "",
        # On what constitutional ground it fell — the part of a strike that transfers to a rule
        # somebody is writing now.
        "temeiuri": temeiuri or [],
    }
    if norma is not None:
        rand |= {
            "norma": norma.text.strip()[:4000],
            "norma_granularitate": norma.granularitate,
            "norma_nota": norma.nota,
        }
    return rand


def _temeiuri_decizie(cx, id_portal: str, publicat: str | None) -> list[dict]:
    """On what constitutional ground a decision struck — read once per decision, then cached.

    The ground is the part of a strike that *transfers*. That art. 224 of the old Penal Code fell
    is a fact about that article; that it fell on equality grounds is something a drafter can use
    on a rule they are writing today.

    Cached because a provision struck by four decisions asks for the same reasoning four times, and
    reading the considerente means a regex pass over a document that runs to 12 000 characters at
    the median.
    """
    from scripts.temeiuri import temeiuri

    memo = getattr(_temeiuri_decizie, "_memo", None)
    if memo is None:
        memo = _temeiuri_decizie._memo = {}
    if id_portal in memo:
        return memo[id_portal]

    rand = cx.execute("SELECT text FROM documente WHERE id_portal = ?", (id_portal,)).fetchone()
    iesire: list[dict] = []
    if rand and rand[0]:
        la_data = None
        if publicat:
            try:
                la_data = date.fromisoformat(publicat[:10])
            except ValueError:
                la_data = None
        iesire = [
            {
                "articol": t.articol,
                "alineate": list(t.alineate),
                "fel": t.fel,
                "nume": t.nume,
                "eticheta": t.eticheta,
                "citat": t.text,
                "incredere": t.increderea,
            }
            for t in temeiuri(rand[0], la_data)
        ]
    memo[id_portal] = iesire
    return iesire


def construieste_considerente(corpus_db: str, *, fereastra: int = 2400) -> dict[str, str]:
    """An excerpt of each striking decision's reasoning, keyed by decision.

    Shipped **separately** from the register and the norms, because only the model pass reads it
    and that pass needs a model. The offline bundle should not carry the cost of a feature that
    does nothing without one.

    Excerpted, not whole: the considerente run to 12 000 characters at the median and 898 000 at
    the worst, and they open with the recital of procedure and the parties' submissions — so the
    first N characters of a decision are reliably the least useful N characters in it. The window
    is cut around the Court's own statement of violation, which `temeiuri.py` already located.
    """
    import sqlite3

    from scripts.temeiuri import considerente as taie_considerente
    from scripts.temeiuri import temeiuri as citeste_temeiuri

    cx = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        randuri = cx.execute(
            "SELECT DISTINCT l.cheie_act, l.id_portal, l.publicat FROM lovituri l"
        ).fetchall()
        iesire: dict[str, str] = {}
        for cheie_act, id_portal, publicat in randuri:
            if cheie_act in iesire:
                continue
            doc = cx.execute(
                "SELECT text FROM documente WHERE id_portal = ?", (id_portal,)
            ).fetchone()
            if not doc or not doc[0]:
                continue
            cons = re.sub(r"\s+", " ", taie_considerente(doc[0])).strip()
            la_data = _data(publicat)
            grounds = citeste_temeiuri(doc[0], la_data)
            incalcate = [t for t in grounds if t.fel == "incalcat"]
            ancora = (incalcate or grounds or [None])[0]
            pozitie = -1
            if ancora is not None:
                pozitie = cons.find(re.sub(r"\s+", " ", ancora.text).strip()[:60])
            start = max(0, pozitie - fereastra // 3) if pozitie >= 0 else 0
            # Snap to word boundaries: an excerpt that opens mid-word reads as corrupted text, and
            # the model is being asked to quote from it verbatim.
            if start:
                spatiu = cons.find(" ", start)
                start = spatiu + 1 if 0 <= spatiu < start + 40 else start
            taiat = cons[start : start + fereastra]
            if len(cons) > start + fereastra:
                taiat = taiat[: taiat.rfind(" ")] if " " in taiat else taiat
            if taiat:
                iesire[cheie_act] = taiat
        return iesire
    finally:
        cx.close()


def construieste_norme_lovite(corpus_db: str) -> list[dict]:
    """The wording of every struck provision the corpus can quote — the Tier 2 comparison set.

    **Every strike, not only the unrepaired ones.** `neconstitutional.json` answers "was it put
    right", which is the question for a draft that *cites* the provision. Re-enactment is a
    different question: article 147 (4) binds erga omnes, so passing the struck wording again is
    caught by the original decision whether or not the original text was later repaired. A register
    filtered to unrepaired rows would miss exactly the case where Parliament fixed the old law and
    then wrote the same rule into a new one.

    Keyed on the *resolved* unit, so a provision struck by four decisions contributes one norm
    rather than four — otherwise a draft matching it reports four identical findings, and the norm
    becomes its own nearest neighbour in any calibration run over this set.
    """
    import sqlite3

    from scripts.lovituri import extrage
    from scripts.prevedere import Prevedere, textul, versiuni

    # Strikes are read, not re-derived — but a corpus that has never been extracted has an empty
    # table, and reading it would ship an empty comparison set that looks exactly like "no
    # provision was ever struck". Same fallback `neconstitutional.din_baze` makes, for the same
    # reason: extract once, slowly, and say so.
    cx = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        gol = cx.execute("SELECT count(*) FROM lovituri").fetchone()[0] == 0
        neexaminate = cx.execute(
            "SELECT count(*) FROM documente WHERE lovituri_extrase IS NULL"
            " AND emitent LIKE 'Curtea Constitu%' AND tip = 'decizie'"
        ).fetchone()[0]
    finally:
        cx.close()
    if gol and neexaminate:
        extrage(corpus_db)

    cx = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        index = versiuni(cx)
        randuri = cx.execute(
            "SELECT act, locator, publicat, cheie_act, id_portal FROM lovituri"
            " WHERE act IS NOT NULL AND locator != '' ORDER BY publicat, cheie_act"
        ).fetchall()
        pe_unitate: dict[tuple[str, str], dict] = {}
        for act, locator, publicat, decizie, id_portal in randuri:
            an = int(publicat[:4]) if publicat else None
            p = textul(cx, act, locator, an, index)
            if not isinstance(p, Prevedere):
                continue
            cheie = (p.act_gasit, p.locator_gasit)
            if cheie in pe_unitate:
                continue
            pe_unitate[cheie] = {
                "act_id": p.act_gasit,
                "locator": p.locator_gasit,
                "locator_cerut": p.locator,
                "decizie": decizie,
                "publicat": publicat,
                "norma": p.text.strip()[:4000],
                "norma_granularitate": p.granularitate,
                "norma_nota": p.nota,
                "temeiuri": _temeiuri_decizie(cx, id_portal, publicat),
            }
        return list(pe_unitate.values())
    finally:
        cx.close()


def _gasiri_pentru_opinie(draft: str, stare: Stare) -> list[dict]:
    """The deterministic findings, each with the reasoning behind its decision attached."""
    cons = stare.considerente()
    iesire: list[dict] = []
    for g in [*_neconstitutional(draft, stare), *_reluare(draft, stare)["gasite"]]:
        decizie = g.get("decizie") or ""
        if decizie and cons.get(decizie):
            iesire.append({**g, "considerente": cons[decizie]})
    return iesire


def _opinie_cerere(draft: str, stare: Stare) -> dict:
    """The prompt for a model the caller runs itself — the browser's half of the two-step.

    WebLLM is JavaScript and the validator is Python, so the tab asks for the prompt, runs it, and
    posts the reply back. The context is not returned for the client to send back: it is recomputed
    when the reply arrives, because a client that could supply the context could supply one
    containing its own hallucination.
    """
    from scripts.opinie import cerere

    prompt, context = cerere(draft, _gasiri_pentru_opinie(draft, stare))
    if not prompt:
        return {
            "are_prompt": False,
            "motiv": "niciun considerent disponibil pentru deciziile găsite",
            "prompt": "",
            "decizii": [],
        }
    return {"are_prompt": True, "motiv": "", "prompt": prompt, "decizii": sorted(context)}


def _opinie(draft: str, stare: Stare, model=None, brut: str | None = None) -> dict:
    """Whether the draft has the defect the Court found — the one pass that needs a model.

    Retrieval is already done: the context is assembled from the deterministic findings, so the
    model reasons over a fixed dictionary and never searches. `validare.valideaza` then drops
    anything citing outside it.

    Runs on-device or not at all. The draft is an unpublished bill and the page's CSP is written so
    it cannot be sent anywhere; the existing cloud path carries public law text only. A local
    endpoint or WebLLM in the tab is the whole of the supported surface, which is a real limit and
    the right one.
    """
    from scripts.opinie import opinie

    o = opinie(draft, _gasiri_pentru_opinie(draft, stare), model=model, brut=brut)
    return {
        "a_rulat": o.a_rulat,
        "motiv": o.motiv,
        "experimental": True,
        "severitate": o.severitate,
        "incredere": o.increderea,
        "rata_de_respingere": round(o.rata_de_respingere, 3),
        "decizii_trimise": sorted(o.context),
        "acceptate": [
            {
                "decizie": c.provizie,
                "citat": c.citat,
                "motiv": c.motiv,
                "fragment": c.fragment_proiect,
            }
            for c in o.acceptate
        ],
        "respinse": [
            {"decizie": getattr(r.constatare, "provizie", "") or "", "motiv": r.explicatie}
            for r in o.respinse
        ],
    }


def _reluare(draft: str, stare: Stare) -> dict:
    """Where the draft's wording re-enacts a struck provision, with what it was checked against.

    The coverage travels with the findings rather than beside them: an empty list means "nothing
    matched among the N provisions I can quote", and on the same screen that is indistinguishable
    from "there was nothing to match against" unless the answer says which.
    """
    from scripts.reluare import acoperire, reluari

    gasite = reluari(draft, stare.norme_lovite)
    return {
        "acoperire": acoperire(stare.norme_lovite),
        "gasite": [
            {
                "unitate": r.unitate,
                "text": r.text[:400],
                "act_id": r.act_id,
                "locator": r.locator,
                "decizie": r.decizie,
                "publicat": r.publicat,
                "scor": round(r.scor, 3),
                "suprapunere": round(r.suprapunere, 3),
                "aproape_identic": r.aproape_identic,
                "granularitate": r.granularitate,
                "norma": r.norma[:400],
                "severitate": r.severitate,
                "motiv": r.motiv,
                "temeiuri": list(r.temeiuri),
                "incredere": r.increderea,
            }
            for r in gasite
        ],
    }


def construieste_neconstitutional(
    corpus_db: str,
    graf_db: str,
    *,
    complet_pentru: frozenset[str] = frozenset(),
    la_data: date | None = None,
) -> list[dict]:
    """Build the shipped struck-but-unrepaired register from a corpus + its graph.

    `complet_pentru` is empty by default for the same reason it is in `construieste_vid`: a
    shipped slice cannot vouch that any act type was collected exhaustively, so every row comes
    back evidentially `blocking` and says so on its face. That default is deliberately expensive —
    with nothing declared complete, no finding this feeds can ever block a draft, only warn. It is
    a dial an operator turns by declaring what they actually finished collecting, not a default
    that flatters the data.
    """
    import sqlite3

    from scripts.neconstitutional import din_baze, registru
    from scripts.prevedere import Prevedere, textul, versiuni

    lovituri, muchii, tipuri = din_baze(corpus_db, graf_db)
    randuri = registru(
        lovituri,
        muchii,
        tipuri,
        la_data=la_data or date.today(),
        complet_pentru=complet_pentru,
    )

    # The struck text is recovered here, at build time, and travels in the report — so the browser
    # can show what the Court removed without holding the corpus it was cut out of. One connection
    # and one version index for the whole register, not one per row.
    cx = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        index = versiuni(cx)
        # `Lovitura` carries the decision's citation key, and resolving a decision by citation key
        # is the collision `documente` exists to prevent — `decizie-5-1996` names a Court decision
        # no better than an agency's. `lovituri` holds both keys for rows that are Court decisions
        # by construction, so this map is exact rather than a lookup by name.
        pe_cheie = dict(cx.execute("SELECT DISTINCT cheie_act, id_portal FROM lovituri").fetchall())
        iesire = []
        for n in randuri:
            p = n.lovitura.proviziune
            norma = None
            if p.act and p.locator:
                an = n.lovitura.publicat.year if n.lovitura.publicat else None
                gasit = textul(cx, p.act, p.locator, an, index)
                norma = gasit if isinstance(gasit, Prevedere) else None
            id_portal = pe_cheie.get(n.lovitura.decizie)
            temeiuri = (
                _temeiuri_decizie(
                    cx,
                    id_portal,
                    n.lovitura.publicat.isoformat() if n.lovitura.publicat else None,
                )
                if id_portal
                else []
            )
            iesire.append(_nereparat_dict(n, norma, temeiuri))
        return iesire
    finally:
        cx.close()


def _neconstitutional(draft: str, stare: Stare) -> list[dict]:
    """Where the draft cites a provision the Court struck and nobody ever repaired.

    The severest thing this package can say to a drafter, and the cheapest to say: an intersection
    between the prebuilt register and the draft's own citations, no model and no network. Silent
    where no register is shipped — an empty pass and a pass that never ran are different facts, and
    `rezumat` is where a surface learns which one it has.
    """
    from scripts.coliziune import coliziuni

    return [
        {
            "text": c.text[:300],
            "act_id": c.act_id,
            "locator": c.locator,
            "locator_lovit": c.locator_lovit,
            "fel": c.fel,
            "decizie": c.decizie,
            "decizii": list(c.decizii),
            "publicat": c.publicat.isoformat() if c.publicat else None,
            "zile_de_la_termen": c.zile_de_la_termen,
            "potrivire": c.potrivire,
            "severitate": c.severitate,
            "sustinut": c.sustinut,
            "motiv": c.motiv,
            "citat": c.citat,
            "norma": c.norma,
            "norma_granularitate": c.norma_granularitate,
            "norma_nota": c.norma_nota,
            "limitari": list(c.limitari),
            "temeiuri": list(c.temeiuri),
            "incredere": c.increderea,
        }
        for c in coliziuni(draft, stare.neconstitutional)
    ]


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


def _republicari_citate(draft: str, stare: Stare) -> dict[str, date | None]:
    """Republication dates for just the acts this draft cites — the input `vigoare.py` needs to
    decide whether a locator-level match crosses a renumbering boundary."""
    from scripts.referinte import referinte

    return stare.republicari({r.act.id for r in referinte(draft) if r.act is not None})


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
                # material, not blocking, when the match only holds across a renumbering boundary
                "severitate": cm.severitate,
            }
            for cm in citari_moarte(draft, graf, _republicari_citate(draft, stare))
        ]
    finally:
        graf.close()


def _calificate(draft: str, stare: Stare) -> list[dict]:
    """References in the draft to a provision with a qualified status short of repeal — suspended,
    derogated from, or with a prorogated term. Read from the graph's `suspenda`/`deroga`/`proroga`
    edges; silent where the data cannot reach, and a provision already caught as repealed is not
    repeated here. Material, not blocking: the citation is not dead, but it is not unqualified.
    """
    if not stare.are_graf():
        return []
    from scripts.graf import _deschide_graf
    from scripts.vigoare import citari_calificate

    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        return [
            {
                "act_id": cc.act_id,
                "locator": cc.locator,
                "eticheta": cc.eticheta,
                "motiv": cc.motiv,
                "intregul_act": cc.calificare.este_intregul_act,
            }
            for cc in citari_calificate(draft, graf, _republicari_citate(draft, stare))
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
        # Titles and corpus-membership come from `stare` (the shard index in the browser, `acte`
        # on localhost), so this no longer opens the whole corpus — only the initiatives DB.
        with depozit.deschide(stare.initiative, readonly=True) as ini:
            for act_id in acte:
                amend = inbound(graf, act_id, doar_amendamente=True)
                try:
                    pendinte = initiative_pe_act(ini, act_id)
                except Exception:
                    pendinte = []
                out.append(
                    {
                        "act_id": act_id,
                        "titlu": stare.titlu(act_id),
                        "sursa_url": stare.sursa_url(act_id),
                        "in_corpus": stare.cunoscut(act_id),
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


def _fisa_act(qs: dict, stare: Stare) -> dict:
    act_id = _prima(qs, "act").strip()
    if not act_id:
        return {
            "gasit": False,
            "act_id": "",
            "limitari": ["Alege un act pentru fișa de lucru."],
        }
    watch = _supraveghere(act_id, stare)
    if not watch.get("cunoscut"):
        return {**watch, "gasit": False, "limitari": ["Actul nu este în corpusul local."]}
    viduri = [
        {
            **v,
            "actiuni": _actiuni_prevedere(act_id, v.get("locator")),
        }
        for v in _raport_lista(stare.vid)
        if v.get("act_id") == act_id
    ][:5]
    neconstitutionale = [
        {
            **n,
            "actiuni": _actiuni_prevedere(act_id, n.get("locator")),
        }
        for n in _raport_lista(stare.neconstitutional)
        if n.get("act_id") == act_id
    ][:5]
    referinte_ue = _referinte_ue_dosar(stare, {act_id}, limita=8)
    pasi = ["Deschide prevederile afectate înainte de a scrie sau modifica text."]
    if viduri:
        pasi.append("Pentru lacune: verifică obligația, termenul și instrumentul lipsă.")
    if neconstitutionale:
        pasi.append("Pentru CCR: compară norma curentă cu decizia și marchează reparația.")
    if watch.get("initiative"):
        pasi.append("Pentru inițiative: compară proiectele pendinte înainte de text nou.")
    if referinte_ue:
        pasi.append("Pentru UE: verifică actele CELEX importate sau importă cele lipsă.")
    return {
        **watch,
        "gasit": True,
        "viduri": viduri,
        "neconstitutionale": neconstitutionale,
        "referinte_ue": referinte_ue,
        "pasi": pasi,
        "limitari": [
            "Fișa de lucru agregă date locale; nu este verdict juridic.",
            *list(watch.get("limitari") or []),
        ],
    }


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


def _act(qs: dict, stare: Stare) -> dict:
    """Resolve tip/număr/an to an act id, and say whether the corpus carries it (with its title).

    Lets the drafting form replace a free-text act field with pickers, and confirm — before the
    user commits to a change — exactly which document they mean. `cunoscut=False` is not an error;
    the act simply is not collected yet."""
    from scripts.referinte import Act

    tip = (qs.get("tip", [""])[0] or "lege").strip()
    nr = (qs.get("nr", [""])[0] or "").strip()
    an = (qs.get("an", [""])[0] or "").strip()
    if not nr or not an.isdigit():
        return {"act_id": "", "cunoscut": False, "titlu": ""}
    act_id = Act(tip, nr, int(an)).id
    return {
        "act_id": act_id,
        "cunoscut": stare.cunoscut(act_id),
        "titlu": stare.titlu(act_id),
        # Everything else that answers to this name. `Hotărâre nr. 1 din 2016` is eighteen
        # different acts by eighteen different bodies, and a form that confirmed one of them
        # silently would confirm the wrong one seventeen times out of eighteen. The citation does
        # not say which; the reader has to.
        "omonime": _omonime(act_id, stare),
    }


def _omonime(act_id: str, stare: Stare) -> list[dict]:
    """The other acts a bare citation key could mean, if there are any.

    Empty — not absent — where the key is unambiguous, which is the ordinary case. Empty too where
    the store predates the column, because a corpus that cannot answer the question must not
    answer it wrongly.
    """
    from scripts import omonime

    try:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            lista = omonime.candidati(con, act_id)
    except sqlite3.OperationalError:
        return []
    return [{"act_id": r[0], "titlu": r[4], "emitent": r[5], "publicat": r[6]} for r in lista[1:]]


def _prevedere(qs: dict, stare: Stare) -> dict:
    """One provision's stored text, by act and locator. What a citation chip shows on hover.

    The consolidation view lists only the provisions an amendment *touched* — twenty rows for an
    act with hundreds — so nearly every citation inside it points at an article of the same act
    that is not on screen. Highlighting alone therefore answered almost nothing: measured on
    Legea 98/2016, 48 of 50 chips had no visible target. This is the other half of following a
    reference, and it reads the corpus as published rather than as consolidated.

    `gasit=False` where the corpus does not hold that provision — an act stored as one flattened
    row has no `art. 187` to return, and saying so is the point. A chip that quietly showed nothing
    would be indistinguishable from a provision that says nothing.
    """
    act_id = (qs.get("act", [""])[0] or "").strip()
    locator = (qs.get("loc", [""])[0] or "").strip()
    if not act_id or not locator:
        return {"gasit": False, "act_id": act_id, "locator": locator, "text": ""}
    with depozit.deschide(stare.corpus, readonly=True) as con:
        rand = con.execute(
            "SELECT text FROM provizii WHERE act_id = ? AND locator = ? ORDER BY ord LIMIT 1",
            (act_id, locator),
        ).fetchone()
    return {
        "gasit": rand is not None,
        "act_id": act_id,
        "locator": locator,
        "titlu": stare.titlu(act_id),
        "text": (rand[0] if rand else "") or "",
    }


def _cine_citeaza(qs: dict, stare: Stare) -> dict:
    """What depends on a provision — the answer to "what breaks if I change this".

    `harta` is the act's load-bearing provisions by how many distinct sources cite each, so a
    drafter can see where the weight sits before choosing what to edit. `citari` is the detail for
    one provision, each entry saying whether the citation names it exactly, names something inside
    it, or names something it sits inside — three different strengths of "this would be affected",
    kept apart rather than summed.

    Empty rather than an error where no graph is built: the graph is derived, an install may not
    have it yet, and a silent zero would read as "nothing depends on this".
    """
    act_id = (qs.get("act", [""])[0] or "").strip()
    locator = (qs.get("loc", [""])[0] or "").strip() or None
    if not act_id:
        return {"act_id": "", "locator": None, "citari": [], "harta": [], "are_graf": False}
    if not stare.are_graf():
        return {"act_id": act_id, "locator": locator, "citari": [], "harta": [], "are_graf": False}

    from scripts.graf import _deschide_graf, cine_citeaza, harta_citari

    act_id = stare.rezolva_nume(act_id)
    graf = _deschide_graf(stare.graf, readonly=True)
    try:
        citari = cine_citeaza(graf, act_id, locator)
        harta = harta_citari(graf, act_id)
    finally:
        graf.close()
    return {
        "act_id": act_id,
        "locator": locator,
        "titlu": stare.titlu(act_id),
        "citari": citari[:120],
        "total": len(citari),
        "harta": harta,
        "are_graf": True,
    }


def _deputati(qs: dict, stare: Stare) -> dict:
    """A deputy's record, or the parliamentary groups when no name is given.

    Identity is `(leg, camera, idm)` — the Chamber's own link key. Anything less merges people:
    `idm` alone covered 1 044 individuals with 349 values, and adding only the legislature still
    left 282 keys holding more than one person, because a deputy and a senator can share a number
    in the same year.

    Empty rather than an error where the passages have not been collected: an install with
    initiatives but no Fișe read has no signatures, and a zero must not read as "signed nothing".
    """
    q = (qs.get("q", [""])[0] or "").strip()
    idm = (qs.get("idm", [""])[0] or "").strip()
    leg = (qs.get("leg", [""])[0] or "").strip() or None
    camera = (qs.get("camera", [""])[0] or "").strip() or None
    doar_grupuri = (qs.get("grupuri", [""])[0] or "").strip()
    grup = (qs.get("grup", [""])[0] or "").strip()
    toti = (qs.get("toti", [""])[0] or "").strip()
    rezultat = (qs.get("rezultat", [""])[0] or "").strip() or None

    from scripts import deputati as dep

    with depozit.deschide(stare.initiative, readonly=True) as con:
        try:
            if idm:
                s = dep.soarta(con, idm, leg, camera)
                return {
                    "idm": idm,
                    "leg": leg,
                    "camera": camera,
                    "soarta": {
                        "adoptate": s.adoptate,
                        "respinse": s.respinse,
                        "nedecise": s.nedecise,
                    },
                    "initiative": dep.initiative(con, idm, leg, camera),
                    "interventii": _spuse(con, idm, leg, camera),
                    "voturi": _cum_a_votat(con, idm, leg, camera),
                    # Whether this store *carries* the roll and the transcripts at all. A member
                    # who cast no recorded vote and a build that ships no votes are different
                    # facts, and a panel that simply disappeared for both would report the first
                    # while meaning the second — the published build omits them for size.
                    "are_voturi": _are_tabel(con, "vot_nominal"),
                    "are_dezbateri": _are_tabel(con, "interventie"),
                }
            if toti:
                # The directory, for a reader who has no name to type — which is most readers.
                gata = (stare.parlament.get("persoane") or {}).get(leg or "")
                if gata is not None:
                    return {"leg": leg, "persoane": gata}
                return {
                    "leg": leg,
                    "persoane": [_persoana_dict(dep, p) for p in dep.toti(con, leg=leg)],
                }
            if grup:
                # The bills behind a group's counts. A card that says 466 adopted and cannot show
                # which 466 is a number a reader has to take on trust.
                return {
                    "grup": dep.grup_afisat(grup),
                    "leg": leg,
                    "rezultat": rezultat,
                    "initiative": dep.initiative_grup(con, grup, leg=leg, rezultat=rezultat),
                }
            if q:
                # One entry per person, each carrying every term they served. The search used to
                # return one row per term, so the same member appeared twice and neither row said
                # so.
                return {
                    "cautare": q,
                    "persoane": [_persoana_dict(dep, p) for p in dep.persoane(con, q)],
                    "semnatari": [
                        {
                            "idm": x.idm,
                            "leg": x.leg,
                            "camera": x.camera,
                            "nume": x.nume,
                            "grupuri": list(x.grupuri),
                            "initiative": x.initiative,
                        }
                        for x in dep.cauta(con, q)
                    ],
                }
            # `leg` narrows a group's record to one parliament. A sum across parliaments it was
            # differently composed in reads as one continuous record and is not.
            gata = (stare.parlament.get("grupuri") or {}).get(leg or "")
            if gata is not None:
                return {
                    "legislaturi": stare.parlament.get("legislaturi", []),
                    "leg": leg if doar_grupuri or leg else None,
                    "grupuri": gata,
                }
            return {
                "legislaturi": dep.legislaturi(con),
                "leg": leg if doar_grupuri or leg else None,
                "grupuri": dep.grupuri(con, leg),
            }
        except sqlite3.OperationalError:
            # The store predates the signature tables — nothing has been collected yet.
            return {
                "grupuri": [],
                "persoane": [],
                "semnatari": [],
                "initiative": [],
                "legislaturi": [],
            }


def _parcurs(qs: dict, stare: Stare) -> dict:
    """How one bill moved: who signed it, who was asked, and how the room voted.

    Read from the initiatives store, where `parcurs.colecteaza_parcurs` writes it. Returns empty
    lists rather than an error when the passage has not been collected for that bill — a watchlist
    is drawn from `initiative`, which is populated years before any of these rows are, and a card
    that failed instead of saying "not read yet" would make an uncollected bill look like a broken
    one.

    Votes carry `rezultat` as well as the tally, because the tally alone does not say which way it
    went: an adoption writes no question at all, so 275 votes *for* a bill and 296 votes to throw
    one out are the same three numbers with nothing between them but a null field.
    """
    plx_id = (qs.get("plx", [""])[0] or "").strip()
    if not plx_id:
        return {"plx_id": "", "etape": [], "avize": [], "voturi": [], "initiatori": []}
    with depozit.deschide(stare.initiative, readonly=True) as con:
        try:
            etape = [
                {
                    "data": r[0],
                    "camera": r[1],
                    "actiune": r[2],
                    # split() on an empty string yields [""], which renders as a stray separator
                    # where a step simply names no committee
                    "comisii": [c for c in (r[3] or "").split("\n") if c],
                    # Present only where the step links a debate, so a step that had none is not
                    # offered as one whose transcript failed to load.
                    "steno": ({"ids": r[4], "idm": r[5]} if r[4] else None),
                }
                for r in con.execute(
                    "SELECT data, camera, actiune, comisii, steno_ids, steno_idm"
                    " FROM initiativa_etapa WHERE plx_id = ? ORDER BY ord",
                    (plx_id,),
                )
            ]
            avize = [
                {"de_la": r[0], "data": r[1], "sens": r[2], "numar": r[3], "primit": bool(r[4])}
                for r in con.execute(
                    "SELECT de_la, data, sens, numar, primit FROM initiativa_aviz"
                    " WHERE plx_id = ? ORDER BY primit, data",
                    (plx_id,),
                )
            ]
            voturi = [
                {
                    "data": r[0],
                    "camera": r[1],
                    "intrebare": r[2],
                    "pentru": r[3],
                    "contra": r[4],
                    "abtineri": r[5],
                    "rezultat": r[6],
                    "absenti": r[7],
                    # Present only where the step linked a roll, so a division with none is not
                    # offered as one whose roll failed to load.
                    "idv": r[8],
                }
                for r in con.execute(
                    "SELECT data, camera, intrebare, pentru, contra, abtineri, rezultat, absenti,"
                    " idv FROM initiativa_vot WHERE plx_id = ? ORDER BY data",
                    (plx_id,),
                )
            ]
            initiatori = [
                {
                    "nume": r[0],
                    "grup": _grup_afisat(r[1]),
                    "camera": r[2],
                    "idm": r[3],
                    "leg": r[4],
                }
                for r in con.execute(
                    "SELECT nume, grup, camera, idm, leg FROM initiativa_initiator"
                    " WHERE plx_id = ? ORDER BY grup, nume",
                    (plx_id,),
                )
            ]
            # What the bill itself says, not only what happened to it. `obiect` is the Fișa's own
            # statement of what the draft sets out to do, and it is the thing a reader opens an
            # initiative to read; `sursa_url` is the Chamber's page, so anyone can check this
            # reading against the source.
            cap = con.execute(
                "SELECT titlu, obiect, stadiu, tip, data_inreg, sursa_url FROM initiative"
                " WHERE plx_id = ?",
                (plx_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # The store predates these tables — nothing has been collected yet.
            return {"plx_id": plx_id, "etape": [], "avize": [], "voturi": [], "initiatori": []}
    return {
        "plx_id": plx_id,
        "titlu": cap[0] if cap else "",
        "obiect": cap[1] if cap else "",
        "stadiu": cap[2] if cap else "",
        "tip": cap[3] if cap else "",
        "data_inreg": cap[4] if cap else "",
        "sursa_url": cap[5] if cap else "",
        "etape": etape,
        "avize": avize,
        "voturi": voturi,
        "initiatori": initiatori,
    }


def _persoana_dict(dep, p) -> dict:
    """One person as the page reads them. Shared by the search and the directory so the two cannot
    drift into describing the same person differently."""
    return {
        "nume": p.nume,
        "legislaturi": list(p.legislaturi),
        "initiative": p.initiative,
        "mandate": [
            {
                "idm": m.idm,
                "leg": m.leg,
                "camera": m.camera,
                "grupuri": [dep.grup_afisat(g) for g in m.grupuri],
                "initiative": m.initiative,
            }
            for m in p.mandate
        ],
    }


def _are_tabel(con: sqlite3.Connection, nume: str) -> bool:
    """Whether this store carries any rows of `nume`.

    Asking `sqlite_master` whether the table exists answers nothing: `depozit.deschide` runs the
    schema on every open, so every table exists in every store from the moment it is opened. The
    question is whether anything was ever put in it — and the published build leaves the roll and
    the transcripts out for size, so a profile there must say so rather than draw nothing.

    `LIMIT 1` rather than a count: the roll is 484 596 rows and this runs on every profile.
    """
    try:
        return bool(con.execute(f"SELECT 1 FROM {nume} LIMIT 1").fetchone())
    except sqlite3.OperationalError:
        return False


def _grup_afisat(grup):
    from scripts.deputati import grup_afisat

    return grup_afisat(grup)


def _spuse(con: sqlite3.Connection, idm: str, leg: str | None, camera: str | None) -> list[dict]:
    """What this deputy said in the Chamber, newest sitting first.

    Joined on `(leg, camera, idm)` — the Chamber's own key — and never on the name, for the same
    reason the signatures are. Empty where no transcript has been read: a deputy with no speeches
    collected must not be reported as one who never spoke.
    """
    try:
        return [
            {
                "ids": r[0],
                "idm": r[1],
                "ord": r[2],
                "data": r[3],
                "titlu": r[4],
                "plx_id": r[5],
                "text": r[6],
            }
            for r in con.execute(
                "SELECT i.ids, i.idm, i.ord, s.data, s.titlu, s.plx_id, i.text"
                " FROM interventie i JOIN stenograma s ON s.ids = i.ids AND s.idm = i.idm"
                " WHERE i.dep_idm = ? AND i.dep_leg IS ? AND i.dep_camera IS ?"
                # Capped where the others are not: a speech is a paragraph, not a row, and a
                # chair's record runs to thousands. The card says when it is showing a slice.
                " ORDER BY s.data DESC, i.ord LIMIT 300",
                (idm, leg, camera),
            )
        ]
    except sqlite3.OperationalError:
        # No transcripts collected in this store.
        return []


def _cum_a_votat(con: sqlite3.Connection, idm: str, leg: str | None, camera: str | None):
    """How this member voted, from the Chamber's own roll of each division.

    The tally on a Fișa is the room's answer and nobody's. This is the one a voter can act on, and
    it hangs off the same key as their signatures and their speeches.
    """
    from scripts import nominal

    return nominal.cum_a_votat(con, idm, leg, camera)


def _rol(qs: dict, stare: Stare) -> dict:
    """One division's roll, grouped by parliamentary group.

    `gasit=False` where the roll has not been collected. An unread roll and a division nobody voted
    in must not look alike — an empty list for both would report a silence that did not happen.
    """
    from scripts import nominal

    idv = (qs.get("idv", [""])[0] or "").strip()
    if not idv:
        return {"gasit": False, "idv": "", "grupuri": []}
    with depozit.deschide(stare.initiative, readonly=True) as con:
        try:
            return nominal.rolul(con, idv)
        except sqlite3.OperationalError:
            return {"gasit": False, "idv": idv, "grupuri": []}


def _stenograma(qs: dict, stare: Stare) -> dict:
    """One sitting item's debate, in the order it was spoken.

    Keyed on `(ids, idm)` — the sitting and the item within it — because that is what a step links
    and what the Chamber publishes. `gasit=False` where the transcript has not been collected,
    rather than an empty list: a debate nobody has fetched and a debate nobody spoke at must not
    look alike.
    """
    ids = (qs.get("ids", [""])[0] or "").strip()
    idm = (qs.get("idm", [""])[0] or "").strip()
    if not ids or not idm:
        return {"gasit": False, "ids": ids, "idm": idm, "interventii": []}
    with depozit.deschide(stare.initiative, readonly=True) as con:
        try:
            cap = con.execute(
                "SELECT data, camera, titlu, plx_id, url FROM stenograma WHERE ids = ? AND idm = ?",
                (ids, idm),
            ).fetchone()
            if not cap:
                return {"gasit": False, "ids": ids, "idm": idm, "interventii": []}
            interventii = [
                {
                    "ord": r[0],
                    "vorbitor": r[1],
                    "idm": r[2],
                    "leg": r[3],
                    "camera": r[4],
                    "rol": r[5],
                    "text": r[6],
                }
                for r in con.execute(
                    "SELECT ord, vorbitor, dep_idm, dep_leg, dep_camera, rol, text"
                    " FROM interventie WHERE ids = ? AND idm = ? ORDER BY ord",
                    (ids, idm),
                )
            ]
        except sqlite3.OperationalError:
            return {"gasit": False, "ids": ids, "idm": idm, "interventii": []}
    return {
        "gasit": True,
        "ids": ids,
        "idm": idm,
        "data": cap[0],
        "camera": cap[1],
        "titlu": cap[2],
        "plx_id": cap[3],
        "url": cap[4],
        "interventii": interventii,
    }


def _dezbateri(qs: dict, stare: Stare) -> dict:
    """Search what was actually said, rather than what a bill was called.

    A title says what a law is for; the debate says what was argued about it, and the two are
    often not the same words. Diacritic-folded by the index, so a reader who types `masuri` finds
    `măsuri`.
    """
    q = (qs.get("q", [""])[0] or "").strip()
    if not q:
        return {"cautare": "", "rezultate": []}
    with depozit.deschide(stare.initiative, readonly=True) as con:
        try:
            rezultate = [
                {
                    "ids": r[0],
                    "idm": r[1],
                    "ord": r[2],
                    "vorbitor": r[3],
                    "data": r[4],
                    "titlu": r[5],
                    "plx_id": r[6],
                    "fragment": r[7],
                }
                for r in con.execute(
                    "SELECT f.ids, f.idm, f.ord, f.vorbitor, s.data, s.titlu, s.plx_id,"
                    "  snippet(interventie_fts, 0, '<mark>', '</mark>', '…', 24)"
                    " FROM interventie_fts f"
                    " LEFT JOIN stenograma s ON s.ids = f.ids AND s.idm = f.idm"
                    " WHERE interventie_fts MATCH ? ORDER BY rank LIMIT 40",
                    (q,),
                )
            ]
        except sqlite3.OperationalError:
            # No transcripts collected, or the query is not valid FTS syntax — either way there is
            # nothing to show, and a 500 on a stray quote mark would be worse.
            return {"cautare": q, "rezultate": []}
    return {"cautare": q, "rezultate": rezultate}


def _domenii(qs: dict, stare: Stare) -> dict:
    """The corpus grouped by the body that issued it, or one body's acts.

    Not by subject: the portal publishes no classification and this package does not invent one.
    The issuer is on every document and is what the state itself files by.
    """
    from scripts import domenii

    emitent = (qs.get("emitent", [""])[0] or "").strip()
    tip = (qs.get("tip", [""])[0] or "").strip() or None
    try:
        with depozit.deschide(stare.corpus, readonly=True) as con:
            if emitent:
                return {
                    "emitent": emitent,
                    "tip": tip,
                    "acte": domenii.acte_ale(con, emitent, tip=tip),
                }
            return {
                "emitenti": [
                    {
                        "nume": e.nume,
                        "acte": e.acte,
                        "tipuri": [{"tip": t, "acte": n} for t, n in e.tipuri[:6]],
                        "de_la": e.de_la,
                        "pana_la": e.pana_la,
                    }
                    for e in domenii.emitenti(con)
                ]
            }
    except sqlite3.OperationalError:
        # A store with no acts collected yet, or an older schema. Empty, not an error: a zero here
        # would otherwise read as "this body has issued nothing".
        return {"emitenti": [], "acte": []}


def _importa(nume: str, continut_b64: str) -> dict:
    """One uploaded file into the editor's block tree, in a single round trip.

    Base64 in JSON rather than multipart, and that is a decision about the *other* build: under
    Pyodide there is no HTTP at all, the page calls this function directly, and a transport that
    only exists on localhost would mean two code paths for one feature. The draft still never
    leaves the tab in the browser build.

    Parsed here too, because a caller that got text back would immediately ask for the tree and
    nothing else can be done with the text meanwhile.
    """
    import base64
    import binascii

    from scripts import fisiere

    try:
        octeti = base64.b64decode(continut_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "eroare": "conținut invalid"}
    if not octeti:
        return {"ok": False, "eroare": "fișier gol"}
    try:
        citit = fisiere.citeste(octeti, nume=nume or "")
    except ValueError as e:
        # A refusal a person can act on — a PDF says what to do instead — rather than a stack
        # trace, and never a half-read draft that somebody then edits.
        return {"ok": False, "eroare": str(e)}
    return {
        "ok": True,
        "fel": citit.fel,
        "paragrafe": citit.paragrafe,
        "text": citit.text,
        **_parseaza(citit.text),
    }


def _docx(titlu: str, text: str) -> dict:
    """The draft as a `.docx`, base64 so the page can save it without a download endpoint.

    Same reason as `_importa`: the browser build has no server to stream bytes from, and one path
    for both builds beats a feature that only works on localhost.
    """
    import base64

    from scripts import fisiere

    if not (text or "").strip():
        return {"ok": False, "eroare": "nimic de exportat"}
    octeti = fisiere.catre_docx(titlu or "Proiect", text)
    return {
        "ok": True,
        "nume": _nume_fisier(titlu),
        "continut_b64": base64.b64encode(octeti).decode("ascii"),
    }


_NUME_RAU = re.compile(r"[^\w .,()\-]", re.UNICODE)


def _nume_fisier(titlu: str) -> str:
    """A download name built from a title the user typed.

    Path separators, control characters and anything else that is not a letter, a digit or ordinary
    punctuation are dropped rather than escaped. The title reaches a browser's `download` attribute
    here, and could reach a `Content-Disposition` header the day this is served over something
    else — where a newline is header injection and a `/` is a path. Sanitising at the point the
    name is made means that day is not a new decision.
    """
    curat = _NUME_RAU.sub("", (titlu or "").strip())[:60].strip(" .") or "proiect"
    return f"{curat}.docx"


def _parseaza(text: str) -> dict:
    """Recover the Articol ▸ Alineat ▸ Literă tree from the pasted plain text of an act, so the
    editor can load an existing law as blocks to redact. Deterministic, no model."""
    from scripts.parsare_text import parseaza_text

    return parseaza_text(text or "")


def _norma(text: str) -> dict:
    """Check a submitted project is written entirely in one drafting norm, not a mix of the two.

    Deterministic, no model (see `scripts.norma`). Returns the dominant norm, whether the project is
    coherent, and the exact units that break from the majority so the editor can point at them.

    It also carries the normative-register findings for the same text. Two different questions
    about one piece of writing — *is it all in one norm* and *is it in the register a norm is
    written in* — and the composer asks both of a draft it already has in hand, so they travel
    together rather than costing a second round trip."""
    from scripts.norma import coerenta
    from scripts.redactare import limbaj_normativ

    c = coerenta(text or "")
    return {
        "limbaj": [
            {"gasit": a.gasit, "fragment": a.fragment, "explicatie": a.explicatie}
            for a in limbaj_normativ(text or "")
        ],
        "dominanta": c.dominanta,
        "coerent": c.coerent,
        "raport": c.raport(),
        "unitati": [
            {"text": u.text, "norma": u.norma, "scor_nou": u.scor_nou, "scor_actual": u.scor_actual}
            for u in c.unitati
        ],
        "abateri": [{"text": u.text, "norma": u.norma} for u in c.abateri],
    }


def _regula(text: str) -> dict:
    """Legislation as code: parse a provision-as-rule, render both norms, check it, list its cases.

    Deterministic (see `scripts.lac`). A parse error comes back as data (`ok: false`), never raised,
    so the editor shows it inline. No corpus, no model — pure over the one line written."""
    from scripts.lac import analizeaza

    return analizeaza(text or "")


def _termeni(text: str, stare: Stare) -> dict:
    """The defined terms a draft uses, in reading order, each with its definition — so the editor
    can chip them and show the meaning on hover. Deterministic (see `definitii.recunoaste`)."""
    from scripts.definitii import recunoaste

    occ = recunoaste(text or "", stare.termeni)
    return {
        "termeni": [
            {
                "termen": o.termen.termen,
                "definitie": o.termen.definitie,
                "fragment": o.fragment,
                "start": o.start,
                "end": o.end,
            }
            for o in occ
        ]
    }


def _dictionar(stare: Stare) -> dict:
    """The whole defined-term dictionary, deduplicated and alphabetised, for client-side
    autocomplete. Sent once at startup; the terms are public law, nothing about the draft."""
    seen: set[str] = set()
    out: list[dict] = []
    for t in sorted(stare.termeni, key=lambda t: t.termen.lower()):
        k = t.cheia
        if k in seen:
            continue
        seen.add(k)
        out.append({"termen": t.termen, "definitie": t.definitie})
    return {"termeni": out}


def _compune(interventii: list[dict]) -> dict:
    """Compile a list of structured changes into a whole amending act, verified by re-reading it.

    Legislation as code: the caller sends the intents (operation, act, locators, new text); this
    returns the mandated Legea 24/2000 document plus `verificare` — the points that did not read
    back as their own operation, so the drafter is told exactly what to look at.
    """
    from scripts.compunere import Interventie, compune

    def g(i: dict, k: str) -> str | None:
        v = str(i.get(k, "") or "").strip()
        return v or None

    ivs = [
        Interventie(
            operatie=g(i, "operatie") or "modifica",
            act=g(i, "act") or "…",
            articol=g(i, "articol"),
            alineat=g(i, "alineat"),
            litera=g(i, "litera"),
            text_nou=g(i, "text_nou") or "…",
            articol_nou=g(i, "articol_nou"),
        )
        for i in interventii
    ]
    r = compune(ivs)
    return {
        "titlu": r.titlu,
        "text": r.text,
        "verificare": list(r.verificare),
        "curat": r.curat,
    }


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

    from scripts.ancore import ca_dict as _ancore

    # The text handed to the page is the *normalised* one, because the anchor offsets are measured
    # against it. Sending the raw text with offsets read off a normalised copy would draw every
    # chip a few characters off wherever the original had a double space or a wrapped line.
    ancorate = {r.locator: _ancore(r.text or "", propriu=r.locator) for r in rez.values()}

    provizii = [
        {
            "locator": r.locator,
            "complet": r.complet,
            "abrogat": r.abrogat,
            "text": ancorate[r.locator]["text"] if r.text else r.text,
            "ancore": ancorate[r.locator]["ancore"],
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
        "rezumat": {
            "atinse": len(provizii),
            "consolidate": consolidate,
            "refuzate": len(provizii) - consolidate,
        },
    }


def _cauta(
    q: str,
    stare: Stare,
    *,
    tip: str | None = None,
    an_min: int | None = None,
    an_max: int | None = None,
    limita: int = 25,
    offset: int = 0,
) -> dict:
    """Full-text search, filtered by act type/year and paged. `total` lets the UI say how many hits
    there are behind the page it shows, instead of silently truncating at a fixed cap."""
    if not q.strip():
        return {"results": [], "total": 0, "offset": 0, "limita": limita}
    with depozit.deschide(stare.corpus, readonly=True) as con:
        rows = depozit.cauta(con, q, limita, offset=offset, tip=tip, an_min=an_min, an_max=an_max)
        total = depozit.cauta_numar(con, q, tip=tip, an_min=an_min, an_max=an_max)
    return {
        "results": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limita": limita,
    }


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

        def shape(other, m):
            # Title from `stare` (shard index or `acte`), so no whole-corpus open here either.
            return {
                "act_id": other,
                "fel": m.fel,
                "locator": m.locator,
                "de_la": m.de_la.isoformat() if m.de_la else None,
                "titlu": stare.titlu(other),
                "sursa_url": stare.sursa_url(other),
            }

        inb = [shape(o, m) for o, m in list(intra.items())[:limita]]
        outb = [shape(o, m) for o, m in list(iese.items())[:limita]]
    finally:
        graf.close()
    return {"act": act_id, "inbound": inb, "outbound": outb}


def construieste_parlament(initiative_db: str) -> dict:
    """The whole-Parliament answers, settled once at publish time.

    `/api/deputati` with no name asks for the groups and the legislatures; with `toti` it asks for
    the directory. Both aggregate the signature tables — 68.783 initiator rows — and neither
    depends on anything the reader types beyond `leg`, whose values are the handful of
    legislatures. Computed per request that is fine against a local file and ruinous against a
    mounted one: measured on the published build, the groups panel took **54,2 s**, which the page
    shows as an empty panel rather than a slow one.

    Keyed by legislature, with `""` for "across all of them".
    """
    from scripts import deputati as dep

    with depozit.deschide(initiative_db, readonly=True) as con:
        try:
            legi = dep.legislaturi(con)
            return {
                "legislaturi": legi,
                "grupuri": {(leg or ""): dep.grupuri(con, leg) for leg in [None, *legi]},
                "persoane": {
                    (leg or ""): [_persoana_dict(dep, p) for p in dep.toti(con, leg=leg)]
                    for leg in [None, *legi]
                },
            }
        except sqlite3.OperationalError:
            # A store that predates the signature tables: nothing collected yet.
            return {"legislaturi": [], "grupuri": {}, "persoane": {}}
