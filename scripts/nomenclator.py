"""The named acts, from what a citation calls them to what the corpus stored.

The Constitution and the codes are cited by name and never by number, so `referinte._NUMITE`
resolves them to a bare name: `constitutie`, `cod-penal`, `cod-procedura-civila`. The collector
keys an act by what its own title says, and the portal's titles are *COD PENAL*, *CODUL CIVIL*,
*CONSTITUȚIA ROMÂNIEI* — which `colector.slug_tip` turns into `codul-penal-0-1969`,
`codul-civil-0-2011`, `constitutie-0-1991`.

The two never met. Measured on the finished corpus: 7 419 acts — a quarter of everything the
corpus cites — looked uncollected while sitting in the database under the other name, and among
them the single most-cited act in Romanian law. `constitutie` carries 95 768 citations and eleven
stored versions, and not one of them was reachable from a citation.

**A name is not one act.** There are eleven constitutions in the corpus, from 1866 to 2003, and
two civil codes. So resolution takes a date and answers with the version in force then — the
latest at or before it — and with the most recent when no date is given, which is what a drafter
writing today means. Answering `constitutie` with the 1866 text would be worse than answering
nothing.

Standard library only, and a pure function over a set of ids: the caller supplies whatever it
knows, so the same code answers from a corpus on localhost and from the shard index in the browser.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

# `referinte` name -> the prefix `colector.slug_tip` derives from the portal's own title. Both
# halves are written out rather than computed: the portal says "COD PENAL" but "CODUL DE PROCEDURĂ
# PENALĂ", and a rule that guessed one from the other would be wrong for half of them.
PREFIXE: Final[dict[str, str]] = {
    "constitutie": "constitutie",
    "cod-civil": "codul-civil",
    "cod-penal": "codul-penal",
    "cod-fiscal": "codul-fiscal",
    "cod-muncii": "codul-muncii",
    "cod-administrativ": "codul-administrativ",
    "cod-procedura-civila": "codul-de-procedura-civila",
    "cod-procedura-penala": "codul-de-procedura-penala",
    "cod-procedura-fiscala": "codul-de-procedura-fiscala",
}

# `codul-penal-0-1969` — the `0` is the number slot a named act has no value for.
_VERSIUNE = re.compile(r"^(?P<prefix>.+)-0-(?P<an>\d{4})$")


def este_nume(act_id: str) -> bool:
    """Whether this id is a name awaiting resolution rather than a stored act."""
    return act_id in PREFIXE


def versiuni(nume: str, ids: set[str]) -> list[tuple[int, str]]:
    """(year, id) for every stored version of a named act, oldest first. Empty when none is held."""
    prefix = PREFIXE.get(nume)
    if not prefix:
        return []
    gasite: list[tuple[int, str]] = []
    for act_id in ids:
        m = _VERSIUNE.match(act_id)
        if m and m.group("prefix") == prefix:
            gasite.append((int(m.group("an")), act_id))
    return sorted(gasite)


def rezolva(nume: str, ids: set[str], la_data: date | None = None) -> str | None:
    """The stored act a name means, or None when the corpus holds no version of it.

    With a date, the version in force then — the latest published at or before it. Without one, the
    most recent, which is what a citation written today means. A date earlier than every version
    resolves to nothing rather than to the oldest: a 1991 draft did not cite the 2003 Constitution,
    and saying it did would be an invention.
    """
    disponibile = versiuni(nume, ids)
    if not disponibile:
        return None
    if la_data is None:
        return disponibile[-1][1]
    potrivite = [(an, act) for an, act in disponibile if an <= la_data.year]
    return potrivite[-1][1] if potrivite else None


# --- acts keyed under the wrong year ----------------------------------------------------------
#
# `colector._an` takes the year from the record, then from `data_vigoare`, and only then from the
# title. For a *republished* act `data_vigoare` is the republication date, so the act is filed
# under the year it was republished rather than the year it was passed:
#
#     lege-303-2005   "LEGE nr. 303 din 28 iunie 2004 (*republicată*) privind statutul
#                      judecătorilor și procurorilor"
#
# Every citation says `Legea nr. 303/2004` and finds nothing. Measured on the finished corpus:
# 20 715 documents — 10,1% — are filed under a year their own title contradicts, and the bias is
# the wrong way round, because an act gets republished precisely when it matters and keeps being
# amended. The most-cited law in the corpus is the most likely to be misfiled.
#
# This does not re-key anything. Re-keying would mean rewriting `acte`, the graph built on those
# ids, and `lovituri` — a migration, not a lookup. Here the stored id stays and the citation's id
# becomes an alias for it, which is the same shape as the named acts above.

_TITLU_AN = re.compile(r"\bdin\s+\d{1,2}\s+[a-zăâîșț]+\s+((?:1[6-9]|20)\d{2})", re.IGNORECASE)


def alias_an(con) -> dict[str, str]:
    """`tip-numar-anul-din-titlu` -> the id the corpus actually stored it under.

    Built from `documente`, which keeps every record, and restricted to ids `acte` really holds.

    **Ambiguous aliases are dropped, not guessed.** 1 130 of them are claimed by two different
    documents — two acts of the same type and number whose titles both point at one year. There is
    no way to choose without inventing, and inventing is the one thing this package does not do, so
    those citations keep resolving to nothing exactly as they did before.
    """
    titluri = {r[0]: r[1] or "" for r in con.execute("SELECT id, titlu FROM acte")}
    reali = set(titluri)
    candidat: dict[str, set[str]] = {}
    for cheie, tip, numar, an, titlu in con.execute(
        "SELECT cheie_act, tip, numar, an, titlu FROM documente"
        " WHERE numar IS NOT NULL AND numar <> '' AND an IS NOT NULL"
    ):
        m = _TITLU_AN.search(titlu or "")
        if not m:
            continue
        an_titlu = int(m.group(1))
        if an_titlu == an or cheie not in reali:
            continue
        candidat.setdefault(f"{tip}-{numar}-{an_titlu}", set()).add(cheie)
    # An alias that already names a real act is not an alias — the corpus holds both years.
    #
    # And the target has to *confirm* the year, because `acte` is a citation view where the last
    # writer wins and 53 242 documents share a key with another. Deduplicating on `cheie_act`
    # therefore does not mean one act: two unrelated laws can collapse into one row, and the row
    # that survived may be the other one. Measured before this check, 2 566 of 10 669 aliases —
    # 24% — pointed at an act from a different year, including `lege-303-2004` landing on a 2005
    # ratification law rather than the statute of judges. An alias that cannot be confirmed
    # against the stored act's own title is dropped.
    iesire: dict[str, str] = {}
    for alias, tinte in candidat.items():
        if len(tinte) != 1 or alias in reali:
            continue
        tinta = next(iter(tinte))
        m = _TITLU_AN.search(titluri.get(tinta, ""))
        if m and int(m.group(1)) == int(alias.rsplit("-", 1)[1]):
            iesire[alias] = tinta
    return iesire
