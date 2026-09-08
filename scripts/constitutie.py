"""The Constitution, from the Chamber of Deputies.

It is cited 78.122 times by the rest of the corpus and was not in it. Not because the text is hard
to get, but because `surse.py` asks the ministry's portal only for acts struck by a decision of the
Court, and the Constitution has not been struck — so the repealed constitutions of 1866, 1923, 1938,
1948, 1952 and 1969 were all collected, and the one in force was not.

The source is `cdep.ro`, which publishes the text as revised by Legea nr. 429/2003 and confirmed
by Decizia Curţii Constituţionale nr. 3/2003, republished in Monitorul Oficial nr. 767 of 31
October 2003. That citation is the reason to prefer it over the unofficial sites carrying the same
words: those state neither which revision they show nor where it was published, and a provision
this tool quotes has to be one the reader can check.

The eight titles are eight pages, `par1=1..8`. Run:

    uv run python -m scripts.constitutie --db corpus.db
"""

from __future__ import annotations

import argparse
import html
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass

BAZA = "https://www.cdep.ro/ords/pls/dic/site.page?id=339&idl=1&par1="
TITLURI = range(1, 9)

ID_ACT = "constitutie-0-2003"
# What the rest of the corpus calls it when it cites it. Setting this is the whole point of the
# exercise: 78.122 references resolve to a document that is now present.
CHEIE = "constitutie"
TITLU = (
    "CONSTITUŢIA ROMÂNIEI republicată în MONITORUL OFICIAL nr. 767 din 31 octombrie 2003, "
    "modificată şi completată prin Legea de revizuire nr. 429/2003"
)

# An article's body ends at the *next article's marginal note*, not at its `ARTICOLUL` heading:
# the note anchor comes first in the markup, so stopping at the heading swallows it and the last
# paragraph of every article ends with the next article's title.
_ARTICOL = re.compile(
    r"<B>\s*ARTICOLUL\s*(?P<nr>\d+)\s*</B>\s*(?:<BR>)?(?P<corp>.*?)"
    r"(?=<A\s+NAME=\"[^\"]*sba\d+\"|<B>\s*ARTICOLUL|\Z)",
    re.I | re.S,
)
# The marginal note sits in the anchor just before the article, and is the article's own heading.
_NOTA = re.compile(r'<A\s+NAME="[^"]*sba(?P<nr>\d+)"[^>]*>(?P<nota>[^<]*)</A>', re.I)
_ALINEAT = re.compile(r"\((?P<nr>\d+)\)\s*(?P<text>.*?)(?=\(\d+\)|\Z)", re.S)
_ETICHETE = re.compile(r"<[^>]+>")
_SPATII = re.compile(r"\s+")


@dataclass(frozen=True)
class Prevedere:
    locator: str
    text: str


def _curata(brut: str) -> str:
    return _SPATII.sub(" ", html.unescape(_ETICHETE.sub(" ", brut))).strip()


def _adu(url: str, pauza: float) -> str:
    cerere = urllib.request.Request(url, headers={"User-Agent": "legislativ/1.0"})
    with urllib.request.urlopen(cerere, timeout=30) as r:
        brut = r.read()
    time.sleep(pauza)
    for codec in ("utf-8", "iso-8859-2", "cp1250"):
        try:
            return brut.decode(codec)
        except UnicodeDecodeError:
            continue
    return brut.decode("utf-8", "replace")


def parseaza(pagina: str) -> list[Prevedere]:
    """The articles of one title page, as `art7.alin2` provisions plus each article's heading."""
    note = {m.group("nr"): _curata(m.group("nota")) for m in _NOTA.finditer(pagina)}
    iesire: list[Prevedere] = []
    for m in _ARTICOL.finditer(pagina):
        nr = m.group("nr")
        corp = m.group("corp")
        nota = note.get(nr, "")
        if nota:
            iesire.append(Prevedere(f"art{nr}", nota))
        alineate = list(_ALINEAT.finditer(corp))
        if alineate:
            for a in alineate:
                text = _curata(a.group("text"))
                if text:
                    iesire.append(Prevedere(f"art{nr}.alin{a.group('nr')}", text))
        else:
            # Articles with a single unnumbered paragraph — most of Title I carries one.
            text = _curata(corp)
            if text:
                iesire.append(Prevedere(f"art{nr}.alin1", text))
    return iesire


def adu_tot(*, pauza: float = 0.5, log=print) -> list[Prevedere]:
    toate: list[Prevedere] = []
    for t in TITLURI:
        pagina = _adu(f"{BAZA}{t}", pauza)
        gasite = parseaza(pagina)
        log(f"  titlul {t}: {len(gasite)} prevederi")
        toate.extend(gasite)
    return toate


def scrie(db: str, prevederi: list[Prevedere], *, log=print) -> None:
    if not prevederi:
        raise SystemExit("nu am extras nicio prevedere; nu scriu nimic")
    articole = {p.locator.split(".")[0] for p in prevederi}
    if len(articole) < 150:
        # The Constitution has 156 articles. Fewer means the page layout moved and the parse is
        # partial — writing a partial constitution is worse than writing none.
        raise SystemExit(f"doar {len(articole)} articole extrase din 156; parsarea e incompletă")

    con = sqlite3.connect(db, timeout=60.0)
    con.execute("PRAGMA busy_timeout = 60000")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM provizii WHERE act_id = ?", (ID_ACT,))
        con.execute("DELETE FROM acte WHERE id = ?", (ID_ACT,))
        con.execute(
            "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
            " sursa_url, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ID_ACT,
                CHEIE,
                "constitutie",
                "0",
                2003,
                TITLU,
                "PARLAMENTUL",
                "2003-10-31",
                f"{BAZA}1",
                time.strftime("%Y-%m-%d"),
            ),
        )
        con.executemany(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
            [(ID_ACT, p.locator, n, p.text) for n, p in enumerate(prevederi)],
        )
        con.commit()
    finally:
        con.close()
    log(f"scris {ID_ACT}: {len(articole)} articole · {len(prevederi)} prevederi")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--pauza", type=float, default=0.5, help="secunde între cele opt cereri")
    a = ap.parse_args(argv)
    scrie(a.db, adu_tot(pauza=a.pauza))


if __name__ == "__main__":
    main()
