"""Build the copy of the corpus that a browser reads over the network.

`corpus.db` is the working database: it carries the raw HTML archive, the crawl bookkeeping and
the fetch cache, none of which a reader ever queries. Stripping them and rebuilding the file takes
it from **12,96 GB to 6,69 GB**, which matters twice over — it fits inside R2's 10 GB free tier,
and VACUUM rewrites the file so each act's provisions land on adjacent pages. That locality halved
the cost of opening a law over HTTP, from 3,0 MB to 1,19 MB.

Two properties the browser depends on, both easy to lose by copying the file by hand:

- **No WAL.** SQLite refuses `immutable=1` on a database with a `-wal` sidecar, and `immutable=1`
  is what lets it skip locking on a file it cannot write to.
- **A rebuilt page layout.** Without VACUUM the freed pages stay as holes and the provisions of
  one act remain scattered across the file.

The source is opened read-only and never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from scripts import depozit

# Build-time only: the never-rewritten HTML archive, the crawl state, the fetch cache, the log.
DE_ARUNCAT = ("documente", "surse", "cache", "progres")

GRATUIT_R2_GB = 10.0


def _verifica(tinta: Path) -> None:
    """Read the copy back the way the browser will, so a broken file cannot reach the bucket.

    The checks are taken from the data rather than hard-coded: naming an act here would mean this
    script starts failing the day that act is superseded, which says nothing about the copy.
    """
    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        acte = con.execute("SELECT count(*) FROM acte").fetchone()[0]
        provizii = con.execute("SELECT count(*) FROM provizii").fetchone()[0]
        if not acte or not provizii:
            raise SystemExit(f"copia e goală: {acte} acte, {provizii} provizii")
        print(f"  acte      → {acte}")
        print(f"  provizii  → {provizii}")

        # An act picked from the file itself, then read back by id — the query the reader makes.
        act_id = con.execute("SELECT id FROM acte LIMIT 1").fetchone()[0]
        if not con.execute("SELECT count(*) FROM provizii WHERE act_id = ?", (act_id,)).fetchone()[
            0
        ]:
            raise SystemExit(f"actul {act_id} nu are provizii în copie")
        print(f"  un act    → {act_id}")

        # fts5 here is `content='provizii'`, an index with no copy of the text behind it. That is
        # exactly the thing a careless VACUUM or a dropped shadow table would break, so search has
        # to be exercised with a word the corpus actually contains.
        cuvant = next(
            (
                c
                for (text,) in con.execute("SELECT text FROM provizii WHERE text != '' LIMIT 40")
                for c in text.split()
                if len(c) > 5 and c.isalpha()
            ),
            None,
        )
        if cuvant is None:
            raise SystemExit("nu am găsit niciun cuvânt cu care să probez căutarea")
        gasite = con.execute(
            "SELECT count(*) FROM (SELECT act_id FROM provizii_fts"
            " WHERE provizii_fts MATCH ? LIMIT 5)",
            (cuvant,),
        ).fetchone()[0]
        if not gasite:
            raise SystemExit(f"căutarea nu găsește «{cuvant}», deși e în text: indexul e rupt")
        print(f"  căutare   → «{cuvant}» în {gasite} provizii")
    finally:
        con.close()


def _verifica_orice(tinta: Path) -> None:
    """The weaker check for the companion databases: it opens, and it is not empty.

    `graf.db` and `initiative.db` carry the citation edges and everything parliamentary. They keep
    all their tables — there is no build-time bulk to strip — but they are written in WAL like the
    corpus, and WAL is what `immutable=1` refuses. So they still have to pass through here.
    """
    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        tabele = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%_fts%'"
            )
        ]
        randuri = {}
        for t in tabele:
            try:
                randuri[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            except sqlite3.DatabaseError:
                continue
        if not any(randuri.values()):
            raise SystemExit(f"{tinta} nu are niciun rând în nicio tabelă")
        for t, n in sorted(randuri.items(), key=lambda x: -x[1])[:4]:
            print(f"  {t:<24} {n:>9,}")
    finally:
        con.close()


def _manifest(tinta: Path) -> Path:
    """Write, next to the published copy, the counts describing it.

    The headline the page opens with used to be counted per request. That is fine against a local
    file and ruinous against a remote one: `count(*)` over 3.302.558 provisions reads essentially
    the whole table, which over byte-range requests means gigabytes for a number that never
    changes between publications. So the counts are settled once, here, where the file is local.
    """
    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        m = {
            "acte": con.execute("SELECT count(*) FROM acte").fetchone()[0],
            "provizii": con.execute("SELECT count(*) FROM provizii").fetchone()[0],
            "acte_structurate": depozit._structurate_normative(con),
            "acte_normative": con.execute(
                f"SELECT count(*) FROM acte WHERE tip IN ({depozit._MARCAJE_NORMATIV})"
            ).fetchone()[0],
        }
    finally:
        con.close()
    cale = tinta.with_name("manifest.json")
    cale.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print(f"  manifest → {cale}: " + " · ".join(f"{k} {v:,}" for k, v in m.items()))
    return cale


def _gb(cale: Path) -> float:
    return cale.stat().st_size / 1e9


def publica(sursa: Path, tinta: Path, *, de_aruncat: tuple[str, ...] = DE_ARUNCAT) -> Path:
    """Write `tinta` as the published copy of `sursa`. Returns the path written.

    `de_aruncat` empty means "keep everything" — the companion databases need the WAL folded in
    and the file rebuilt, but have nothing to strip.
    """
    if not sursa.is_file():
        raise SystemExit(f"nu găsesc {sursa}")
    tinta.parent.mkdir(parents=True, exist_ok=True)

    inceput = time.time()
    print(f"copiez {_gb(sursa):.2f} GB → {tinta}", flush=True)
    shutil.copyfile(sursa, tinta)
    # A live corpus may have uncheckpointed pages sitting in its WAL; without them the copy is
    # stale, so bring the sidecars along and let SQLite fold them in below.
    for coada in ("-wal", "-shm"):
        vecin = sursa.with_name(sursa.name + coada)
        if vecin.is_file():
            shutil.copyfile(vecin, tinta.with_name(tinta.name + coada))
    print(f"  copiat în {time.time() - inceput:.0f}s", flush=True)

    con = sqlite3.connect(tinta)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")
        jurnal = con.execute("PRAGMA journal_mode").fetchone()[0]
        if jurnal.lower() != "delete":
            raise SystemExit(f"jurnalul a rămas {jurnal}; immutable=1 ar refuza fișierul")

        prezente = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for tabel in de_aruncat:
            if tabel in prezente:
                con.execute(f"DROP TABLE {tabel}")
                print(f"  aruncat {tabel}", flush=True)
        con.commit()

        print("VACUUM (rescrie fișierul, grupează proviziile fiecărui act) …", flush=True)
        inceput = time.time()
        con.execute("VACUUM")
        print(f"  vacuum în {time.time() - inceput:.0f}s", flush=True)
    finally:
        con.close()

    for coada in ("-wal", "-shm"):
        vecin = tinta.with_name(tinta.name + coada)
        if vecin.is_file():
            os.remove(vecin)

    _verifica(tinta) if de_aruncat else _verifica_orice(tinta)
    if de_aruncat:
        _manifest(tinta)

    marime = _gb(tinta)
    marja = GRATUIT_R2_GB - marime
    print(f"\n{tinta} · {marime:.2f} GB")
    print(
        f"nivel gratuit R2 = {GRATUIT_R2_GB:.0f} GB · "
        + (f"încape, marjă {marja:.2f} GB" if marja > 0 else f"DEPĂȘIT cu {-marja:.2f} GB")
    )
    return tinta


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sursa", type=Path, default=Path("corpus.db"))
    ap.add_argument("--tinta", type=Path, default=Path("publicat.db"))
    ap.add_argument(
        "--fel",
        choices=("corpus", "auxiliar"),
        default="corpus",
        help=(
            "'corpus' aruncă tabelele de construire; 'auxiliar' (graf.db, initiative.db) păstrează "
            "tot și doar scoate WAL-ul și rescrie fișierul, fiindcă immutable=1 refuză un -wal"
        ),
    )
    a = ap.parse_args(argv)
    publica(a.sursa, a.tinta, de_aruncat=DE_ARUNCAT if a.fel == "corpus" else ())


if __name__ == "__main__":
    main()
