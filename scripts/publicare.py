"""When an act was published in Monitorul Oficial, read from the act's own text.

The publication date is not decoration. Article 147 (1) of the Constitution suspends a provision
the Court has struck for 45 days *from publication*, and article 78 gives an ordinary law three
days from publication unless it names a later date. Every deadline this package computes is
anchored on that date, and until now the corpus did not hold it.

**What it held instead was the in-force date, twice.** `scrie_inregistrare` wrote
`rec.data_vigoare` into both `acte.publicat` and `acte.vigoare`, so `publicat` was a publication
date in name only — identical to `vigoare` in all 63 933 rows measured. For Curtea
Constituțională decisions the two genuinely coincide, because article 147 (4) makes a decision
binding from publication, so the register's arithmetic happened to be right. For an ordinary law
with a vacatio legis it is wrong by however long that vacatio is, and nothing said so.

**The service does not give the date, but the document does.** The API's `Publicatie` field is
the literal string `Monitorul Oficial` — no number, no date. The act's own text opens with
`Publicat în MONITORUL OFICIAL nr. 9 din 17 ianuarie 1996`, and that line is present in 100% of
the Court's decisions and 78% of all collected documents. So this is a parse, not a new fetch.

**Anchored on `MONITORUL OFICIAL`, and only in the header.** Two ways to get this wrong, both
silent. Every act opens with its own designation — `DECIZIE nr. 101 din 25 octombrie 1995` —
which matches a bare `nr. N din DD month YYYY` pattern and is the date it was *pronounced*, often
months earlier. And the body of any decision quotes other acts with their own monitors, several
times. So the pattern requires the words `MONITORUL OFICIAL` immediately before the number, and
only the opening of the document is searched.

Where the line cannot be read, this returns `None` and the caller stores `NULL`. That is the
whole point: a missing publication date has to look missing, or it becomes a copy of whatever
was nearest to hand.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Final

from scripts.parsare import LUNI
from scripts.text import cheie, normalizeaza

# How much of the document counts as the header. The publication line sits in the first few
# lines of every portal record; the reasoning that cites other monitors starts well after.
FEREASTRA: Final[int] = 700

_MONITOR: Final[re.Pattern[str]] = re.compile(
    r"MONITORUL\s+OFICIAL(?:\s+AL\s+ROM(?:Â|A)NIEI)?"
    r"(?:\s*,?\s*PARTEA\s+(?P<partea>[IVX]+))?"
    r"\s*,?\s*(?:nr\.?|num(?:ă|a)rul)?\s*"
    r"(?P<numar>\d{1,5})\s+din\s+(?P<zi>\d{1,2})\s+(?P<luna>[a-zăâîșț]+)\s+(?P<an>\d{4})",
    re.IGNORECASE,
)


# `republicat în Monitorul Oficial nr. X` is a different event from first publication: the act
# was consolidated and reissued, often decades later, and its articles may have been renumbered.
# Measured at 3.4% of collected documents. The date is still a real publication date and is kept,
# but a caller computing "in force since" or an article-level deadline from a republication is
# computing from the wrong event, so the distinction is carried rather than flattened.
_REPUBLICARE: Final[re.Pattern[str]] = re.compile(r"republicat", re.IGNORECASE)


@dataclass(frozen=True)
class Publicare:
    """One publication, as the act states it."""

    monitor: int | None
    data: date | None
    partea: str | None
    text: str
    republicare: bool = False


def publicare(text: str) -> Publicare | None:
    """The Monitorul Oficial reference from an act's header, or `None` if it does not carry one."""
    cap = normalizeaza(text)[:FEREASTRA]
    m = _MONITOR.search(cap)
    if m is None:
        return None
    luna = LUNI.get(cheie(m.group("luna")))
    if luna is None:
        return None
    try:
        data = date(int(m.group("an")), luna, int(m.group("zi")))
    except ValueError:
        # A scanned or mistyped day like `31 iunie`. A wrong date is worse than no date.
        return None
    partea = m.group("partea")
    # Only the words immediately before the reference decide it: `republicat` elsewhere in a
    # header routinely refers to some *other* act the document mentions.
    inainte = cap[max(0, m.start() - 40) : m.start()]
    return Publicare(
        monitor=int(m.group("numar")),
        data=data,
        partea=partea.upper() if partea else None,
        text=m.group(0),
        republicare=bool(_REPUBLICARE.search(inainte)),
    )


def reciteste(cale_db: str = "corpus.db", *, lot: int = 5000, log=print) -> dict[str, int]:
    """Fill `publicat` / `monitor` for a corpus collected before this module existed.

    A local pass over text already stored — nothing is refetched. Run after a collection, or
    after this parser changes: the whole point of keeping the document text is that a parser
    improvement can be replayed over the corpus without touching the ministry's server again.
    """
    from scripts import depozit

    with depozit.deschide(cale_db) as con:  # opening for write applies the column migration
        # Ids first, text in batches. `SELECT ... text ... .fetchall()` over the whole corpus
        # pulls every document body into memory at once — measured at 4.4 GB and climbing on a
        # 205 000-document corpus, for a job whose working set is one document. The ids are
        # eight bytes each and the text is fetched only for the batch being written.
        ids = [
            r[0]
            for r in con.execute(
                "SELECT id_portal FROM documente WHERE publicare_incercata IS NULL"
            )
        ]
        log(f"{len(ids)} documente fără dată de publicare")

        citite = fara = vazute = 0
        for start in range(0, len(ids), lot):
            felie = ids[start : start + lot]
            semne = ",".join("?" * len(felie))
            randuri = con.execute(
                f"SELECT id_portal, cheie_act, text FROM documente WHERE id_portal IN ({semne})",
                felie,
            ).fetchall()
            for r in randuri:
                vazute += 1
                p = publicare(r["text"])
                con.execute(
                    "UPDATE documente SET publicare_incercata = 1 WHERE id_portal = ?",
                    (r["id_portal"],),
                )
                if p is None:
                    fara += 1
                    continue
                con.execute(
                    "UPDATE documente SET publicat = ?, monitor = ?, republicare = ?"
                    " WHERE id_portal = ?",
                    (p.data.isoformat(), p.monitor, int(p.republicare), r["id_portal"]),
                )
                # `acte` is the citation view: only a document that is still the winner for its
                # key may set the date there, or a collided namesake would overwrite it.
                con.execute(
                    "UPDATE acte SET publicat = ? WHERE id = ? AND id_portal = ?",
                    (p.data.isoformat(), r["cheie_act"], r["id_portal"]),
                )
                citite += 1
            con.commit()
            log(f"  {vazute}/{len(ids)} · {citite} citite · {fara} fără linie MO")

        # Filling in the dates that could be read is only half the job. An act whose document
        # carries no Monitorul Oficial line still holds whatever `publicat` had before — and
        # before, that was a copy of the in-force date. Leaving those behind produces the worst
        # of both worlds: a column that is right for most rows and quietly wrong for the rest,
        # with nothing to tell them apart. Measured on the finished corpus: 11 116 of 152 079.
        golite = con.execute(
            "UPDATE acte SET publicat ="
            " (SELECT d.publicat FROM documente d WHERE d.id_portal = acte.id_portal)"
        ).rowcount
        log(f"  {golite} rânduri din «acte» realiniate la documentul lor")
    return {"total": len(ids), "citite": citite, "fara_linie": fara}


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    a = ap.parse_args()
    r = reciteste(a.db)
    print(
        f"\ngata: {r['citite']} date de publicare citite din {r['total']} documente "
        f"({r['fara_linie']} fără linie Monitorul Oficial)"
    )
    cx = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    for eticheta, q in [
        ("documente cu dată MO", "SELECT count(*) FROM documente WHERE publicat IS NOT NULL"),
        ("din care republicări", "SELECT count(*) FROM documente WHERE republicare = 1"),
        (
            "acte unde publicat ≠ vigoare",
            "SELECT count(*) FROM acte WHERE publicat IS NOT NULL AND publicat <> vigoare",
        ),
    ]:
        print(f"  {eticheta}: {cx.execute(q).fetchone()[0]}")
    cx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
