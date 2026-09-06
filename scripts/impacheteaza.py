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

# The distribution, not the archive: `corpus.db` keeps every collided document's text and is
# 6.4 GB, where the cut sent to a reader is 2.5 GB and 742 MB compressed. `scripts.distributie`
# builds it; this ships it.
FISIERE = ("corpus-distributie.db", "initiative.db", "graf.db")


def impacheteaza(sursa: Path = Path("."), dist: Path = Path("dist")) -> list[tuple[str, int, str]]:
    """Gzip each database into `dist/`; returns (name, compressed bytes, sha256) per file."""
    dist.mkdir(exist_ok=True)
    rezultat: list[tuple[str, int, str]] = []
    for nume in FISIERE:
        cale = sursa / nume
        if not cale.is_file():
            continue
        # Streamed, not slurped. This was `read_bytes()` then `gzip.compress()` — both the
        # plaintext and the compressed copy in memory at once — written when the corpus was
        # small. At 2.5 GB that is 5 GB of resident memory to produce one file, and at the 6.4 GB
        # archive it does not complete at all.
        tinta = dist / f"{nume}.gz"
        suma = hashlib.sha256()
        octeti = 0
        with cale.open("rb") as intrare, gzip.open(tinta, "wb", compresslevel=9) as iesire:
            for bucata in iter(lambda: intrare.read(1 << 20), b""):
                iesire.write(bucata)
        with tinta.open("rb") as citit:
            for bucata in iter(lambda: citit.read(1 << 20), b""):
                suma.update(bucata)
                octeti += len(bucata)
        rezultat.append((f"{nume}.gz", octeti, suma.hexdigest()))
    return rezultat


if __name__ == "__main__":
    for nume, octeti, suma in impacheteaza():
        print(f"  {nume:20} {octeti / 1e6:7.1f} MB  sha256:{suma[:16]}…")
    print("\nÎncarcă dist/*.gz ca active la un release GitHub.")
    print("Researcherii le iau cu scripts/ia_corpus.sh")
