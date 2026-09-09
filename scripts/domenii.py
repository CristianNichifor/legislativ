"""Grouping the corpus by who made the law, because that is what the corpus actually says.

A reader who wants "everything about health" wants a subject taxonomy, and the portal publishes
none: a page carries its type, its number, its year, its issuer and its text, and no classification
of any kind. So a subject grouping would have to be invented — from title keywords, or from a
model — and presented as though it were read. This package does not do that anywhere else and does
not start here.

What the documents *do* state is the body that issued them, on every single one: 488 distinct
issuers, no document without one. That is a real grouping and a useful one — the Ministry of
Health's orders are the health file in the sense the state itself keeps it — and every act in it is
there because its own page says so. The matrix has separate domain hints now, but those are labelled
as metadata evidence, not as this issuer grouping.

**Its limits, stated rather than discovered.** A ministry is not a subject: the Government issues
across every field at once and accounts for 51 344 documents on its own, so `Guvernul` is a large
box rather than a topic. Ministries are renamed and merged constantly — `Ministerul Culturii și
Identității Naționale` and `Ministerul Culturii` are the same file under two governments — and this
does not join them, because nothing in the data says they are the same body and a merge would be a
claim about machinery of government rather than about documents.

The second axis is the instrument: what kind of act a body issues says something about the power it
is exercising. A ministry issuing `ordin` is administering; Parliament issuing `lege` is
legislating. Both are read, neither is inferred.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Emitent:
    """One issuing body, with what it has issued."""

    nume: str
    acte: int
    tipuri: tuple[tuple[str, int], ...]
    de_la: str | None
    pana_la: str | None


def emitenti(con: sqlite3.Connection, *, limita: int = 60) -> list[Emitent]:
    """Every issuing body, busiest first, with the instruments it uses and the years it spans.

    Counted over `acte` rather than `documente`, because `acte` is what the rest of the package can
    open: a count over the archive would promise rows a reader cannot reach. Since namesakes each
    hold their own act row, the two numbers now differ only by documents never enriched.
    """
    randuri = con.execute(
        "SELECT emitent, tip, count(*) n, min(an) de_la, max(an) pana_la FROM acte"
        " WHERE emitent IS NOT NULL AND trim(emitent) <> ''"
        " GROUP BY emitent, tip"
    ).fetchall()
    pe_emitent: dict[str, list] = {}
    for emitent, tip, n, de_la, pana_la in randuri:
        pe_emitent.setdefault(emitent, []).append((tip, n, de_la, pana_la))
    iesire = [
        Emitent(
            nume=nume,
            acte=sum(x[1] for x in parti),
            tipuri=tuple(sorted(((t, n) for t, n, _, _ in parti), key=lambda x: -x[1])),
            de_la=str(min((x[2] for x in parti if x[2]), default="") or "") or None,
            pana_la=str(max((x[3] for x in parti if x[3]), default="") or "") or None,
        )
        for nume, parti in pe_emitent.items()
    ]
    return sorted(iesire, key=lambda e: -e.acte)[:limita]


def acte_ale(
    con: sqlite3.Connection, emitent: str, *, tip: str | None = None, limita: int = 50
) -> list[dict]:
    """What one body has issued, newest first.

    `cheie_citare` travels with each row, not just the act id: where an act took a qualified id
    because a namesake holds the bare key, the citation a reader would write is the bare one and
    the list has to show what they would have to type to find it again.
    """
    conditie = " AND tip = ?" if tip else ""
    argumente = [emitent] + ([tip] if tip else []) + [limita]
    # A store collected before namesakes had their own ids has no `cheie_citare`, and a read-only
    # connection does not run migrations — that is the ordinary state of a corpus being read while
    # a collector fills it. The id is the right stand-in: under the old rule it *was* the citation.
    are_cheie = any(r[1] == "cheie_citare" for r in con.execute("PRAGMA table_info(acte)"))
    coloana = "cheie_citare" if are_cheie else "id"
    return [
        {
            "act_id": r[0],
            "cheie_citare": r[1],
            "tip": r[2],
            "numar": r[3],
            "an": r[4],
            "titlu": r[5],
            "publicat": r[6],
        }
        for r in con.execute(
            f"SELECT id, {coloana}, tip, numar, an, titlu, publicat FROM acte"
            f" WHERE emitent = ?{conditie}"
            " ORDER BY an DESC, publicat DESC, numar DESC LIMIT ?",
            argumente,
        )
    ]
