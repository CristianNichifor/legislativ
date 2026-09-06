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
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from scripts import depozit
from scripts.text import fara_separatoare


@dataclass(frozen=True)
class Curatare:
    examinate: int
    schimbate: int
    secunde: float

    def __str__(self) -> str:
        return (
            f"{self.examinate} provizii examinate · {self.schimbate} curățate · {self.secunde:.0f}s"
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


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    a = ap.parse_args()
    print(f"\ngata: {separatoare(a.db)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
