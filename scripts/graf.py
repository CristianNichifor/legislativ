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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from scripts import depozit
from scripts.amendamente import amendamente
from scripts.referinte import Act, referinte

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS muchii (
    din_act   TEXT NOT NULL,
    catre_act TEXT NOT NULL,
    locator   TEXT,
    fel       TEXT NOT NULL,          -- modifica | abroga | introduce | deroga | ... | refera
    incredere TEXT NOT NULL,          -- verbatim (stated) | derived (inherited/reference)
    de_la     TEXT,                   -- the amending act's date, when known
    PRIMARY KEY (din_act, catre_act, locator, fel)
);
CREATE INDEX IF NOT EXISTS idx_muchii_catre ON muchii(catre_act);
CREATE INDEX IF NOT EXISTS idx_muchii_din ON muchii(din_act);
"""


@dataclass(frozen=True)
class Muchie:
    din_act: str
    catre_act: str
    locator: str
    fel: str
    incredere: str
    de_la: date | None


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
    con.executescript(SCHEMA)
    return con


def _muchii_din_act(act: Act, text: str, publicat: date | None) -> Iterator[Muchie]:
    """Every edge one act's text asserts: its amendments, then its plain references.

    An amendment is the stronger claim (it changes the target), so where a target is both amended
    and merely referenced the amendment edge is what matters; the reference edges fill in the rest
    of what the act points at, which is what a gap check reads.
    """
    tinte_amendate: set[str] = set()
    for a in amendamente(text, act_gazda=act):
        if a.act_tinta is None or a.act_tinta.id == act.id:
            continue
        yield Muchie(act.id, a.act_tinta.id, a.locator.id, a.fel, a.increderea, publicat)
        tinte_amendate.add(a.act_tinta.id)
    vazute: set[str] = set()
    for r in referinte(text):
        if r.act is None or r.act.id == act.id or r.act.id in tinte_amendate:
            continue
        cheie = f"{r.act.id}|{r.locator.id}"
        if cheie in vazute:
            continue
        vazute.add(cheie)
        yield Muchie(act.id, r.act.id, r.locator.id, "refera", "derived", publicat)


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
    text = "\n".join(
        r[0]
        for r in _CORP_LUCRATOR.execute(
            "SELECT text FROM provizii WHERE act_id = ? ORDER BY ord", (id_act,)
        )
    )
    publicat = date.fromisoformat(publicat_iso) if publicat_iso else None
    return id_act, [
        (
            m.din_act,
            m.catre_act,
            m.locator,
            m.fel,
            m.incredere,
            m.de_la.isoformat() if m.de_la else None,
        )
        for m in _muchii_din_act(act, text, publicat)
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
                text = "\n".join(
                    r[0]
                    for r in corp.execute(
                        "SELECT text FROM provizii WHERE act_id = ? ORDER BY ord", (act.id,)
                    )
                )
                publicat = date.fromisoformat(rand["publicat"]) if rand["publicat"] else None
                graf.execute("DELETE FROM muchii WHERE din_act = ?", (act.id,))
                for m in _muchii_din_act(act, text, publicat):
                    graf.execute(
                        "INSERT OR REPLACE INTO muchii (din_act, catre_act, locator, fel,"
                        " incredere, de_la) VALUES (?,?,?,?,?,?)",
                        (
                            m.din_act,
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
                    "INSERT OR REPLACE INTO muchii (din_act, catre_act, locator, fel,"
                    " incredere, de_la) VALUES (?,?,?,?,?,?)",
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
    return Muchie(
        r["din_act"],
        r["catre_act"],
        r["locator"],
        r["fel"],
        r["incredere"],
        date.fromisoformat(r["de_la"]) if r["de_la"] else None,
    )


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
