"""What a deputy has put their name to, read from the initiatives already collected.

`parcurs.py` reads each Fișa's sponsors and stores one row per signature, carrying the Chamber's
own `idm` for the person. That is 68 625 signatures over 349 deputies and 12 parliamentary groups,
and it is enough to answer the question a voter asks about their representative: what have you
proposed, with whom, and what became of it.

Three things this refuses to do, because the data does not support them.

**A signature is not authorship.** Romanian initiatives are routinely co-signed by twenty or more
members, so "Deputy X proposed 633 bills" would be a claim about paperwork, not about work. Every
count here travels with how many people signed alongside, and a bill signed by sixty is reported as
what it is.

**A bill without a recorded vote is not a bill that failed.** Only 1 729 of 4 052 initiatives have
a division on their Fișa; the rest are still moving, or died without one. Those are counted in
their own column and never folded into either outcome, because a success rate computed over
"adopted / everything" would quietly convert a pending bill into a defeat.

**An outcome is not a deputy's outcome.** A vote is on the bill, and the bill carries every
signature on it. This reports what happened to the bills someone signed; it does not attribute the
result to them, and it does not rank people.

The parliamentary group travels with the *signature*, not with the person: the Fișa records the
group each member sat in when they signed, so a deputy who changed groups appears under both, which
is the historically accurate answer rather than a tidier wrong one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# The two group names the source writes without capitals or diacritics. Everything else in the
# column is an acronym — PSD, USR, PNL, AUR, UDMR, UPR, SOS RO, PACE, PMP — and must not be
# "corrected" into something the Chamber does not write. So this is a map of the two it spells
# wrongly, not a title-casing rule applied to a column it would damage.
GRUP_AFISAT: dict[str, str] = {
    "neafiliati": "Neafiliați",
    "Minoritati": "Minorități",
}


def grup_afisat(grup: str | None) -> str | None:
    return GRUP_AFISAT.get(grup or "", grup)


@dataclass(frozen=True)
class Mandat:
    """One term: what the Chamber's own link is keyed on, and what it carries."""

    idm: str
    leg: str | None
    camera: str | None
    nume: str
    grupuri: tuple[str, ...]
    initiative: int


@dataclass(frozen=True)
class Persoana:
    """One member, with every term they served.

    **The terms are grouped; the numbers are not.** `idm` is not stable across legislatures —
    Buzoianu Diana-Anda is 56 in 2020 and 48 in 2024 — and the Chamber publishes no id that is:
    the member page states the mandate history in prose and the photograph's filename is a name
    rendering, written two different ways (`HorgaMariaGabriela.JPG` against
    `Horga_Maria-Gabriela.jpg`, `Alina_Stefania_Gorghiu.jpg` against `GorghiuAlinaStefania.JPG`),
    so it identifies nothing the name does not.

    So the grouping is by diacritic-folded name, which is a guess, and it is confined to
    *navigation*. Measured over the collected corpus: 1 052 terms, 818 folded names, and **no name
    carried by two people in the same legislature and chamber** — so within a term the name is
    unambiguous, and only a cross-term collision is possible. Every count stays attached to its own
    term, so if two people ever are merged the card shows two labelled terms side by side rather
    than one wrong total.
    """

    nume: str
    mandate: tuple[Mandat, ...]

    @property
    def legislaturi(self) -> tuple[str, ...]:
        return tuple(sorted({m.leg for m in self.mandate if m.leg}, reverse=True))

    @property
    def initiative(self) -> int:
        return sum(m.initiative for m in self.mandate)


@dataclass(frozen=True)
class Semnatar:
    """One deputy, as the Chamber identifies them."""

    idm: str
    leg: str | None
    camera: str | None
    nume: str
    grupuri: tuple[str, ...]
    initiative: int


@dataclass(frozen=True)
class Soarta:
    """What became of the bills someone signed. `nedecise` is its own number on purpose."""

    adoptate: int
    respinse: int
    nedecise: int

    @property
    def cu_vot(self) -> int:
        return self.adoptate + self.respinse


def _fara_diacritice(s: str) -> str:
    from scripts.text import cheie

    return cheie(s)


def cauta(con: sqlite3.Connection, q: str, *, limita: int = 20) -> list[Semnatar]:
    """Deputies whose name matches, most prolific signer first.

    Grouped by `(leg, camera, idm)`, which is what the Chamber's own link is keyed on:
    `structura2015.mp?idm=56&leg=2020&cam=2`. All three are needed and each was learned the hard
    way. Keyed on `idm` alone, 349 values covered 1 044 people. Adding the legislature left 282
    pairs still covering more than one person — `idm=56, leg=2020` is Buzoianu Diana-Anda in the
    Chamber and Ghica Cristian in the Senate. With the chamber too, no key covers two names.

    Matched diacritic-folded, because the Fișe spell the same person `Şovăială` and `Șovăială` in
    the same legislature and a reader types neither.
    """
    if not q or not q.strip():
        return []
    tinta = _fara_diacritice(q)
    randuri = con.execute(
        "SELECT idm, leg, camera, nume, count(DISTINCT plx_id) n FROM initiativa_initiator"
        " WHERE idm IS NOT NULL GROUP BY leg, camera, idm ORDER BY n DESC"
    ).fetchall()
    gasiti = [r for r in randuri if tinta in _fara_diacritice(r[3] or "")][:limita]
    return [_semnatar(con, r[0], r[1], r[2], r[3], r[4]) for r in gasiti]


def toti(con: sqlite3.Connection, *, leg: str | None = None) -> list[Persoana]:
    """Every member the store knows, one entry each.

    The search answers "how did this person vote"; this answers "who are they" — the question of a
    reader who has no name to type, which is most readers. 1 052 terms group to 818 people, so the
    whole directory is one modest list rather than something that needs paging.
    """
    randuri = con.execute(
        "SELECT idm, leg, camera, nume, count(DISTINCT plx_id) n FROM initiativa_initiator"
        " WHERE idm IS NOT NULL" + (" AND leg = ?" if leg else "") + " GROUP BY leg, camera, idm",
        ([leg] if leg else []),
    ).fetchall()
    oameni = _grupeaza(con, [_semnatar(con, r[0], r[1], r[2], r[3], r[4]) for r in randuri])
    # Sorted diacritic-folded, so `Șovăială` files under Ș where a reader looks for it rather than
    # after Z, which is where a byte comparison puts it.
    return sorted(oameni, key=lambda p: _fara_diacritice(p.nume))


def _grupeaza(con: sqlite3.Connection, semnatari: list[Semnatar]) -> list[Persoana]:
    """Terms into people. See `Persoana` for why the key is the folded name, and why confining
    that guess to navigation is what makes it safe."""
    grupat: dict[str, list[Mandat]] = {}
    for s in semnatari:
        grupat.setdefault(_fara_diacritice(s.nume), []).append(
            Mandat(s.idm, s.leg, s.camera, s.nume, s.grupuri, s.initiative)
        )
    return [
        Persoana(
            # The name as the most recent term spells it: the Fișe change their spelling over the
            # years and the newest is the one a reader will recognise.
            nume=max(m, key=lambda x: (x.leg or "", x.idm)).nume,
            mandate=tuple(sorted(m, key=lambda x: x.leg or "", reverse=True)),
        )
        for m in grupat.values()
    ]


def persoane(con: sqlite3.Connection, q: str, *, limita: int = 20) -> list[Persoana]:
    """Members matching a name, one entry each, with every term they served.

    `cauta` returns one row per *term*, which is what the store is keyed on and what made the
    search list the same person twice. This groups those rows for navigation — see `Persoana` for
    why that grouping is a name match and why it is safe to make it here and nowhere else.

    Ordered by the most recent legislature first, then by how much the person signed, so a search
    for a common surname puts the sitting member above one who left in 2016.
    """
    iesire = _grupeaza(con, cauta(con, q, limita=limita * 4))
    return sorted(iesire, key=lambda p: (p.legislaturi[0] if p.legislaturi else "", p.initiative))[
        ::-1
    ][:limita]


def _semnatar(
    con: sqlite3.Connection, idm: str, leg: str | None, camera: str | None, nume: str, n: int
) -> Semnatar:
    grupuri = tuple(
        sorted(
            r[0]
            for r in con.execute(
                "SELECT DISTINCT grup FROM initiativa_initiator"
                " WHERE idm = ? AND leg IS ? AND camera IS ? AND grup IS NOT NULL",
                (idm, leg, camera),
            )
        )
    )
    return Semnatar(idm, leg, camera, nume, grupuri, n)


def soarta(
    con: sqlite3.Connection, idm: str, leg: str | None = None, camera: str | None = None
) -> Soarta:
    """What happened to the bills this deputy signed.

    Counted per initiative, not per vote row: a bill can be divided on more than once — in each
    chamber, or on a report and again on the whole — and counting rows would report one bill
    several times. The last recorded result on a bill is the one that stands.
    """
    randuri = con.execute(
        "SELECT i.plx_id, ("
        "  SELECT v.rezultat FROM initiativa_vot v WHERE v.plx_id = i.plx_id"
        "  AND v.rezultat IS NOT NULL ORDER BY v.data DESC LIMIT 1)"
        " FROM (SELECT DISTINCT plx_id FROM initiativa_initiator"
        "       WHERE idm = ? AND leg IS ? AND camera IS ?) i",
        (idm, leg, camera),
    ).fetchall()
    adoptate = sum(1 for _, r in randuri if r == "adoptat")
    respinse = sum(1 for _, r in randuri if r == "respins")
    return Soarta(adoptate, respinse, len(randuri) - adoptate - respinse)


def initiative(
    con: sqlite3.Connection,
    idm: str,
    leg: str | None = None,
    camera: str | None = None,
    *,
    limita: int = 1000,
) -> list[dict]:
    """The bills this deputy signed, newest first, each with how many signed it.

    The ceiling is high enough not to bite: the most prolific signer in the collected corpus is
    well under it, so "every bill" means every bill. It was 25, and a page that offered to show
    "all 25" of a member's 267 initiatives was not truncating, it was misreporting.

    The co-signer count is not decoration. A bill carrying sixty signatures says something
    different from one carrying two, and a list without it invites reading every row as this
    person's own initiative.
    """
    return [
        {
            "plx_id": r[0],
            "titlu": r[1],
            "stadiu": r[2],
            "data": r[3],
            "semnatari": r[4],
            "rezultat": r[5],
        }
        for r in con.execute(
            "SELECT ii.plx_id, i.titlu, i.stadiu, i.data_inreg,"
            "  (SELECT count(*) FROM initiativa_initiator x WHERE x.plx_id = ii.plx_id),"
            "  (SELECT v.rezultat FROM initiativa_vot v WHERE v.plx_id = ii.plx_id"
            "   AND v.rezultat IS NOT NULL ORDER BY v.data DESC LIMIT 1)"
            " FROM (SELECT DISTINCT plx_id FROM initiativa_initiator"
            "       WHERE idm = ? AND leg IS ? AND camera IS ?) ii"
            " LEFT JOIN initiative i ON i.plx_id = ii.plx_id"
            " ORDER BY i.data_inreg DESC LIMIT ?",
            (idm, leg, camera, limita),
        )
    ]


def legislaturi(con: sqlite3.Connection) -> list[str]:
    """Every legislature the store holds signatures for, newest first."""
    return [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT leg FROM initiativa_initiator WHERE leg IS NOT NULL ORDER BY leg DESC"
        )
    ]


def initiative_grup(
    con: sqlite3.Connection,
    grup: str,
    *,
    leg: str | None = None,
    rezultat: str | None = None,
    limita: int = 1000,
) -> list[dict]:
    """The bills a group's members signed, newest first, optionally by outcome.

    A group's row says 466 adopted and 975 with no recorded vote; those are counts of *bills* and
    a reader who sees them wants the list behind them. Counted and listed the same way, off the
    same query, so the number on the card and the length of the list cannot drift apart.

    `rezultat` is `adoptat`, `respins`, or `nedecis` — the last meaning no division was recorded,
    which is not a defeat and is why it is a third value rather than the absence of the first two.
    """
    unde_leg = " AND leg = ?" if leg else ""
    argumente: list = [grup] + ([leg] if leg else [])
    randuri = con.execute(
        "SELECT ii.plx_id, i.titlu, i.stadiu, i.data_inreg,"
        "  (SELECT count(*) FROM initiativa_initiator x WHERE x.plx_id = ii.plx_id),"
        "  (SELECT v.rezultat FROM initiativa_vot v WHERE v.plx_id = ii.plx_id"
        "   AND v.rezultat IS NOT NULL ORDER BY v.data DESC LIMIT 1)"
        " FROM (SELECT DISTINCT plx_id, leg FROM initiativa_initiator"
        f"       WHERE grup = ?{unde_leg}) ii"
        " LEFT JOIN initiative i ON i.plx_id = ii.plx_id"
        " ORDER BY i.data_inreg DESC",
        argumente,
    ).fetchall()
    iesire = [
        {
            "plx_id": r[0],
            "titlu": r[1],
            "stadiu": r[2],
            "data": r[3],
            "semnatari": r[4],
            "rezultat": r[5] or "nedecis",
        }
        for r in randuri
    ]
    if rezultat:
        iesire = [x for x in iesire if x["rezultat"] == rezultat]
    return iesire[:limita]


def grupuri(con: sqlite3.Connection, leg: str | None = None) -> list[dict]:
    """Every parliamentary group, with its members, its signatures and what became of them.

    `semnaturi` and `initiative` are different numbers and both are reported: twenty members of one
    group signing one bill is twenty signatures and one initiative, and showing only the first
    would make a group look busy for co-signing.

    `leg` narrows every number to one legislature. Without it a group's record is a sum across
    parliaments it was differently composed in — AUR in 2020 and AUR in 2024 are one row and two
    different sets of people — which reads as one continuous record and is not.
    """
    unde_leg = " AND leg = ?" if leg else ""
    iesire: list[dict] = []
    for grup, membri, semnaturi in con.execute(
        # Members counted as distinct (leg, camera, idm) triples, which is what the Chamber's own
        # link is keyed on. Counting ids alone reports one person where a group has had several
        # sit under the same number, and the pair without the chamber still merges a deputy with
        # a senator who share it.
        "SELECT grup, count(DISTINCT leg || '/' || camera || '/' || idm), count(*)"
        " FROM initiativa_initiator"
        f" WHERE grup IS NOT NULL AND idm IS NOT NULL{unde_leg} GROUP BY grup",
        ([leg] if leg else []),
    ).fetchall():
        randuri = con.execute(
            "SELECT ii.plx_id, ("
            "  SELECT v.rezultat FROM initiativa_vot v WHERE v.plx_id = ii.plx_id"
            "  AND v.rezultat IS NOT NULL ORDER BY v.data DESC LIMIT 1)"
            " FROM (SELECT DISTINCT plx_id FROM initiativa_initiator"
            f"       WHERE grup = ?{unde_leg}) ii",
            ([grup] + ([leg] if leg else [])),
        ).fetchall()
        adoptate = sum(1 for _, r in randuri if r == "adoptat")
        respinse = sum(1 for _, r in randuri if r == "respins")
        iesire.append(
            {
                "grup": grup_afisat(grup),
                "grup_brut": grup,
                "membri": membri,
                "semnaturi": semnaturi,
                "initiative": len(randuri),
                "adoptate": adoptate,
                "respinse": respinse,
                "nedecise": len(randuri) - adoptate - respinse,
            }
        )
    return sorted(iesire, key=lambda g: -g["semnaturi"])
