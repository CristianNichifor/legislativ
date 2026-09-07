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
    limita: int = 25,
) -> list[dict]:
    """The bills this deputy signed, newest first, each with how many signed it.

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


def grupuri(con: sqlite3.Connection) -> list[dict]:
    """Every parliamentary group, with its members, its signatures and what became of them.

    `semnaturi` and `initiative` are different numbers and both are reported: twenty members of one
    group signing one bill is twenty signatures and one initiative, and showing only the first
    would make a group look busy for co-signing.
    """
    iesire: list[dict] = []
    for grup, membri, semnaturi in con.execute(
        # Members counted as distinct (leg, camera, idm) triples, which is what the Chamber's own
        # link is keyed on. Counting ids alone reports one person where a group has had several
        # sit under the same number, and the pair without the chamber still merges a deputy with
        # a senator who share it.
        "SELECT grup, count(DISTINCT leg || '/' || camera || '/' || idm), count(*)"
        " FROM initiativa_initiator"
        " WHERE grup IS NOT NULL AND idm IS NOT NULL GROUP BY grup"
    ):
        randuri = con.execute(
            "SELECT ii.plx_id, ("
            "  SELECT v.rezultat FROM initiativa_vot v WHERE v.plx_id = ii.plx_id"
            "  AND v.rezultat IS NOT NULL ORDER BY v.data DESC LIMIT 1)"
            " FROM (SELECT DISTINCT plx_id FROM initiativa_initiator WHERE grup = ?) ii",
            (grup,),
        ).fetchall()
        adoptate = sum(1 for _, r in randuri if r == "adoptat")
        respinse = sum(1 for _, r in randuri if r == "respins")
        iesire.append(
            {
                "grup": grup,
                "membri": membri,
                "semnaturi": semnaturi,
                "initiative": len(randuri),
                "adoptate": adoptate,
                "respinse": respinse,
                "nedecise": len(randuri) - adoptate - respinse,
            }
        )
    return sorted(iesire, key=lambda g: -g["semnaturi"])
