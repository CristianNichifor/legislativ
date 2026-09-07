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
import re
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from scripts import depozit
from scripts.api import USER_AGENT
from scripts.ritm import Ritm

# The service answers a cold request for a megabyte of markup in about 2.5 s; 60 leaves room for a
# slow one without letting a stalled connection hold the run.
TERMEN: float = 60.0

# How much of the archived text a parse must recover before it is allowed to replace the act's
# provisions. Below 1.0 only to absorb whitespace normalisation: a correct article tree exceeds the
# flat text, because provisions are stored at every level and an article's words are counted again
# in its alineate.
PRAG_TEXT: float = 0.98

# Where an act's body starts in the archived text. Everything before the first article marker is
# the title, the Monitorul Oficial line and the preamble — which the HTML page carries in its own
# markup and `parsare` does not put in a provision. On a long code that is a rounding error; on a
# four-page treaty it is a quarter of the characters, which is why comparing against the whole
# archive rejected 767 of 767 sampled acts whose articles had all been recovered correctly.
_PRIMUL_ARTICOL = re.compile(r"\b(?:Articolul|Art\.)\s*(?:\d|I\b|unic)", re.IGNORECASE)


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


def de_tot(con: sqlite3.Connection) -> list[str]:
    """Every act whose page has never been asked for, struck ones first and then newest.

    `de_lovituri` is the work list that pays for itself first and it is deliberately narrow: the
    acts a Curtea Constituțională decision struck, where a flattened text costs a finding. It is
    also the *default*, which meant a plain `descarca` never reached the rest of the corpus — and
    the rest of the corpus turned out to be the whole reason half the acts have no article tree.
    33 710 acts have no row in `surse` at all: not fetched and failed, never asked for. Every one
    of them is stored as a single flat provision, which is a 100% correlation and the diagnosis.

    Ordered struck-first to keep the existing priority, then by year descending, because a run cut
    short should have done the law people are reading rather than an alphabetical prefix.
    """
    lovite = de_lovituri(con)
    vazut = set(lovite)
    restul = [
        r[0]
        for r in con.execute(
            "SELECT id_portal FROM acte"
            " WHERE id_portal IS NOT NULL AND id_portal != ''"
            " ORDER BY an DESC, id"
        )
        if r[0] not in vazut
    ]
    return lovite + restul


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
    paralel: int = 1,
    rata: float = 2.0,
    log=print,
) -> Descarcare:
    """Fetch the document pages not yet asked for, and keep them.

    Serial by default, and that stays the default deliberately: this reads a ministry's website,
    and nothing should start several connections to it without someone having decided to.

    `paralel` opens more connections; `rata` is the ceiling they share. The two are separate dials
    and conflating them is the mistake worth naming. Twelve connections that each wait their turn
    against one clock is twelve times the throughput at the same load on the server; twelve that
    each sleep between their own requests is twelve times the load. Measured on this corpus, a page
    takes about a second to come back and 6 ms to compress, so the job is almost entirely waiting —
    the shape concurrency helps and faster code does not.

    Writes stay on this thread. SQLite takes one writer, and two collectors against one file has
    already killed a run today with `database is locked`.
    """
    t0 = time.monotonic()
    cerute = reusite = esuate = octeti = 0

    with depozit.deschide(cale_db) as con:
        lista = de_facut(con, candidati if candidati is not None else de_lovituri(con))
        if limita is not None:
            lista = lista[:limita]
        log(f"{len(lista)} documente de adus (restul sunt deja cerute o dată)")

        ritm = Ritm(rata) if paralel > 1 else None

        def adu_una(pereche):
            id_portal, url = pereche
            if ritm:
                ritm.asteapta()
            return pereche, _adu(url)

        if paralel > 1:
            with ThreadPoolExecutor(max_workers=paralel) as pool:
                rezultate = pool.map(adu_una, lista)
                for i, (pereche, (brut, stare)) in enumerate(rezultate, start=1):
                    cerute, reusite, esuate, octeti = _pastreaza(
                        con, pereche, brut, stare, cerute, reusite, esuate, octeti
                    )
                    if i % 25 == 0 or i == len(lista):
                        con.commit()
                        log(f"  {i}/{len(lista)} · {reusite} aduse · {esuate} eșuate")
        else:
            for i, pereche in enumerate(lista, start=1):
                brut, stare = _adu(pereche[1])
                cerute, reusite, esuate, octeti = _pastreaza(
                    con, pereche, brut, stare, cerute, reusite, esuate, octeti
                )
                if i % 10 == 0 or i == len(lista):
                    con.commit()
                    log(f"  {i}/{len(lista)} · {reusite} aduse · {esuate} eșuate")
                if i < len(lista):
                    time.sleep(pauza)

    return Descarcare(cerute, reusite, esuate, octeti, time.monotonic() - t0)


def _pastreaza(con, pereche, brut, stare, cerute, reusite, esuate, octeti):
    """Write one fetched page. A failure is stored too, so it is not asked for again."""
    id_portal, url = pereche
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
    return cerute + 1, reusite, esuate, octeti


def html(con: sqlite3.Connection, id_portal: str) -> str | None:
    """The stored page, decompressed. `None` where it was never fetched or the fetch failed."""
    rand = con.execute("SELECT html FROM surse WHERE id_portal = ?", (id_portal,)).fetchone()
    if rand is None or rand[0] is None:
        return None
    return gzip.decompress(rand[0]).decode("utf-8", "replace")


def imbogateste(
    cale_db: str = "corpus.db",
    *,
    limita: int | None = None,
    reia: bool = True,
    log=print,
) -> dict:
    """Upgrade acts from their stored page: one flattened row becomes the real article tree.

    The act's identity is *not* taken from the parse. `parsare.parseaza` reads the page's own
    title, and for a code that yields `necunoscut` — the corpus knows the act is
    `codul-penal-0-1997` because it collected it under that key, and a page that cannot name
    itself must not be allowed to rename it. Only the provisions are written
    (`depozit.scrie_provizii`), so the act's reconciled publication date survives.

    **An act whose page parses to less text than the archive holds keeps the flattened row.** That
    sentence used to be enforced by `len(parsat.provizii) <= 1` — a count, not a measurement — and
    the difference cost 54% of the acts this was run over. A page whose HTML yields three empty
    preamble paragraphs has three provisions, passes a count check, and replaces the act. Measured
    after the first full run: the Codul vamal went from 79 865 characters to 95, of which all that
    survived was `privind Codul vamal al României` and two more header fragments.

    So the test is on content, against `documente.text` — the archive the service returned, which
    is never rewritten and is therefore the only thing that still knows how much text the act has.
    Comparing against the *current* provisions would compare against the damage: a second run over
    an already-emptied act would find the parse no worse than what is there and accept it again.

    A real article tree comfortably exceeds the flat text, because provisions are stored at every
    level and an article's words are counted again in its alineate. Measured over acts that were
    correctly enriched, the ninetieth percentile is 1.53× the archive. The tolerance below 1.0 is
    only for whitespace normalisation, not for lost paragraphs.

    **`reia` skips acts that already hold a tree**, which is what makes this restartable. The store
    now holds 118 354 pages, so this is a job measured in hours, and without a skip a run that is
    interrupted at the ninety-thousandth act begins again at the first — re-parsing and rewriting
    everything it already did, including the FTS rows, which is the expensive half. A flattened act
    has exactly one provision and an enriched one has many, so "already has a tree" is a count, not
    a flag that could drift out of step with the data.

    Pass `reia=False` to re-parse everything, which is what a change to `parsare` calls for.
    """
    from scripts.parsare import parseaza

    imbunatatite = provizii = sarite = pierdute = 0
    with depozit.deschide(cale_db) as con:
        randuri = con.execute(
            "SELECT s.id_portal, s.url, a.id FROM surse s JOIN acte a ON a.id_portal = s.id_portal"
            " WHERE s.stare = 'ok' ORDER BY a.id"
        ).fetchall()
        total_pagini = len(randuri)
        if reia:
            # One scan for the whole set, not a count per act: at 118 354 acts the per-act form is
            # 118 354 aggregate queries before the first page is parsed.
            structurate = {
                r[0]
                for r in con.execute(
                    "SELECT act_id FROM provizii GROUP BY act_id HAVING count(*) > 1"
                )
            }
            randuri = [r for r in randuri if r[2] not in structurate]
        if limita is not None:
            randuri = randuri[:limita]
        log(f"{len(randuri)} acte de îmbogățit (din {total_pagini} cu pagină stocată)")

        for i, (id_portal, url, act_id) in enumerate(randuri, start=1):
            brut = html(con, id_portal)
            if brut is not None:
                parsat = parseaza(brut, url)
                if len(parsat.provizii) <= 1:
                    # One provision is what the act already has. Replacing a flattened row with
                    # another flattened row costs an FTS rewrite and buys nothing.
                    sarite += 1
                elif _pastreaza_textul(con, id_portal, parsat):
                    provizii += depozit.scrie_provizii(con, act_id, parsat.provizii)
                    imbunatatite += 1
                else:
                    pierdute += 1
            else:
                sarite += 1
            # Reported unconditionally, and that is the point. This used to sit after the
            # `continue` of every rejection, so a run that was refusing most acts printed nothing
            # at all: 100 754 acts to walk, four gigabytes read, and a log holding one line. It
            # read exactly like a hang, and was diagnosed as one for twenty minutes.
            if i % 200 == 0 or i == len(randuri):
                con.commit()
                log(
                    f"  {i}/{len(randuri)} · {imbunatatite} îmbogățite · {provizii} provizii"
                    f" · {pierdute} refuzate (ar fi pierdut text) · {sarite} fără structură"
                )
        con.commit()
    return {
        "imbunatatite": imbunatatite,
        "provizii": provizii,
        "sarite": sarite,
        "pierdute": pierdute,
    }


def _pastreaza_textul(con, id_portal: str, parsat) -> bool:
    """Whether this parse keeps what the archive holds, and so may replace the act's provisions.

    Measured against `documente.text`, which is never rewritten and is therefore the only thing
    that still knows how much text an act has. Comparing against the current provisions would
    compare against the damage: a second run over an act this already emptied would find the parse
    no worse than the fragments left behind and accept it again.
    """
    rand = con.execute("SELECT text FROM documente WHERE id_portal = ?", (id_portal,)).fetchone()
    arhiva = rand[0] if rand and rand[0] else ""
    if not arhiva:
        return True
    # Body against body. The comparison used to be against the whole archive, preamble included,
    # and the preamble is exactly what a correct parse leaves out — so acts whose every article had
    # been recovered were refused for losing their title. Measured over 767 of them, this accepts
    # 415 that the old rule rejected, and still refuses 309 that lose a median 9% of the body
    # itself. Where no article marker is found the whole archive is used, which is the conservative
    # reading: an act this cannot locate a body in is one to leave alone.
    m = _PRIMUL_ARTICOL.search(arhiva)
    referinta = arhiva[m.start() :] if m else arhiva
    recuperat = sum(len(p.text or "") for p in parsat.provizii)
    return recuperat >= len(referinta) * PRAG_TEXT


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
        "--de-la-capat",
        action="store_true",
        help="reparsează și actele care au deja arbore (după o schimbare în parsare)",
    )
    ap.add_argument(
        "--imbogateste",
        action="store_true",
        help="nu aduce nimic: parsează paginile deja stocate în arborele de articole",
    )
    ap.add_argument("--paralel", type=int, default=1, help="conexiuni simultane la aducere")
    ap.add_argument("--rata", type=float, default=2.0, help="cereri pe secundă, peste toate")
    ap.add_argument(
        "--toate",
        action="store_true",
        help="adu paginile tuturor actelor, nu doar ale celor lovite de o decizie",
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
        r = imbogateste(a.db, limita=a.limita, reia=not a.de_la_capat)
        print(f"\ngata: {r['imbunatatite']} acte structurate, {r['provizii']} provizii")
        return 0

    candidati = None
    if a.toate:
        with depozit.deschide(a.db, readonly=True) as con:
            candidati = de_tot(con)
    r = descarca(
        a.db,
        candidati=candidati,
        limita=a.limita,
        pauza=a.pauza,
        paralel=a.paralel,
        rata=a.rata,
    )
    print(f"\ngata: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
