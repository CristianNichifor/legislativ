"""Running the extractors over the corpus as it fills.

The deterministic layer — deadlines, definitions, references — was built and measured against a
gold set. This points it at the real corpus: every act the collector has landed, read for the
obligations it imposes and the terms it defines. It is the bridge between "the extractors work on
sentences" and "the extractors work on Romanian law", and it needs nothing the collector has not
already stored.

**Read-only, and useful before the corpus is complete.** It opens `mode=ro`, so it runs
alongside the collector and simply sees more each time. A deadline inventory over 6 000 acts is a
real answer, not a placeholder; it grows to the full corpus without any code changing.

**Deadlines are the pass that pays off first.** `termene.obligatii` reads the sentences that
delegate a law's operation — *în termen de 30 de zile … Guvernul aprobă normele metodologice* —
and every one is a dated obligation whose discharge is checkable. Across the whole corpus that is
an inventory of what the state promised itself and by when, which is the raw material the gap
report turns into findings once the implementing acts are loaded to check against.

**What this does not do yet is decide the gap.** `vid.py` needs the relation graph — which act
implements which — and the API's flat text does not carry it; those edges come from the
`Actiunisuferite` / `ActiuniInduse` panels, a later enrichment pass. So this reports the
obligations and the terms, honestly, and stops short of calling any obligation unmet. Counting
what exists is not the same as judging what is missing, and only the first is safe on a partial
corpus.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from scripts.definitii import Termen, definitii
from scripts.referinte import Act, Locator
from scripts.termene import Obligatie, obligatii


@dataclass(frozen=True)
class ObligatieGasita:
    """A dated obligation, with the act it sits in so a finding can cite it."""

    act: Act
    obligatie: Obligatie


def _act_din_rand(rand: sqlite3.Row) -> Act:
    return Act(rand["tip"], rand["numar"], rand["an"])


def _acte(con: sqlite3.Connection, limita: int | None) -> Iterator[sqlite3.Row]:
    q = "SELECT id, tip, numar, an, titlu, publicat, vigoare FROM acte ORDER BY an DESC, numar"
    if limita:
        q += f" LIMIT {int(limita)}"
    yield from con.execute(q)


def _text(con: sqlite3.Connection, act_id: str) -> str:
    return "\n".join(
        r[0]
        for r in con.execute("SELECT text FROM provizii WHERE act_id = ? ORDER BY ord", (act_id,))
    )


def obligatii_corpus(
    con: sqlite3.Connection, *, limita: int | None = None
) -> Iterator[ObligatieGasita]:
    """Every dated obligation the corpus states, act by act.

    Streams rather than collects: the corpus is large and a caller usually wants to count or
    filter, not hold every obligation in memory at once.
    """
    for rand in _acte(con, limita):
        act = _act_din_rand(rand)
        vigoare = None
        if rand["vigoare"]:
            from datetime import date

            vigoare = date.fromisoformat(rand["vigoare"])
        for ob in obligatii(_text(con, act.id), act=act, locator=Locator()):
            _ = vigoare  # the act's date travels on the Obligatie via `act`, kept for scadenta()
            yield ObligatieGasita(act, ob)


def termeni_corpus(con: sqlite3.Connection, *, limita: int | None = None) -> list[Termen]:
    """Every term the corpus defines, across all acts — the terminology check's dictionary."""
    gasiti: list[Termen] = []
    for rand in _acte(con, limita):
        act = _act_din_rand(rand)
        gasiti.extend(definitii(_text(con, act.id), act=act))
    return gasiti


def rezumat(con: sqlite3.Connection, *, limita: int | None = None) -> dict[str, int]:
    """Counts, so the analysis states its own scope rather than implying it covered everything."""
    obligatii_list = list(obligatii_corpus(con, limita=limita))
    cu_termen = sum(1 for o in obligatii_list if o.obligatie.termen_zile is not None)
    cu_instrument = sum(1 for o in obligatii_list if o.obligatie.tip_asteptat is not None)
    return {
        "obligatii": len(obligatii_list),
        "obligatii_cu_termen": cu_termen,
        "obligatii_cu_instrument": cu_instrument,
        "termeni_definiti": len(termeni_corpus(con, limita=limita)),
    }


def _main() -> int:
    import argparse

    from scripts import depozit

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--limita", type=int, default=None, help="doar primele N acte (pentru probe)")
    a = ap.parse_args()
    with depozit.deschide(a.db, readonly=True) as con:
        total_acte = con.execute("SELECT count(*) FROM acte").fetchone()[0]
        r = rezumat(con, limita=a.limita)
        print(f"corpus: {total_acte} acte (analizate: {a.limita or total_acte})")
        for k, v in r.items():
            print(f"  {k}: {v}")
        print("\nexemple de obligații cu termen:")
        n = 0
        for og in obligatii_corpus(con, limita=a.limita):
            if og.obligatie.termen_zile and n < 8:
                o = og.obligatie
                print(
                    f"  {og.act.id}: {o.tip_asteptat or '?'} în {o.termen_zile}z "
                    f"({o.ancora}) — {o.institutie or '?'}"
                )
                n += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
