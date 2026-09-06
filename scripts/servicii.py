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
        *,
        date_dir: str | None = None,
    ):
        self.corpus = corpus
        self.initiative = initiative
        self.graf = graf
        self.date_dir = Path(date_dir) if date_dir else None
        self._titluri: dict[str, str] | None = None
        self._urls: dict[str, str] | None = None
        self._republicari: dict[str, str] | None = None
        self._ids: set[str] | None = None
        self.termeni: list[Termen] = self._dictionar()
        self.vid: list[dict] = self._incarca_raport("vid.json")
        self.neconstitutional: list[dict] = self._incarca_raport("neconstitutional.json")
        self.norme_lovite: list[dict] = self._incarca_raport("norme_lovite.json")
        # Lazy: only the model pass reads the reasoning, and that pass needs a model. Loading it
        # eagerly would make every offline session pay for a feature it is not using.
        self._considerente: dict[str, str] | None = None

    @property
    def pe_shard(self) -> bool:
        return self.date_dir is not None

    def are_graf(self) -> bool:
        return Path(self.graf).is_file()

    # Built from the most recent acts only, not the whole corpus: definitions over a
    # quarter-million acts would take minutes, and the terminology check must answer instantly. The
    # recent N carry the vocabulary a current draft is most likely to talk around. On shards the
    # same bounded dictionary arrives prebuilt as `termeni.json`.
    def _dictionar(self, limita: int = 800) -> list[Termen]:
        if self.pe_shard:
            cale = self.date_dir / "termeni.json"
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
    def _incarca_raport(self, nume: str) -> list[dict]:
        cai = [self.date_dir / nume] if self.pe_shard else [Path("web/data") / nume, Path(nume)]
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

    def rezolva_nume(self, act_id: str, la_data: date | None = None) -> str:
        """A named act (`constitutie`, `cod-penal`) mapped onto the version the corpus stores.

        Citations name these acts; the collector keys them from their own titles, so the two write
        different ids for the same law and a quarter of everything the corpus cites looked absent.
        Anything that is not a name is returned unchanged, so callers can apply this blindly.
        """
        if not nomenclator.este_nume(act_id):
            return act_id
        return nomenclator.rezolva(act_id, self._toate_id(), la_data) or act_id

    def cunoscut(self, act_id: str) -> bool:
        """Whether the corpus carries this act at all — the honest 'in corpus' signal."""
        act_id = self.rezolva_nume(act_id)
        if self.pe_shard:
            return act_id in self._index()
        with depozit.deschide(self.corpus, readonly=True) as con:
            return con.execute("SELECT 1 FROM acte WHERE id = ?", (act_id,)).fetchone() is not None


def rezumat(stare: Stare) -> dict:
    """The corpus headline the page opens with: how much law, how many bills."""
    if stare.pe_shard:
        cale = stare.date_dir / "manifest.json"
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
            out["initiative"] = initiative_pe_act(ini, act_id)
    except Exception:
        out["initiative"] = []
    return out


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
    return {"act_id": act_id, "cunoscut": stare.cunoscut(act_id), "titlu": stare.titlu(act_id)}


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
