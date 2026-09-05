"""The gap report, run over the real corpus and the derived graph.

This is the loop closing. `vid.py` had the logic — an obligation whose implementing act cannot be
found is a gap, qualified by whether the corpus is complete for that instrument — but it needed a
`Corpus` whose acts knew what they referenced. The graph now supplies exactly that: each act's
outbound edges are what it amends and references. So this bridges the two, and the tested severity
and limitation logic in `vid.py` runs unchanged over national law instead of a fixture.

**The bridge is one line of meaning.** `vid.Corpus.implementari(host, tip)` asks which acts
reference a host act; an act references what its `referinte_la` set holds; and that set is the
act's outbound edges from `graf.py`. Populate `referinte_la` from the graph and the whole
gap-detection apparatus works without touching its logic — the graph made the missing input
available, this hands it over.

**Completeness is the honest dial, and it stays conservative until it is earned.** `complet_pentru`
names the act types the corpus can vouch for exhaustively. While the collection is still running it
is empty, so every gap finding is `blocking` — "cannot tell a missing norm from an uncollected
one", which is the truth. Once the collector has walked the whole corpus, the six normative types
can be declared complete and the same findings downgrade to `material`: real, actionable gaps. The
dial is a parameter, not a guess, so it is set when the fact is true and not before.

Read-only on both databases, so it runs while they fill and simply judges more each time.
"""

from __future__ import annotations

from datetime import date

from scripts import depozit
from scripts.analiza import obligatii_corpus
from scripts.graf import _deschide_graf, outbound
from scripts.referinte import Act
from scripts.termene import Obligatie
from scripts.vid import ActCunoscut, Corpus, Vid, raport, vid_legislativ


def corpus_din_graf(
    corpus_db: str = "corpus.db",
    graf_db: str = "graf.db",
    *,
    complet_pentru: frozenset[str] = frozenset(),
) -> Corpus:
    """A `vid.Corpus` whose acts know what they reference, taken from the graph's outbound edges.

    Every act in the corpus becomes an `ActCunoscut`; its `referinte_la` is the set of acts it
    points at, so `implementari` can find an implementing act by scanning for one whose outbound
    edges include the host. `complet_pentru` is passed through untouched — the caller decides what
    the corpus may vouch for, because only the caller knows whether the collection has finished.
    """
    acte: dict[str, ActCunoscut] = {}
    with depozit.deschide(corpus_db, readonly=True) as corp:
        randuri = corp.execute(
            "SELECT id, tip, numar, an, titlu, publicat, vigoare FROM acte"
        ).fetchall()
    graf = _deschide_graf(graf_db)
    try:
        for r in randuri:
            tinte = {m.catre_act for m in outbound(graf, r["id"])}
            acte[r["id"]] = ActCunoscut(
                act=Act(r["tip"], r["numar"], r["an"]),
                titlu=r["titlu"] or "",
                publicat=date.fromisoformat(r["publicat"]) if r["publicat"] else None,
                vigoare=date.fromisoformat(r["vigoare"]) if r["vigoare"] else None,
                referinte_la=frozenset(tinte),
            )
    finally:
        graf.close()
    return Corpus(acte=acte, complet_pentru=complet_pentru)


def raport_vid(
    corpus_db: str = "corpus.db",
    graf_db: str = "graf.db",
    *,
    complet_pentru: frozenset[str] = frozenset(),
    la_data: date | None = None,
    limita: int | None = None,
    doar_cu_instrument: bool = True,
) -> list[Vid]:
    """Every dated obligation the corpus cannot show was met, worst overdue first.

    Obligations come from the acts' own text; the corpus-of-record for checking them comes from
    the graph. Both read-only, so this is safe to run mid-collection — it simply judges against
    however much law has landed.

    `doar_cu_instrument` keeps only obligations that name an instrument to issue — a norm, a
    hotărâre, an ordin — and it is the default because the point of this report is missing
    *implementing acts*, not deadlines in general. A sentence like "cu recurs în termen de 10
    zile" is a procedural clock, not a delegation, and the extractor cannot always tell them
    apart from the words alone; requiring a recognised instrument is the cheap, honest filter
    that keeps the report about the thing it is for. Turn it off to see every dated obligation,
    noise included.
    """
    corpus = corpus_din_graf(corpus_db, graf_db, complet_pentru=complet_pentru)
    with depozit.deschide(corpus_db, readonly=True) as corp:
        obligatii: list[Obligatie] = [
            og.obligatie
            for og in obligatii_corpus(corp, limita=limita)
            if og.obligatie.tip_asteptat is not None or not doar_cu_instrument
        ]
    return vid_legislativ(obligatii, corpus, la_data or date.today())


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument(
        "--complet", default="", help="tipuri complete, separate prin virgulă (ex: hg,ordin)"
    )
    ap.add_argument("--limita", type=int, default=None)
    a = ap.parse_args()
    complet = frozenset(t.strip() for t in a.complet.split(",") if t.strip())
    vids = raport_vid(a.corpus, a.graf, complet_pentru=complet, limita=a.limita)
    blocante = sum(1 for v in vids if v.severitate == "blocking")
    print(
        f"{len(vids)} obligații fără implementare găsită "
        f"({blocante} blocante, {len(vids) - blocante} materiale)\n"
    )
    print(raport(vids[:15]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
