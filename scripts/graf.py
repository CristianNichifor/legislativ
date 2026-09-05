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
from collections.abc import Iterator
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


def _deschide_graf(cale: str):
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


def construieste(
    corpus_db: str = "corpus.db", graf_db: str = "graf.db", *, limita: int | None = None, log=print
) -> int:
    """Read the corpus, extract every edge, write them to the graph database. Returns edge count.

    Idempotent per act: an act's edges are deleted and rewritten, so a rebuild after the corpus
    grows replaces cleanly rather than doubling.
    """
    scrise = 0
    # One read connection for the whole build. The first version reopened the corpus per act — a
    # fresh connection for every one of a quarter-million rows — which turned a minutes job into
    # an hours one. Read-only, so it still runs beside the collector's writer.
    with depozit.deschide(corpus_db, readonly=True) as corp:
        q = "SELECT id, tip, numar, an, publicat FROM acte ORDER BY an DESC, numar"
        if limita:
            q += f" LIMIT {int(limita)}"
        acte = corp.execute(q).fetchall()

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

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument("--limita", type=int, default=None)
    a = ap.parse_args()
    n = construieste(a.corpus, a.graf, limita=a.limita)
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
