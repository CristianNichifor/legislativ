"""Package the built corpus for the research team.

The databases are gitignored — a gigabyte of SQLite is an artifact, not source — so the team
cannot get them from a clone. This gzips the three of them into `dist/` for a maintainer to attach
to a GitHub release, the same out-of-band pattern the sister repository uses for its map data.
A researcher then downloads the release rather than scraping a ministry's server themselves, which
is the point: the collection is run once, by someone, and shared.

Not automated into CI: publishing a release is a deliberate act with a version and a date, and the
corpus changes slowly enough that a human deciding when to cut one is the right cadence.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

FISIERE = ("corpus.db", "initiative.db", "graf.db")


def impacheteaza(sursa: Path = Path("."), dist: Path = Path("dist")) -> list[tuple[str, int, str]]:
    """Gzip each database into `dist/`; returns (name, compressed bytes, sha256) per file."""
    dist.mkdir(exist_ok=True)
    rezultat: list[tuple[str, int, str]] = []
    for nume in FISIERE:
        cale = sursa / nume
        if not cale.is_file():
            continue
        brut = cale.read_bytes()
        comprimat = gzip.compress(brut, 9)
        tinta = dist / f"{nume}.gz"
        tinta.write_bytes(comprimat)
        rezultat.append((f"{nume}.gz", len(comprimat), hashlib.sha256(comprimat).hexdigest()))
    return rezultat


if __name__ == "__main__":
    for nume, octeti, suma in impacheteaza():
        print(f"  {nume:20} {octeti / 1e6:7.1f} MB  sha256:{suma[:16]}…")
    print("\nÎncarcă dist/*.gz ca active la un release GitHub.")
    print("Researcherii le iau cu scripts/ia_corpus.sh")
