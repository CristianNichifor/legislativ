"""The amendment graph, derived from the corpus rather than scraped from the portal.

`vid.py` needs edges: to say a law's implementing norms were never issued, it must know which
acts point back at that law. The portal publishes those relations, but only through a panel
endpoint that builds a broken SQL query on any input this package could send — fragile, injectable,
and on the same host the collector is already straining. So the graph is built the deterministic
way instead, from text this package already holds and already parses.

**Every amending act says what it changes.** `amendamente.py` reads "modifică articolul 7 din
Legea nr. 98/2016" out of an act's body and returns the target act and article. Run it over the
whole corpus and the outbound edges fall out; invert them and the inbound edges — *who amends
this law* — come for free. `referinte.py` adds the plain references, which is the edge `vid.py`
looks for when it asks whether any act refers back to a law that owed implementing norms.

**This is better than the panel, not a fallback from it.** The edges are ours: extracted by the
patterns measured at 100% precision on the gold set, each carrying whether its target was stated
outright or inherited from a chapeau — the provenance the portal's opaque list cannot give. And
it costs the server nothing, because it reads the text already collected.

**Its limit is honest and already handled.** The graph sees only amendments whose acts are in the
corpus, so a law amended by an act not yet collected shows fewer inbound edges than it truly has.
That is exactly what `Corpus.complet_pentru` in `vid.py` exists to qualify: the graph grows toward
complete as the collection fills, and a gap finding says which instruments the corpus can and
cannot vouch for. An incomplete graph understates amendments; it never invents one.

Written to its own database, not the corpus, because SQLite takes one writer and the collector
holds it. The graph reads the corpus `mode=ro` and writes edges beside it.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from scripts import depozit
from scripts.amendamente import amendamente
from scripts.referinte import Act, referinte
from scripts.text import normalizeaza

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS muchii (
    din_act     TEXT NOT NULL,
    din_locator TEXT,                 -- which provision of the citing act said it; NULL if unknown
    catre_act   TEXT NOT NULL,
    locator     TEXT,
    fel         TEXT NOT NULL,        -- modifica | abroga | introduce | deroga | ... | refera
    incredere   TEXT NOT NULL,        -- verbatim (stated) | derived (inherited/reference)
    de_la       TEXT,                 -- the amending act's date, when known
    PRIMARY KEY (din_act, din_locator, catre_act, locator, fel)
);
CREATE INDEX IF NOT EXISTS idx_muchii_catre ON muchii(catre_act);
CREATE INDEX IF NOT EXISTS idx_muchii_din ON muchii(din_act);
CREATE INDEX IF NOT EXISTS idx_muchii_din_loc ON muchii(din_act, din_locator);
"""


@dataclass(frozen=True)
class Muchie:
    din_act: str
    catre_act: str
    locator: str
    fel: str
    incredere: str
    de_la: date | None
    din_locator: str | None = None


def _deschide_graf(cale: str, *, readonly: bool = False):
    """Open the graph. Writers create the schema; readers open `mode=ro` and skip the DDL.

    The read-only path matters for the same reason it does on the corpus: `executescript(SCHEMA)`
    is a write, so a reader that ran it would contend for the writer lock — and the server or a
    gap report reading the graph while `construieste` rebuilds it would wedge exactly as two
    collectors on one file did. A ro connection reads the last committed state and never wants
    that lock.
    """
    if readonly:
        con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        return con
    con = sqlite3.connect(cale, timeout=30.0)
    con.row_factory = sqlite3.Row
    _migreaza_sursa(con)
    con.executescript(SCHEMA)
    return con


def _migreaza_sursa(con: sqlite3.Connection) -> None:
    """Drop a `muchii` written before edges carried their source provision.

    `din_locator` belongs in the primary key — the same target cited from two articles is two
    edges, and a key without it keeps one and discards the other — so this cannot be an
    `ALTER TABLE ADD COLUMN`. The old rows are dropped rather than migrated because there is
    nothing to migrate them *to*: the source provision was never recorded, and every one of them
    would have to be filled with NULL, which is indistinguishable from an act with no provisions.

    Dropping derived data is safe here in a way it would never be in the corpus. The graph is
    rebuilt from `provizii` by `construieste`, so what is lost is recomputable — and it has to be
    recomputed anyway, since the whole point is that the old edges were extracted from a corpus
    with no article trees.
    """
    tabele = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "muchii" not in tabele:
        return
    coloane = {r[1] for r in con.execute("PRAGMA table_info(muchii)")}
    if "din_locator" in coloane:
        return
    con.execute("DROP TABLE muchii")
    con.commit()


def text_cu_spans(corp, act_id: str) -> tuple[str, list[tuple[int, int, str]]]:
    """An act's text as one string, plus where each provision sits inside it.

    The text is joined rather than processed provision by provision, and that is deliberate. A
    Romanian amending act states its target once in a chapeau — `Legea nr. 98/2016 se modifică
    astfel:` — and then lists the changes under it, so `amendamente` inherits the target across
    provisions. Extracting each provision alone would break that inheritance and lose the target
    of every amendment after the first.

    So the whole text is still what gets read, and the spans are what let an edge be traced back
    afterwards to the provision whose characters produced it.

    Each provision is normalised before joining, and the join normalised again, so the offsets
    line up with what `referinte` and `amendamente` see — both normalise internally, and a second
    application is a no-op only if the string is already canonical.
    """
    spans: list[tuple[int, int, str]] = []
    bucati: list[str] = []
    pozitie = 0
    for locator, brut in corp.execute(
        "SELECT locator, text FROM provizii WHERE act_id = ? ORDER BY ord", (act_id,)
    ):
        bucata = normalizeaza(brut or "")
        if not bucata:
            continue
        if bucati:
            pozitie += 1  # the "\n" that will join it to the previous piece
        spans.append((pozitie, pozitie + len(bucata), locator))
        bucati.append(bucata)
        pozitie += len(bucata)
    return "\n".join(bucati), spans


def _sursa(spans: list[tuple[int, int, str]], pozitie: int) -> str | None:
    """The provision containing this offset, or None when the act has no spans (or it falls in a
    joining newline). `bisect` rather than a scan: an act runs to hundreds of provisions and this
    is asked once per edge."""
    if not spans:
        return None
    i = bisect_right(spans, (pozitie, len(spans) + pozitie + 1, "\uffff")) - 1
    if i < 0:
        return None
    inceput, sfarsit, locator = spans[i]
    return locator if inceput <= pozitie < sfarsit else None


def _muchii_din_act(
    act: Act,
    text: str,
    publicat: date | None,
    spans: list[tuple[int, int, str]] | None = None,
) -> Iterator[Muchie]:
    """Every edge one act's text asserts: its amendments, then its plain references.

    An amendment is the stronger claim (it changes the target), so where a target is both amended
    and merely referenced the amendment edge is what matters; the reference edges fill in the rest
    of what the act points at, which is what a gap check reads.

    Each edge carries the provision it was read from, mapped from the span the extractor already
    returns. That is what turns "this law points at that law" into "article 5 of this law points
    at article 7 of that one" — the difference between knowing something breaks and knowing what.
    """
    spans = spans or []
    tinte_amendate: set[str] = set()
    for a in amendamente(text, act_gazda=act):
        if a.act_tinta is None or a.act_tinta.id == act.id:
            continue
        yield Muchie(
            act.id,
            a.act_tinta.id,
            a.locator.id,
            a.fel,
            a.increderea,
            publicat,
            _sursa(spans, a.start),
        )
        tinte_amendate.add(a.act_tinta.id)
    vazute: set[str] = set()
    for r in referinte(text):
        if r.act is None or r.act.id == act.id or r.act.id in tinte_amendate:
            continue
        # The source is part of the key now: the same target cited from two different articles is
        # two edges, and deduplicating without it would keep whichever came first and silently
        # drop the other — which is the granularity this exists to add.
        din = _sursa(spans, r.start)
        cheie = f"{din}|{r.act.id}|{r.locator.id}"
        if cheie in vazute:
            continue
        vazute.add(cheie)
        yield Muchie(act.id, r.act.id, r.locator.id, "refera", "derived", publicat, din)


_CORP_LUCRATOR: sqlite3.Connection | None = None


def _porneste_lucrator(corpus_db: str) -> None:
    """One read-only connection per worker process, opened once and kept."""
    global _CORP_LUCRATOR
    _CORP_LUCRATOR = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)


def _muchii_pentru(arg: tuple[str, str, str | None, int | None, str | None]):
    """Extract one act's edges in a worker. Reads its own text rather than being handed it.

    The text is the expensive thing to move — a quarter of a million acts averaging 14 kB would
    be gigabytes through a pipe — and every worker already has the corpus open read-only, so it
    costs one indexed lookup instead. Dates cross as ISO strings because that is cheaper to
    pickle than a `date` and the writer needs the string anyway.
    """
    id_act, tip, numar, an, publicat_iso = arg
    act = Act(tip, numar, an)
    text, spans = text_cu_spans(_CORP_LUCRATOR, id_act)
    publicat = date.fromisoformat(publicat_iso) if publicat_iso else None
    return id_act, [
        (
            m.din_act,
            m.din_locator,
            m.catre_act,
            m.locator,
            m.fel,
            m.incredere,
            m.de_la.isoformat() if m.de_la else None,
        )
        for m in _muchii_din_act(act, text, publicat, spans)
    ]


def _acte_de_construit(corp, limita: int | None, doar: Iterable[str] | None) -> list:
    """The acts this build covers, in the order it walks them.

    `doar` is what makes a daily refresh cheap. Edges are keyed by `din_act`, so an act's edges
    live entirely on its own rows — including the inbound ones an older law gains when a new act
    cites it. Placing newly collected acts therefore never requires revisiting the 152 079
    already in the graph, and the difference is eleven minutes against seconds. Ids are chunked
    because SQLite caps the number of bound variables in one statement.
    """
    if doar is None:
        q = "SELECT id, tip, numar, an, publicat FROM acte ORDER BY an DESC, numar"
        if limita:
            q += f" LIMIT {int(limita)}"
        return corp.execute(q).fetchall()

    randuri: list = []
    ids = list(doar)
    for i in range(0, len(ids), 400):
        felie = ids[i : i + 400]
        semne = ",".join("?" * len(felie))
        randuri.extend(
            corp.execute(
                f"SELECT id, tip, numar, an, publicat FROM acte WHERE id IN ({semne})"
                " ORDER BY an DESC, numar",
                felie,
            )
        )
    return randuri


def construieste(
    corpus_db: str = "corpus.db",
    graf_db: str = "graf.db",
    *,
    limita: int | None = None,
    lucratori: int = 1,
    doar: Iterable[str] | None = None,
    log=print,
) -> int:
    """Read the corpus, extract every edge, write them to the graph database. Returns edge count.

    Idempotent per act: an act's edges are deleted and rewritten, so a rebuild after the corpus
    grows replaces cleanly rather than doubling.

    **Extraction is the whole cost and it parallelises.** Profiled over the finished corpus:
    0.08 ms reading an act, 2.7 ms normalising it, and 25 ms pulling references out of it — so
    93% of the work is regex over text, pure CPU, with no shared state between acts. One process
    took 63 minutes over 152 079 acts on a machine with eight cores idle. Workers extract; the
    parent stays the only writer, because SQLite wants one writer and the network of edges has
    to be committed in one place anyway.
    """
    if lucratori > 1:
        return _construieste_paralel(
            corpus_db, graf_db, limita=limita, lucratori=lucratori, doar=doar, log=log
        )
    scrise = 0
    # One read connection for the whole build. The first version reopened the corpus per act — a
    # fresh connection for every one of a quarter-million rows — which turned a minutes job into
    # an hours one. Read-only, so it still runs beside the collector's writer.
    with depozit.deschide(corpus_db, readonly=True) as corp:
        acte = _acte_de_construit(corp, limita, doar)

        graf = _deschide_graf(graf_db)
        try:
            for i, rand in enumerate(acte, start=1):
                act = Act(rand["tip"], rand["numar"], rand["an"])
                text, spans = text_cu_spans(corp, act.id)
                publicat = date.fromisoformat(rand["publicat"]) if rand["publicat"] else None
                graf.execute("DELETE FROM muchii WHERE din_act = ?", (act.id,))
                for m in _muchii_din_act(act, text, publicat, spans):
                    graf.execute(
                        "INSERT OR REPLACE INTO muchii (din_act, din_locator, catre_act, locator,"
                        " fel, incredere, de_la) VALUES (?,?,?,?,?,?,?)",
                        (
                            m.din_act,
                            m.din_locator,
                            m.catre_act,
                            m.locator,
                            m.fel,
                            m.incredere,
                            m.de_la.isoformat() if m.de_la else None,
                        ),
                    )
                    scrise += 1
                if i % 500 == 0:
                    graf.commit()
                    log(f"  {i}/{len(acte)} acte · {scrise} muchii")
            graf.commit()
        finally:
            graf.close()
    return scrise


def _construieste_paralel(
    corpus_db: str,
    graf_db: str,
    *,
    limita: int | None,
    lucratori: int,
    doar: Iterable[str] | None = None,
    log=print,
) -> int:
    """The same build, with extraction fanned out and writing kept in one place."""
    from concurrent.futures import ProcessPoolExecutor

    with depozit.deschide(corpus_db, readonly=True) as corp:
        acte = [
            (r["id"], r["tip"], r["numar"], r["an"], r["publicat"])
            for r in _acte_de_construit(corp, limita, doar)
        ]

    scrise = 0
    graf = _deschide_graf(graf_db)
    try:
        with ProcessPoolExecutor(
            max_workers=lucratori, initializer=_porneste_lucrator, initargs=(corpus_db,)
        ) as ex:
            # `chunksize` matters more than worker count here: an act is ~25 ms of work, so
            # handing them over one at a time spends more on IPC than on extraction.
            for i, (id_act, muchii) in enumerate(
                ex.map(_muchii_pentru, acte, chunksize=64), start=1
            ):
                graf.execute("DELETE FROM muchii WHERE din_act = ?", (id_act,))
                graf.executemany(
                    "INSERT OR REPLACE INTO muchii (din_act, din_locator, catre_act, locator,"
                    " fel, incredere, de_la) VALUES (?,?,?,?,?,?,?)",
                    muchii,
                )
                scrise += len(muchii)
                if i % 2000 == 0:
                    graf.commit()
                    log(f"  {i}/{len(acte)} acte · {scrise} muchii")
        graf.commit()
    finally:
        graf.close()
    return scrise


def inbound(
    graf: sqlite3.Connection, act_id: str, *, doar_amendamente: bool = False
) -> list[Muchie]:
    """Acts that point at `act_id` — who amends or references this law."""
    q = "SELECT * FROM muchii WHERE catre_act = ?"
    if doar_amendamente:
        q += " AND fel != 'refera'"
    return [_muchie(r) for r in graf.execute(q + " ORDER BY de_la", (act_id,))]


def outbound(graf: sqlite3.Connection, act_id: str) -> list[Muchie]:
    """What `act_id` points at — the laws it amends or references."""
    return [
        _muchie(r)
        for r in graf.execute(
            "SELECT * FROM muchii WHERE din_act = ? ORDER BY catre_act", (act_id,)
        )
    ]


def _muchie(r: sqlite3.Row) -> Muchie:
    # `din_locator` is read by name and defaulted, because `inbound`/`outbound` select `*` and a
    # graph opened read-only never runs the migration that adds the column — a reader pointed at a
    # graph built before this would otherwise raise instead of answering with what it does have.
    chei = r.keys()
    return Muchie(
        r["din_act"],
        r["catre_act"],
        r["locator"],
        r["fel"],
        r["incredere"],
        date.fromisoformat(r["de_la"]) if r["de_la"] else None,
        r["din_locator"] if "din_locator" in chei else None,
    )


def cine_citeaza(graf: sqlite3.Connection, act_id: str, locator: str | None = None) -> list[dict]:
    """Which provisions of which acts point at this one.

    The answer to "what breaks if I change it".

    Until edges carried `din_locator` this could only be asked of a whole act: *forty laws cite
    Legea 98/2016*. That is true and nearly useless to someone editing one paragraph of it. With
    the source recorded it becomes *article 210 of OUG 107/2017 repeals your art. 167 alin. (4)*,
    which is a sentence a drafter can act on.

    **Containment runs both ways, and the two are not the same claim**, so each edge says which it
    is rather than being flattened into one count:

    - `exact` — the citation names the provision being changed.
    - `interior` — it names something inside it. Changing `art. 7` reaches everyone who cited
      `art. 7 alin. (2)`, because the paragraph they relied on is inside what you are editing.
    - `incadreaza` — it names something the provision is inside. Editing `art. 7 alin. (2)` touches
      those who cited `art. 7` as a whole, but less directly: they may not depend on your paragraph
      at all, and reporting that as the same kind of hit would cry wolf.

    With no `locator` this returns every citation of the act, which is the old act-level question
    and still the right one when the change is to the act as such.
    """
    randuri = graf.execute(
        "SELECT din_act, din_locator, locator, fel, incredere, de_la FROM muchii"
        " WHERE catre_act = ?",
        (act_id,),
    ).fetchall()
    iesire: list[dict] = []
    for r in randuri:
        tinta = r["locator"] or ""
        fel_atingere = _atingere(locator, tinta)
        if fel_atingere is None:
            continue
        iesire.append(
            {
                "act": r["din_act"],
                "locator_sursa": r["din_locator"],
                "locator_tinta": tinta or None,
                "fel": r["fel"],
                "incredere": r["incredere"],
                "de_la": r["de_la"],
                "atingere": fel_atingere,
            }
        )
    # Exact first, then what sits inside the change, then what merely encloses it — the order of
    # how sure the hit is. Within each, a citation whose own article is known comes before one
    # whose source is a whole flattened act: `art. 210 of OUG 107/2017 repeals your alin. (4)` is
    # actionable, `somewhere in decision 147/2022` is a pointer to go read something. Sorting
    # alphabetically put every `decizie-` ahead of every `oug-` and buried the actionable half.
    rang = {"exact": 0, "interior": 1, "incadreaza": 2}
    return sorted(
        iesire,
        key=lambda x: (
            rang[x["atingere"]],
            0 if x["locator_sursa"] and x["locator_sursa"] != "text" else 1,
            x["act"],
            x["locator_sursa"] or "",
        ),
    )


def _atingere(schimbat: str | None, citat: str) -> str | None:
    """How a citation of `citat` relates to a change at `schimbat`. None when it does not."""
    if not schimbat:
        return "exact"
    if not citat:
        return None
    if citat == schimbat:
        return "exact"
    if citat.startswith(schimbat + "."):
        return "interior"
    if schimbat.startswith(citat + "."):
        return "incadreaza"
    return None


def harta_citari(graf: sqlite3.Connection, act_id: str, *, limita: int = 40) -> list[dict]:
    """Which provisions of an act are the load-bearing ones, by how many distinct sources cite them.

    Counted per distinct citing *provision*, not per edge: one article that cites the same target
    under two different `fel` is one source with two opinions about it, not two dependants.
    """
    return [
        {"locator": r[0], "surse": r[1]}
        for r in graf.execute(
            "SELECT locator, count(DISTINCT din_act || '#' || coalesce(din_locator, '')) c"
            " FROM muchii WHERE catre_act = ? AND locator IS NOT NULL AND locator != ''"
            " GROUP BY locator ORDER BY c DESC, locator LIMIT ?",
            (act_id, limita),
        )
    ]


def rezumat(graf: sqlite3.Connection) -> dict[str, int]:
    def n(q: str) -> int:
        return graf.execute(q).fetchone()[0]

    return {
        "muchii": n("SELECT count(*) FROM muchii"),
        "amendamente": n("SELECT count(*) FROM muchii WHERE fel != 'refera'"),
        "acte_care_amendeaza": n(
            "SELECT count(DISTINCT din_act) FROM muchii WHERE fel != 'refera'"
        ),
        "acte_amendate": n("SELECT count(DISTINCT catre_act) FROM muchii WHERE fel != 'refera'"),
    }


def _main() -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument("--limita", type=int, default=None)
    ap.add_argument(
        "--lucratori",
        type=int,
        default=max(1, (os.cpu_count() or 2) // 2),
        help="procese de extractie; 1 = secvential. Extractia e 93%% din cost si e pur CPU.",
    )
    a = ap.parse_args()
    n = construieste(a.corpus, a.graf, limita=a.limita, lucratori=a.lucratori)
    print(f"\ngata: {n} muchii")
    graf = _deschide_graf(a.graf)
    try:
        r = rezumat(graf)
        for k, v in r.items():
            print(f"  {k}: {v}")
        cele_mai = graf.execute(
            "SELECT catre_act, count(*) c FROM muchii WHERE fel != 'refera'"
            " GROUP BY catre_act ORDER BY c DESC LIMIT 8"
        ).fetchall()
        print("\ncele mai amendate acte din corpus:")
        for row in cele_mai:
            print(f"  {row['catre_act']}: {row['c']} amendamente primite")
    finally:
        graf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
