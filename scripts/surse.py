"""The portal's own document pages, fetched once and kept.

The SOAP service returns an act's text already flattened. No heading a parser can trust, no
paragraph breaks — so `provizii` holds one row per document, `locator = 'text'`, and nothing below
the act is addressable. That is why `prevedere.py` can quote only two thirds of the struck
provisions and why `art. 81 alin. 4` is unrecoverable: the words survived, the structure did not.

The structure is on the HTML detail page of the same document, in the `S_ART` / `S_ALN` / `S_LIT`
markers `parsare.py` has always read. One fetch of the Penal Code yields 660 addressable
provisions where the corpus holds one.

**Fetched once.** A document's page does not change; a *new* document gets a new page. So this
follows the discipline the rest of the collection already uses — `publicare_incercata`,
`lovituri_extrase`, `progres` — and records that a document was **asked for**, whatever came back.
Resuming on "has no html" would re-ask the service for every act it has already refused, on every
run: a job that gets slower the longer it runs and hammers somebody else's server for an answer
that will not change.

**Fetched for what needs it, not for everything.** The measured average is 55 KB gzipped per act —
7.5 MB for the 135 struck acts in the corpus, and something on the order of 8 GB for all 152 079.
So `descarca` takes a work list, and `de_lovituri` is the one that pays for itself first: the acts
a Constitutional Court decision struck, which are exactly the ones the constitutionality check has
to quote. Those 135 yielded 44 059 addressable provisions in place of 135 flattened rows, and took
the register's exactly-quotable strikes from 82 to 106.

**One at a time, with a pause, identifying itself.** Same `USER_AGENT` as the collector, naming
the project and a contact address. This is a ministry's public server; the point of the store is
that the polite total is one request per document, ever.
"""

from __future__ import annotations

import argparse
import gzip
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from scripts import depozit
from scripts.api import USER_AGENT

# The service answers a cold request for a megabyte of markup in about 2.5 s; 60 leaves room for a
# slow one without letting a stalled connection hold the run.
TERMEN: float = 60.0


@dataclass(frozen=True)
class Descarcare:
    """What one run did, so it reports itself rather than being trusted."""

    cerute: int
    reusite: int
    esuate: int
    octeti: int
    secunde: float

    def __str__(self) -> str:
        mb = self.octeti / 1_048_576
        return (
            f"{self.cerute} documente cerute · {self.reusite} aduse ({mb:.1f} MB comprimați) · "
            f"{self.esuate} eșuate · {self.secunde:.0f}s"
        )


def de_lovituri(con: sqlite3.Connection) -> list[str]:
    """The acts a decision struck — the work list that pays for itself first.

    These are the acts the constitutionality check has to quote, and the ones where a flattened
    text costs a finding. Ordered so a run cut short has still done the most-cited acts.
    """
    return [
        r[0]
        for r in con.execute(
            "SELECT a.id_portal FROM acte a"
            " JOIN (SELECT DISTINCT act FROM lovituri WHERE act IS NOT NULL) l ON l.act = a.id"
            " WHERE a.id_portal IS NOT NULL AND a.id_portal != ''"
            " ORDER BY a.id"
        )
    ]


def de_facut(con: sqlite3.Connection, candidati: list[str]) -> list[tuple[str, str]]:
    """(id_portal, url) for the documents never asked for. The incremental half.

    A document already in `surse` is skipped whatever its `stare`: `ok` because the page is kept,
    a failure because re-asking on every run is what turns a fetch into a hammer. `reincearca`
    exists for when a caller decides a failure is worth one more try.
    """
    if not candidati:
        return []
    facute = {r[0] for r in con.execute("SELECT id_portal FROM surse")}
    iesire: list[tuple[str, str]] = []
    for id_portal in candidati:
        if id_portal in facute:
            continue
        rand = con.execute(
            "SELECT sursa_url, id_act_portal FROM acte WHERE id_portal = ?", (id_portal,)
        ).fetchone()
        url = depozit.url_document(rand[0], rand[1]) if rand else ""
        if url:
            iesire.append((id_portal, url))
    return iesire


def reincearca(cale_db: str = "corpus.db", *, stari: tuple[str, ...] = ("retea",)) -> int:
    """Forget failures of the given kinds so the next run asks again. Returns how many.

    Not every failure is an answer. A `retea` is this end's problem — a dropped connection, a
    timeout — and holding it for ever would mean one bad minute permanently costing a document.
    An `http-404` is the server's answer and stays: re-asking changes nothing.

    Deliberately a separate command rather than a retry policy inside `descarca`. A run that
    silently re-asks is the behaviour this store exists to prevent, so forgetting is something a
    person does on purpose.
    """
    with depozit.deschide(cale_db) as con:
        semne = ",".join("?" * len(stari))
        cur = con.execute(f"DELETE FROM surse WHERE stare IN ({semne})", stari)
        con.commit()
        return cur.rowcount


def _adu(url: str) -> tuple[bytes | None, str]:
    """One page. Returns (bytes, state) — never raises, so one bad document cannot end a run."""
    cerere = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(cerere, timeout=TERMEN) as raspuns:
            brut = raspuns.read()
            if raspuns.headers.get("Content-Encoding") == "gzip":
                brut = gzip.decompress(brut)
    except urllib.error.HTTPError as e:
        return None, f"http-{e.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "retea"
    return (brut, "ok") if brut.strip() else (None, "gol")


def descarca(
    cale_db: str = "corpus.db",
    *,
    candidati: list[str] | None = None,
    limita: int | None = None,
    pauza: float = 0.5,
    log=print,
) -> Descarcare:
    """Fetch the document pages not yet asked for, and keep them."""
    t0 = time.monotonic()
    cerute = reusite = esuate = octeti = 0

    with depozit.deschide(cale_db) as con:
        lista = de_facut(con, candidati if candidati is not None else de_lovituri(con))
        if limita is not None:
            lista = lista[:limita]
        log(f"{len(lista)} documente de adus (restul sunt deja cerute o dată)")

        for i, (id_portal, url) in enumerate(lista, start=1):
            brut, stare = _adu(url)
            cerute += 1
            comprimat = gzip.compress(brut, 6) if brut else None
            if brut:
                reusite += 1
                octeti += len(comprimat)
            else:
                esuate += 1
            con.execute(
                "INSERT OR REPLACE INTO surse (id_portal, url, html, octeti, stare, incercat_la)"
                " VALUES (?,?,?,?,?,?)",
                (
                    id_portal,
                    url,
                    comprimat,
                    len(brut) if brut else None,
                    stare,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            if i % 10 == 0 or i == len(lista):
                con.commit()
                log(f"  {i}/{len(lista)} · {reusite} aduse · {esuate} eșuate")
            if i < len(lista):
                time.sleep(pauza)

    return Descarcare(cerute, reusite, esuate, octeti, time.monotonic() - t0)


def html(con: sqlite3.Connection, id_portal: str) -> str | None:
    """The stored page, decompressed. `None` where it was never fetched or the fetch failed."""
    rand = con.execute("SELECT html FROM surse WHERE id_portal = ?", (id_portal,)).fetchone()
    if rand is None or rand[0] is None:
        return None
    return gzip.decompress(rand[0]).decode("utf-8", "replace")


def imbogateste(cale_db: str = "corpus.db", *, limita: int | None = None, log=print) -> dict:
    """Upgrade acts from their stored page: one flattened row becomes the real article tree.

    The act's identity is *not* taken from the parse. `parsare.parseaza` reads the page's own
    title, and for a code that yields `necunoscut` — the corpus knows the act is
    `codul-penal-0-1997` because it collected it under that key, and a page that cannot name
    itself must not be allowed to rename it. Only the provisions are written
    (`depozit.scrie_provizii`), so the act's reconciled publication date survives.

    An act whose page parses to nothing keeps the flattened row it already had. A worse corpus is
    not an upgrade.
    """
    from scripts.parsare import parseaza

    imbunatatite = provizii = sarite = 0
    with depozit.deschide(cale_db) as con:
        randuri = con.execute(
            "SELECT s.id_portal, s.url, a.id FROM surse s JOIN acte a ON a.id_portal = s.id_portal"
            " WHERE s.stare = 'ok' ORDER BY a.id"
        ).fetchall()
        if limita is not None:
            randuri = randuri[:limita]
        log(f"{len(randuri)} acte cu pagină stocată")

        for i, (id_portal, url, act_id) in enumerate(randuri, start=1):
            brut = html(con, id_portal)
            if brut is None:
                sarite += 1
                continue
            parsat = parseaza(brut, url)
            if len(parsat.provizii) <= 1:
                # One provision is what the act already has. Replacing a flattened row with
                # another flattened row costs an FTS rewrite and buys nothing.
                sarite += 1
                continue
            provizii += depozit.scrie_provizii(con, act_id, parsat.provizii)
            imbunatatite += 1
            if i % 20 == 0 or i == len(randuri):
                con.commit()
                log(f"  {i}/{len(randuri)} · {imbunatatite} acte · {provizii} provizii")
        con.commit()
    return {"imbunatatite": imbunatatite, "provizii": provizii, "sarite": sarite}


def rezumat(cale_db: str = "corpus.db") -> dict:
    """What the store holds — asked for, kept, and how much of it."""
    cx = sqlite3.connect(f"file:{cale_db}?mode=ro", uri=True)
    try:
        total, ok = cx.execute("SELECT count(*), sum(stare = 'ok') FROM surse").fetchone()
        octeti = cx.execute("SELECT sum(length(html)) FROM surse").fetchone()[0] or 0
        return {"cerute": total or 0, "pastrate": ok or 0, "octeti": octeti}
    finally:
        cx.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--limita", type=int, help="câte documente să aducă în această rulare")
    ap.add_argument(
        "--pauza",
        type=float,
        default=0.5,
        help="secunde între cereri. Serverul e al unui minister; nu-l grăbi.",
    )
    ap.add_argument(
        "--imbogateste",
        action="store_true",
        help="nu aduce nimic: parsează paginile deja stocate în arborele de articole",
    )
    ap.add_argument("--rezumat", action="store_true")
    a = ap.parse_args()

    if a.rezumat:
        r = rezumat(a.db)
        print(
            f"{r['cerute']} documente cerute · {r['pastrate']} păstrate · "
            f"{r['octeti'] / 1_048_576:.1f} MB"
        )
        return 0
    if a.imbogateste:
        r = imbogateste(a.db, limita=a.limita)
        print(f"\ngata: {r['imbunatatite']} acte structurate, {r['provizii']} provizii")
        return 0

    r = descarca(a.db, limita=a.limita, pauza=a.pauza)
    print(f"\ngata: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
