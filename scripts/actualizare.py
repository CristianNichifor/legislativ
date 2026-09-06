"""Bring a collected corpus up to today, in the time a daily job can afford.

The full build is a two-hour collection, a three-minute publication pass and an eleven-minute
graph. Run daily that is absurd, and a corpus nobody can afford to refresh stops being true —
which is the one failure this package is built to refuse, arriving slowly instead of all at once.

Every stage already knows how to do only what is new; this is the wiring, and the arithmetic that
makes it honest.

**The service enumerates chronologically and appends at the end.** New law lands on new pages past
the old end, and a law amended since arrives as a *new amending act* on one of those pages — so
freshness is not a diff against the server, it is re-walking the tail. `colector.actualizeaza`
does that, re-reading a small margin before the previous end because the last page collected was
almost certainly partial.

**Publication dates cost only the new documents.** `publicare.reciteste` examines what has not
been examined, which is what `publicare_incercata` records — as opposed to what has no date,
which is 22% of the corpus for ever.

**Edges cost only the new acts, and that is exact rather than approximate.** `muchii` is keyed by
`din_act`, so an act's edges live entirely on its own rows. When a new law cites an old one, the
edge belongs to the new law; nothing already in the graph needs revisiting. Rebuilding 152 079
acts to place fifty is eleven minutes to buy seconds.

What this deliberately does not do is decide anything. It collects, dates, and places edges; the
register and the reports are separate commands, because a job that silently republished findings
would be the same confident-and-wrong output in a different coat.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Rezultat:
    """What one refresh actually changed, so the run can report itself rather than be trusted."""

    pagini: int
    documente_noi: int
    acte_noi: int
    date_citite: int
    acte_cu_muchii: int
    muchii: int
    secunde: float

    def __str__(self) -> str:
        return (
            f"{self.pagini} pagini re-parcurse · {self.documente_noi} documente noi · "
            f"{self.acte_noi} acte noi · {self.date_citite} date de publicare · "
            f"{self.acte_cu_muchii} acte re-legate ({self.muchii} muchii) · "
            f"{self.secunde:.0f}s"
        )


def _numara(cale: str) -> tuple[int, int]:
    cx = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        return (
            cx.execute("SELECT count(*) FROM documente").fetchone()[0],
            cx.execute("SELECT count(*) FROM acte").fetchone()[0],
        )
    finally:
        cx.close()


def _acte_atinse(cale: str, de_la: str) -> list[str]:
    """Acts whose document was written on or after `de_la` — the ones whose edges are stale.

    Keyed off `documente.adus_la` rather than a guess about which pages were new: a page
    re-walked for the margin may contain an act that changed, and an act that did not change
    costs one cheap rebuild rather than a wrong graph.
    """
    cx = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        return [
            r[0]
            for r in cx.execute(
                "SELECT DISTINCT cheie_act FROM documente WHERE adus_la >= ? ORDER BY cheie_act",
                (de_la,),
            )
        ]
    finally:
        cx.close()


def actualizeaza(
    corpus_db: str = "corpus.db",
    graf_db: str = "graf.db",
    *,
    lucratori: int = 4,
    pauza: float = 0.2,
    log=print,
) -> Rezultat:
    """Collect the tail, date what arrived, and place its edges. Returns what changed."""
    from scripts import publicare
    from scripts.colector import actualizeaza as colecteaza_coada
    from scripts.graf import construieste

    t0 = time.monotonic()
    inceput = datetime.now(UTC).isoformat(timespec="seconds")
    doc0, acte0 = _numara(corpus_db)

    log("1/3 colectez coada enumerării…")
    u = colecteaza_coada(corpus_db, pauza=pauza, log=log)

    doc1, acte1 = _numara(corpus_db)
    log(f"    {doc1 - doc0} documente noi, {acte1 - acte0} acte noi")

    log("2/3 citesc datele de publicare pentru ce a intrat…")
    p = publicare.reciteste(corpus_db, log=log)

    log("3/3 reconstruiesc muchiile doar pentru actele atinse…")
    atinse = _acte_atinse(corpus_db, inceput)
    muchii = (
        construieste(corpus_db, graf_db, doar=atinse, lucratori=lucratori, log=log) if atinse else 0
    )

    return Rezultat(
        pagini=u.pagini,
        documente_noi=doc1 - doc0,
        acte_noi=acte1 - acte0,
        date_citite=p["citite"],
        acte_cu_muchii=len(atinse),
        muchii=muchii,
        secunde=time.monotonic() - t0,
    )


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument(
        "--lucratori",
        type=int,
        default=4,
        help="procese de extracție a muchiilor — lucru local pe CPU, fără legătură cu serviciul",
    )
    ap.add_argument(
        "--pauza",
        type=float,
        default=0.2,
        help="secunde între paginile colectate. Colectarea cozii e secvențială; 0,2 s a dat "
        "230 pagini/min fără 503-uri.",
    )
    a = ap.parse_args()
    r = actualizeaza(a.db, a.graf, lucratori=a.lucratori, pauza=a.pauza)
    print(f"\ngata: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
