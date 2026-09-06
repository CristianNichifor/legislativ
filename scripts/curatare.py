"""One-off repairs to text already collected.

New collection is clean at the point of writing; this is for the corpus that already exists. Kept
as its own command rather than folded into the daily refresh, because a migration that runs itself
on a schedule is one nobody can decide not to run.

**The service's block separator.** The SOAP endpoint marks a boundary with a lone `+` on its own
line — after the header, before `Articolul UNIC`, after the enacting formula. 125 669 of the
151 947 documents carry at least one, and it is the only single-character line the service emits;
the HTML the portal serves for the same document has none, which is what identified it as an
artifact of the transport rather than part of the law. Left in, it renders inside quotations as
though the Monitorul Oficial had printed a `+`, and it goes into the context a model is asked to
quote from verbatim.

Only the derived copy is touched. `documente.text` keeps exactly what the service returned, because
a marker deleted from the archive could not be recovered, and the archive is the one thing in this
package that has to stay re-readable.

**The byte-order mark in titles.** 91 650 of 152 079 titles — 60% — begin with U+FEFF and a space.
It is not whitespace to Python, so `.strip()` walks up to it and stops, and the title sorts ahead
of every clean one and renders indented. `normalizeaza` now removes it, so new collection is clean;
`titluri` is for what is already written, and decodes the 179 titles carrying raw HTML entities in
the same pass.
"""

from __future__ import annotations

import argparse
import html
import time
from dataclasses import dataclass

from scripts import depozit
from scripts.text import fara_separatoare, normalizeaza


@dataclass(frozen=True)
class Curatare:
    examinate: int
    schimbate: int
    secunde: float
    subiect: str = "provizii"

    def __str__(self) -> str:
        return (
            f"{self.examinate} {self.subiect} examinate · {self.schimbate} curățate · "
            f"{self.secunde:.0f}s"
        )


def separatoare(cale_db: str = "corpus.db", *, lot: int = 5000, log=print) -> Curatare:
    """Remove the service's block markers from the provisions derived from its text.

    Only `locator = 'text'` rows: those are the ones the SOAP endpoint produced. Provisions parsed
    from the portal's HTML (`surse.imbogateste`) never carried the marker — 0 of 44 059 — so
    touching them would be a rewrite with nothing to fix.

    The index is rebuilt once at the end rather than row by row. `provizii_fts` is external
    content, so each edit would otherwise be a withdraw-and-reinsert against the old values, and
    125 669 of those cost more than reading the table again.
    """
    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        # Row ids first, text in batches. A document runs to tens of kilobytes and 125 669 of them
        # are affected, so selecting `text` for all of them at once is several gigabytes resident
        # before a single row is written — a corpus-wide `fetchall` has cost this project 4.36 GB
        # once already.
        ids = [
            r[0]
            for r in con.execute(
                "SELECT rowid FROM provizii WHERE locator = 'text'"
                " AND text LIKE '%' || char(10) || '+%'"
            )
        ]
        log(f"{len(ids)} provizii cu marcaj de separator")
        for start in range(0, len(ids), lot):
            felie = ids[start : start + lot]
            semne = ",".join("?" * len(felie))
            for rowid, text in con.execute(
                f"SELECT rowid, text FROM provizii WHERE rowid IN ({semne})", felie
            ).fetchall():
                examinate += 1
                curatat = fara_separatoare(text)
                if curatat != text:
                    con.execute("UPDATE provizii SET text = ? WHERE rowid = ?", (curatat, rowid))
                    schimbate += 1
            con.commit()
            log(f"  {examinate}/{len(ids)} · {schimbate} curățate")
        if schimbate:
            log("reconstruiesc indexul de căutare…")
            con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")
            con.commit()
    return Curatare(examinate, schimbate, time.monotonic() - t0)


def titluri(cale_db: str = "corpus.db", *, lot: int = 20000, log=print) -> Curatare:
    """Re-normalise stored titles: strip the byte-order mark, decode the HTML entities.

    Two defects, one pass. `normalizeaza` now removes U+FEFF, so new collection is clean; this is
    for the 91 650 titles — 60% of the corpus — already written with one. They render with a
    leading space and sort ahead of every clean title, because a BOM is not whitespace and
    `.strip()` stops at it.

    **The entities are decoded here and not in `normalizeaza`.** 179 titles carry raw markup —
    `&#9675;DECRET nr. 784`, `&nbsp;`, `&lt;` — and `html.unescape` is not idempotent: applied
    twice, `&amp;lt;` becomes `<` where once it gives `&lt;`. `normalizeaza` is documented as safe
    to run twice, and text passes through it on the way in *and* on the way into a matcher, so
    putting a one-way transform inside it would corrupt any title that legitimately spells an
    ampersand. A migration runs once by construction, which is where a one-way fix belongs.

    Both `acte` and `documente` are updated. `acte` is what a reader sees; `documente` is what
    `nomenclator.alias_an` reads titles from to confirm an act's year, and leaving it dirty would
    keep that check comparing against a string the rest of the corpus no longer uses.

    No index maintenance: `provizii_fts` indexes provision text, and titles are not in it.
    """
    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        for tabel, cheie in (("acte", "id"), ("documente", "id_portal")):
            ids = [
                r[0]
                for r in con.execute(
                    f"SELECT {cheie} FROM {tabel} WHERE titlu LIKE char(65279) || '%'"
                    " OR titlu LIKE '%&' || '#%;%' OR titlu LIKE '%&' || 'nbsp;%'"
                    " OR titlu LIKE '%&' || 'amp;%' OR titlu LIKE '%&' || 'lt;%'"
                    " OR titlu LIKE '%&' || 'gt;%' OR titlu LIKE '%&' || 'quot;%'"
                )
            ]
            log(f"{tabel}: {len(ids)} titluri de curățat")
            for start in range(0, len(ids), lot):
                felie = ids[start : start + lot]
                semne = ",".join("?" * len(felie))
                for id_, titlu in con.execute(
                    f"SELECT {cheie}, titlu FROM {tabel} WHERE {cheie} IN ({semne})", felie
                ).fetchall():
                    examinate += 1
                    curatat = normalizeaza(html.unescape(titlu or ""))
                    if curatat and curatat != titlu:
                        con.execute(
                            f"UPDATE {tabel} SET titlu = ? WHERE {cheie} = ?", (curatat, id_)
                        )
                        schimbate += 1
                con.commit()
                log(f"  {examinate} examinate · {schimbate} curățate")
    return Curatare(examinate, schimbate, time.monotonic() - t0, "titluri")


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument(
        "--titluri",
        action="store_true",
        help="curăță titlurile (BOM, entități HTML) în loc de separatoarele din provizii",
    )
    a = ap.parse_args()
    print(f"\ngata: {titluri(a.db) if a.titluri else separatoare(a.db)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
