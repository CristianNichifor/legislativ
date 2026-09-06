"""A corpus to hand someone, cut from the corpus of record.

`corpus.db` is an archive: it keeps every document the service ever returned, including the
53 242 whose citation key collided with another's and whose text exists nowhere else. That is
what `documente` is for and why it must stay — 3 977 MB of the 6 400.

A reader does not need the archive. They need the acts, their provisions, the search index, the
Court's strikes and the amendment graph: **2 573 MB**, which gzips to a download somebody will
actually complete.

**Two artifacts, not one database trying to be both.** Earlier attempts at this shrank
`corpus.db` itself — de-duplicating text between `documente` and `provizii` — and each needed a
rule about which copy was authoritative that changed as new documents arrived. That is a fragile
invariant guarding a distinction that does not need to exist inside one file. Archiving
everything and shipping what is needed are different jobs; the conflict dissolves when they are
different files.

**The schema is identical, so a distribution is a corpus.** Every tool works against it
unchanged — `documente` is simply empty. `progres` is deliberately not copied: without it the
collector refuses to treat a distribution as a corpus it may update, which is right, because the
page numbers it would resume from describe someone else's run.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from scripts import depozit

# Copied wholesale. `documente` is the archive and stays behind; `progres` and `cache` describe a
# collection run rather than the law, and `initiative` lives in its own database.
TABELE: tuple[str, ...] = ("acte", "provizii", "referinte_marcate", "relatii", "lovituri")


@dataclass(frozen=True)
class Rezumat:
    """What the distribution holds, so a release note can state it rather than promise it."""

    acte: int
    provizii: int
    lovituri: int
    octeti: int

    def __str__(self) -> str:
        return (
            f"{self.acte} acte · {self.provizii} provizii · {self.lovituri} lovituri · "
            f"{self.octeti / 1e9:.2f} GB"
        )


def construieste(
    corpus: str = "corpus.db", tinta: str = "dist/corpus-distributie.db", *, log=print
) -> Rezumat:
    """Write a distribution beside the archive. The archive is only ever read from."""
    cale = Path(tinta)
    cale.parent.mkdir(parents=True, exist_ok=True)
    if cale.exists():
        cale.unlink()

    with depozit.deschide(cale) as con:  # creates the full schema, including an empty `documente`
        # Attached by plain path: ATTACH does not parse `file:...?mode=ro` unless the
        # connection was opened with `uri=True`, and opening every corpus that way to serve this
        # one caller would be a wide change for a narrow need. Only SELECTs are issued against
        # `arhiva`, and `test_the_archive_is_not_touched` is what holds that to account.
        con.execute("ATTACH DATABASE ? AS arhiva", (str(Path(corpus).resolve()),))
        for tabel in TABELE:
            try:
                n = con.execute(f"SELECT count(*) FROM arhiva.{tabel}").fetchone()[0]
            except sqlite3.OperationalError:
                log(f"  {tabel}: absent în arhivă, sărit")
                continue
            con.execute(f"INSERT INTO {tabel} SELECT * FROM arhiva.{tabel}")
            log(f"  {tabel}: {n}")
        # The index is external-content, so it is rebuilt from the provisions just copied rather
        # than transferred — transferring it would also carry the archive's rowids.
        # Stamp the release with where it stands, before anyone can do local work in it. A copy
        # that has to infer its position from its own rows loses that position the moment its
        # reader upgrades an act locally — and then `delta` skips whatever the source published in
        # between, permanently. Every copy is born knowing where it is.
        pozitie = con.execute("SELECT coalesce(max(citit_la), '') FROM main.acte").fetchone()[0]
        if pozitie:
            con.execute(
                "INSERT OR REPLACE INTO versiune (cheie, valoare) VALUES ('adus_la', ?)",
                (pozitie,),
            )
        con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")
        log("  provizii_fts: reconstruit")
        # DETACH cannot run inside the transaction the inserts opened, and Python's sqlite3
        # opens one implicitly on the first write.
        con.commit()
        con.execute("DETACH DATABASE arhiva")

    # VACUUM outside the transaction: dropping `documente`'s pages is what actually returns disk.
    cx = sqlite3.connect(str(cale))
    try:
        cx.execute("VACUUM")
    finally:
        cx.close()

    cx = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        numar = lambda t: cx.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: E731
        return Rezumat(numar("acte"), numar("provizii"), numar("lovituri"), cale.stat().st_size)
    finally:
        cx.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--tinta", default="dist/corpus-distributie.db")
    a = ap.parse_args()
    print(f"\ngata: {construieste(a.db, a.tinta)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
