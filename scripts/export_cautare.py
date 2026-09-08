"""Export the corpus as records for the search indexer.

Search and the corpus want opposite things from storage. Opening a law is a point lookup, which the
mounted database does in 0,02 s; searching scans, and a scan over a mounted database is thousands
of serial synchronous range reads — a page of 25 results measured **46,6 s**. So the index is built
here, out of band, and the reader never scans anything at query time.

One record per act: its title, its full text, and the few fields the result list shows. Provisions
would be truer — a hit is really a hit on a provision — but 3.302.558 records is far past what a
static index can carry, and an act with an excerpt is what the page displays anyway.

Writes JSON Lines to stdout or `--tinta`, for `infra/pagefind.mjs` to index.

    uv run python -m scripts.export_cautare --db publicat.db --tinta acte.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


def exporta(db: str, iesire, *, limita: int | None = None, log=print) -> int:
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        # Ordered newest-first so a truncated run (`--limita`, for a trial index) is a sample of
        # current law rather than an arbitrary slice.
        sql = "SELECT id, tip, an, titlu FROM acte ORDER BY an DESC, numar"
        if limita:
            sql += f" LIMIT {int(limita)}"
        acte = con.execute(sql).fetchall()

        inceput, n = time.time(), 0
        for a in acte:
            text = " ".join(
                r[0]
                for r in con.execute(
                    "SELECT text FROM provizii WHERE act_id = ? ORDER BY ord", (a["id"],)
                )
            )
            iesire.write(
                json.dumps(
                    {
                        "id": a["id"],
                        "tip": a["tip"] or "",
                        "an": a["an"] or 0,
                        "titlu": a["titlu"] or "",
                        "text": text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            n += 1
            if n % 20000 == 0:
                log(f"  {n}/{len(acte)} acte · {time.time() - inceput:.0f}s", flush=True)
        log(f"  {n} acte exportate în {time.time() - inceput:.0f}s", flush=True)
        return n
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="publicat.db")
    ap.add_argument("--tinta", type=Path, help="fișierul JSONL; implicit stdout")
    ap.add_argument("--limita", type=int, help="doar primele N acte, pentru o probă")
    a = ap.parse_args(argv)

    if a.tinta:
        with a.tinta.open("w", encoding="utf-8") as f:
            exporta(a.db, f, limita=a.limita)
    else:
        exporta(a.db, sys.stdout, limita=a.limita, log=lambda *_, **__: None)


if __name__ == "__main__":
    main()
