"""Which drafting norm a passage is written in — and whether a project mixes the two.

A reform can be drafted two ways. The **current register** (`actual`) is the impersonal, reflexive,
front-loaded style Legea nr. 24/2000 has always produced: *se modifică*, *prezentul act*,
*prevederile menționate mai sus*, numbers spelled out, one long sentence carrying every condition.
The **plain-language norm** (`nou`) is the Danish-guide style this package targets (see
`docs/STIL_DANEZ.md`): a named actor doing something in the active voice, one idea per sentence, a
plain duty (*trebuie să*), digits for numbers, conditions after the main statement.

A submitted project should be written **entirely in one** — never a paragraph of plain language
wedged between two paragraphs of the old register, which reads as two hands and hides where meaning
shifted. This module is the check for that: it classifies each unit of a text, then reports whether
the whole reads as one norm and, if not, exactly which units break from the majority.

Deterministic — standard library only, no model. The signals are the checkable half of
`docs/STIL_DANEZ.md`: presence of a marker is a fact, not a judgement. It is deliberately quiet —
a unit with no strong signal is `neutru` and never counts as a break, because the cost of a false
"you mixed norms" landing on a drafter is higher than the cost of staying silent on an ambiguous
line. The same asymmetry the terminology check makes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from scripts.text import fara_diacritice

# --- the markers -----------------------------------------------------------------------------
#
# Matched on the diacritic-folded, lower-cased form (via `_cheie`) so a draft typed without
# diacritics — the common case for a working document — is read the same as one with them. Each
# entry is (compiled pattern, weight); weight lets a load-bearing marker (`se modifica`) outvote a
# weak one. Patterns are written against the folded text, so `ă`→`a`, `ș`→`s`, `ț`→`t`.

# Current register: the reflexive-passive formulas, the self-referential "prezentul", the
# front-loaded participle, the archaic connectors, numbers spelled out.
_ACTUAL: tuple[tuple[re.Pattern[str], int], ...] = (
    # reflexive-passive legistic verbs — the single strongest tell of the old register
    (re.compile(r"\bse (?:modifica|completeaza|abroga|aproba|dispune|instituie|stabile[sș]te|"
                r"prevede|aplica|considera|efectueaza|realizeaza|desemneaza|deleaga|"
                r"abiliteaza|mandateaza|adopta)\b"), 3),
    (re.compile(r"\bprezent(?:ul|a|ei|ele|elor)\b"), 2),          # "prezentul act", "prezenta lege"
    (re.compile(r"\b(?:prevederile|dispozitiile|dispozitiunile)\b"), 2),
    (re.compile(r"\bpotrivit\b"), 1),
    (re.compile(r"\bin conformitate cu\b"), 1),
    (re.compile(r"\bsub sanctiunea\b"), 1),
    (re.compile(r"\b(?:sus-?mentionat|mai sus mentionat|mentionat(?:e|a)? mai sus)\b"), 2),
    (re.compile(r"\b(?:prevazut|prevazuta|prevazute|prevazuti)\b(?![^.]*\bcare\b)"), 1),
    (re.compile(r"\b(?:susmentionat|precitat|antemention)"), 1),
    # numbers spelled out, the current-register habit the plain norm drops for digits
    (re.compile(r"\b(?:unsprezece|doisprezece|treisprezece|paisprezece|cincisprezece|"
                r"saisprezece|saptesprezece|optsprezece|nouasprezece|douazeci|treizeci|"
                r"patruzeci|cincizeci|saizeci|saptezeci|optzeci|nouazeci|"
                r"o suta|doua sute|trei sute)\b"), 2),
)

# Plain-language norm: the named duty, direct address, conditions after the statement, digits.
_NOU: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\btrebuie sa\b"), 3),                            # a plain duty, named
    (re.compile(r"\bnu are voie sa\b"), 3),
    (re.compile(r"\b(?:are|au) dreptul\b"), 2),
    (re.compile(r"\b(?:poate|pot) sa\b"), 1),
    (re.compile(r"\beste obligat(?:a|i|e)? sa\b"), 2),
    (re.compile(r"^\s*daca\b[^.]*\batunci\b"), 3),                 # IF … THEN, the Danish shape
    (re.compile(r"\bnu poate depasi\b"), 1),
    # a bare digit + time-unit, the plain norm's "30 de zile" against the register's "treizeci"
    (re.compile(r"\b\d+\s+(?:zile|luni|ani|ore|zile lucratoare)\b"), 2),
)

_PROP = re.compile(r"[.!?]+")


def _cheie(text: str) -> str:
    """Fold to the form the markers are written against: no diacritics, lower-case, single space."""
    return re.sub(r"\s+", " ", fara_diacritice(text).lower()).strip()


@dataclass(frozen=True)
class Unitate:
    """One classified unit of a project — a paragraph or numbered point."""

    text: str
    norma: str  # "nou" | "actual" | "neutru"
    scor_nou: int
    scor_actual: int
    semnale: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Coerenta:
    """The verdict for a whole project: is it one norm, and if not, which units break?"""

    dominanta: str  # the majority norm among the non-neutral units ("nou" | "actual" | "neutru")
    coerent: bool
    unitati: tuple[Unitate, ...]
    abateri: tuple[Unitate, ...] = field(default=())

    def raport(self) -> str:
        """A one-screen human summary, in the register the rest of the package reports in."""
        et = {"nou": "limbaj clar", "actual": "normă curentă", "neutru": "neutru"}
        clasificate = [u for u in self.unitati if u.norma != "neutru"]
        if not clasificate:
            return "Niciun marcaj de stil clar — nu se poate stabili norma. Nimic de semnalat."
        if self.coerent:
            return f"Proiect coerent: tot textul este scris în {et[self.dominanta]}."
        linii = [
            f"Stil mixt: majoritatea textului este în {et[self.dominanta]}, dar "
            f"{len(self.abateri)} unități se abat:"
        ]
        for u in self.abateri:
            frag = u.text.strip().replace("\n", " ")
            frag = frag[:80] + "…" if len(frag) > 80 else frag
            linii.append(f'  • [{et[u.norma]}] „{frag}"')
        return "\n".join(linii)


def unitati(text: str) -> list[str]:
    """Split a project into the units a norm is judged per — points, then paragraphs.

    A numbered/lettered point (``1.`` / ``a)`` / ``(2)``) is the natural unit of a legistic text; a
    project without them falls back to blank-line paragraphs, and a single block to one unit. Empty
    fragments are dropped so an enumerator on its own line does not become a phantom unit.
    """
    brut = text.strip()
    if not brut:
        return []
    # a point marker at the start of a line: "1." / "12." / "a)" / "(2)" / "b)"
    marker = re.compile(r"(?m)^\s*(?:\(?\d+(?:\^\d+)?\)?[.)]|[a-zăâîșț]\))\s+")
    taieturi = [m.start() for m in marker.finditer(brut)]
    if len(taieturi) >= 2:
        buc = [brut[a:b] for a, b in zip([0, *taieturi], [*taieturi, len(brut)], strict=True)]
        return [u.strip() for u in buc if u.strip()]
    parag = [p.strip() for p in re.split(r"\n\s*\n", brut) if p.strip()]
    return parag or [brut]


def _potriviri(
    chei: str, markeri: tuple[tuple[re.Pattern[str], int], ...]
) -> tuple[int, list[str]]:
    scor = 0
    gasite: list[str] = []
    for pat, greutate in markeri:
        m = pat.search(chei)
        if m:
            scor += greutate
            gasite.append(m.group(0).strip())
    return scor, gasite


def clasifica(text: str) -> Unitate:
    """Read one unit and say which norm it is written in.

    The higher weighted score wins; a tie, or no marker at all, is `neutru`. A long unbroken
    sentence — the old register's habit of one clause carrying everything — adds a point to the
    current side, but only as a tie-breaker, never on its own: length is a weak signal and must not
    outvote an explicit marker.
    """
    chei = _cheie(text)
    scor_actual, sem_actual = _potriviri(chei, _ACTUAL)
    scor_nou, sem_nou = _potriviri(chei, _NOU)

    # one long sentence with no full stop mid-way leans old-register, as a tie-breaker only
    cuvinte = len(chei.split())
    propozitii = max(1, len([p for p in _PROP.split(chei) if p.strip()]))
    if cuvinte / propozitii > 35:
        scor_actual += 1

    if scor_actual > scor_nou:
        norma = "actual"
    elif scor_nou > scor_actual:
        norma = "nou"
    else:
        norma = "neutru"
    return Unitate(
        text=text,
        norma=norma,
        scor_nou=scor_nou,
        scor_actual=scor_actual,
        semnale=tuple(sem_nou + sem_actual),
    )


def coerenta(text: str) -> Coerenta:
    """Classify every unit and decide whether the project is written in a single norm.

    The dominant norm is the majority among the units that carry a signal; the neutral ones are
    counted for neither. A project is coherent when no classified unit disagrees with that majority.
    The disagreeing units are returned verbatim so the UI can point at them — the whole value of the
    check is saying *which* line broke the norm, not merely that one did.
    """
    us = [clasifica(u) for u in unitati(text)]
    clasificate = [u for u in us if u.norma != "neutru"]
    if not clasificate:
        return Coerenta(dominanta="neutru", coerent=True, unitati=tuple(us))

    numar = Counter(u.norma for u in clasificate)
    dominanta = numar.most_common(1)[0][0]
    abateri = tuple(u for u in clasificate if u.norma != dominanta)
    return Coerenta(
        dominanta=dominanta,
        coerent=not abateri,
        unitati=tuple(us),
        abateri=abateri,
    )
