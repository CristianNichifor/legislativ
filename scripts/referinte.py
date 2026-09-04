"""What a passage of Romanian law points at: which act, and which provision inside it.

Everything else in this package is built on this module. An amendment is a reference plus a
verb, an unfulfilled deadline is a reference that nothing points back at, and a hallucinated
finding is one whose reference is not in the context the model was given. Get the reference
wrong and every layer above it is wrong in a way that still reads fluently.

**Romanian declines its citations, and the accusative is not the common case.** Acts are cited
far more often in the genitive than the nominative — `prevederile Legii nr. 98/2016`,
`art. 5 din Ordonanța de urgență a Guvernului nr. 57/2019`, `în aplicarea Hotărârii Guvernului
nr. 395/2016`. A pattern written only for `Legea` misses most of the corpus, and misses it
silently. Every act form here is matched in both nominative and genitive, and
`test_referinte.py` carries the genitive of each type for that reason.

**Ministerial order numbers contain full stops.** `Ordinul ministrului finanțelor publice
nr. 1.802/2014` is order one thousand eight hundred and two, not order 1. A number pattern
of `\\d+` reads it as `1`, produces the id `ordin-1-2014`, and then happily merges it with a
different order actually numbered 1 — two unrelated acts collapsed into one node, which is
worse than dropping the citation. Numbers therefore allow dotted thousands and strip them.

**A locator with no act attached is not a missing act.** `La articolul 7, alineatul (2) se
modifică` inside Legea 98/2016 means article 7 *of that same law*. Internal references are the
majority of references in any act, and treating them as unresolved would empty the graph. They
are returned with `act=None`, and binding them to their host act is the caller's job, because
only the caller knows which act it is reading.

Every reference carries the exact span it was read from. That is not diagnostics — it is what
lets a finding quote the law verbatim instead of paraphrasing it, which is the rule this
repository runs on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from scripts.text import normalizeaza

# Ordered longest-first inside each alternation: `Ordonanța de urgență a Guvernului` has to be
# tried before `Ordonanța Guvernului`, or the shorter pattern claims the prefix and the act
# comes out as an ordinary ordonanță — a different instrument with a different legal weight.
TIPURI: Final[dict[str, str]] = {
    "oug": r"(?:Ordonanț(?:a|ei)\s+de\s+urgenț(?:ă|a)(?:\s+a\s+Guvernului)?|O\.?\s?U\.?\s?G\.?)",
    "og": r"(?:Ordonanț(?:a|ei)(?:\s+Guvernului)?|O\.?\s?G\.?)",
    "hg": r"(?:Hot(?:ă|a)r(?:â|a)r(?:ea|ii)(?:\s+Guvernului)?|H\.?\s?G\.?)",
    "lege": r"(?:Leg(?:ea|ii)|Lege)",
    "ordin": r"(?:Ordin(?:ul|ului)?(?:\s+(?:comun\s+)?(?:al\s+)?ministrului[^,;\n]{0,80}?)?)",
    "decret": r"(?:Decret(?:ul|ului)?)",
}

# Codes and the Constitution are cited by name and never by number, so they need their own
# pass. `Codul fiscal` is an act like any other in the graph; it simply has no nr./year.
_NUMITE: Final[list[tuple[str, str]]] = [
    ("constitutie", r"Constituți(?:a|ei)(?:\s+Rom(?:â|a)niei)?"),
    ("cod-procedura-civila", r"Codul(?:ui)?\s+de\s+procedur(?:ă|a)\s+civil(?:ă|a)"),
    ("cod-procedura-penala", r"Codul(?:ui)?\s+de\s+procedur(?:ă|a)\s+penal(?:ă|a)"),
    ("cod-fiscal", r"Codul(?:ui)?\s+fiscal"),
    ("cod-procedura-fiscala", r"Codul(?:ui)?\s+de\s+procedur(?:ă|a)\s+fiscal(?:ă|a)"),
    ("cod-muncii", r"Codul(?:ui)?\s+muncii"),
    ("cod-civil", r"Codul(?:ui)?\s+civil"),
    ("cod-penal", r"Codul(?:ui)?\s+penal"),
    ("cod-administrativ", r"Codul(?:ui)?\s+administrativ"),
]

# 1.802/2014 and 98/2016 are both valid. The dot is a thousands separator, not a section mark.
_NUMAR = r"\d{1,3}(?:\.\d{3})+|\d{1,5}"
_NR_AN = rf"(?:nr\.?\s*)?(?P<numar>{_NUMAR})\s*/\s*(?P<an>(?:19|20)\d{{2}})"


def _cu_grupuri(tip: str) -> str:
    """Each act type needs its own capture-group names, since they share one alternation."""
    return _NR_AN.replace("numar", f"{tip}_numar").replace("an", f"{tip}_an")


_ACTE = re.compile(
    "|".join(rf"(?P<{tip}>{sablon}\s*,?\s*{_cu_grupuri(tip)})" for tip, sablon in TIPURI.items()),
    re.IGNORECASE,
)
_ACTE_NUMITE = re.compile(
    "|".join(rf"(?P<{tip.replace('-', '_')}>{sablon})" for tip, sablon in _NUMITE),
    re.IGNORECASE,
)

_REPUBLICATA = re.compile(r"republicat(?:ă|a|)\b", re.IGNORECASE)
_CU_MODIFICARI = re.compile(
    r"cu\s+modific(?:ă|a)rile\s+(?:și|si|ș|s)?\s*(?:complet(?:ă|a)rile\s+)?ulterioare",
    re.IGNORECASE,
)

# `12^1` is one article number. `12` followed by a separate `1` is two.
_NR_ART = r"\d+(?:\^\d+)?"
# Genitive again, and it is where the first version of this module lost half its locators:
# `alineatul (3) al articolului 8` declines the second noun, and a pattern written for
# `articolul` matches `articol` + `ul` and then meets `ui`, fails, and returns a locator with
# no article — an amendment to alineat 3 of nothing.
_SUF = r"(?:ul(?:ui)?|e(?:le|lor)?)?"
_ARTICOL = rf"(?:articol{_SUF}|art\.?)\s*(?P<articol>{_NR_ART})"
_ALINEAT = rf"(?:alineat{_SUF}|alin\.?)\s*\(?(?P<alineat>{_NR_ART})\)?"
_LITERA = r"(?:liter(?:a|ei|ele|elor)|lit\.?)\s*(?P<litera>[a-zș][\^\d]*)\s*\)"
_PUNCT = rf"(?:punct{_SUF}|pct\.?)\s*(?P<punct>{_NR_ART})"

_LOCATOR = re.compile(
    rf"(?:{_ARTICOL})?"
    rf"(?:\s*,?\s*(?:{_ALINEAT}))?"
    rf"(?:\s*,?\s*(?:{_LITERA}))?"
    rf"(?:\s*,?\s*(?:{_PUNCT}))?",
    re.IGNORECASE,
)

# What can stand between a locator and the act it belongs to: `art. 5 din Legea ...`,
# `alin. (2) al art. 7 din ...`. Anything longer and the two are unrelated neighbours.
_LEGATURA = re.compile(
    r"^\s*,?\s*(?:din|ale?|ai|dinaintea|prev(?:ă|a)zut[eă]?\s+(?:la|de|în|in))\s+$",
    re.IGNORECASE,
)
# What can join two halves of one position: `alineatul (3) al articolului 8`, and the anchor
# form `la articolul 9, după alineatul (2)`. Kept here rather than in the amendment layer
# because a reference is a reference wherever it is read from, and having the two modules
# disagree about what `alineatul (3) al articolului 8` means is how the graph acquires an
# edge to article 8 as a whole.
_LEGATURA_LOC = re.compile(
    r"^\s*,?\s*(?:al|ale|a|ai|din|de\s+la|dup(?:ă|a)|(?:î|i)nainte\s+de)\s+$", re.IGNORECASE
)


@dataclass(frozen=True)
class Act:
    """An act as cited, not as it exists. Two citations of the same law produce equal Acts."""

    tip: str
    numar: str | None = None
    an: int | None = None
    republicata: bool = False
    cu_modificari: bool = False

    @property
    def id(self) -> str:
        """The node key. `republicată` and `cu modificările ulterioare` are deliberately not in
        it: they qualify *which version* is meant, and version is a property of the edge's date,
        not a separate act. Folding them into the id would split Legea 98/2016 into three laws."""
        if self.numar is None:
            return self.tip
        return f"{self.tip}-{self.numar}-{self.an}"


@dataclass(frozen=True)
class Locator:
    """A position inside an act, at whatever depth the citation actually gave."""

    articol: str | None = None
    alineat: str | None = None
    litera: str | None = None
    punct: str | None = None

    def __bool__(self) -> bool:
        return any((self.articol, self.alineat, self.litera, self.punct))

    @property
    def id(self) -> str:
        parti = [
            p
            for p in (
                f"art{self.articol}" if self.articol else None,
                f"alin{self.alineat}" if self.alineat else None,
                f"lit{self.litera}" if self.litera else None,
                f"pct{self.punct}" if self.punct else None,
            )
            if p
        ]
        return ".".join(parti)


@dataclass(frozen=True)
class Referinta:
    """One citation, with the span it was read from so a finding can quote it."""

    act: Act | None
    locator: Locator
    text: str
    start: int
    end: int

    @property
    def este_interna(self) -> bool:
        return self.act is None


def _numar_curat(brut: str) -> str:
    return brut.replace(".", "")


def _calificatori(text: str, sfarsit: int) -> tuple[bool, bool, int]:
    """`, republicată, cu modificările și completările ulterioare` trails the citation.

    The window reaches 120 characters because the qualifier sits *after* the act's title —
    `Legea nr. 98/2016 privind achizițiile publice, republicată` — and a window that stopped at
    the number would have found the qualifier on no act that carries a long title, which is
    most of them. Neither flag enters the act id, so a qualifier picked up from a neighbouring
    citation costs nothing; missing one on the act that has it would understate how amended a
    law is."""
    coada = text[sfarsit : sfarsit + 120]
    republicata = _REPUBLICATA.search(coada)
    modificari = _CU_MODIFICARI.search(coada)
    intindere = sfarsit
    for m in (republicata, modificari):
        if m is not None:
            intindere = max(intindere, sfarsit + m.end())
    return bool(republicata), bool(modificari), intindere


def acte(text: str) -> list[Referinta]:
    """Every act cited in the passage, in the order they appear."""
    text = normalizeaza(text)
    gasite: list[Referinta] = []
    for m in _ACTE.finditer(text):
        tip = m.lastgroup
        tip = next(t for t in TIPURI if m.group(t) is not None)
        numar = _numar_curat(m.group(f"{tip}_numar"))
        an = int(m.group(f"{tip}_an"))
        republicata, modificari, sfarsit = _calificatori(text, m.end())
        gasite.append(
            Referinta(
                act=Act(tip, numar, an, republicata, modificari),
                locator=Locator(),
                text=text[m.start() : sfarsit],
                start=m.start(),
                end=sfarsit,
            )
        )
    for m in _ACTE_NUMITE.finditer(text):
        if any(r.start <= m.start() < r.end for r in gasite):
            continue
        tip = next(t for t, _ in _NUMITE if m.group(t.replace("-", "_")) is not None)
        gasite.append(
            Referinta(
                act=Act(tip),
                locator=Locator(),
                text=m.group(0),
                start=m.start(),
                end=m.end(),
            )
        )
    return sorted(gasite, key=lambda r: r.start)


def locatori(text: str) -> list[tuple[Locator, int, int]]:
    """Every internal position cited, with its span. Empty matches are discarded."""
    text = normalizeaza(text)
    gasite: list[tuple[Locator, int, int]] = []
    pozitie = 0
    while pozitie < len(text):
        m = _LOCATOR.search(text, pozitie)
        if m is None:
            break
        if m.end() == m.start():
            pozitie = m.start() + 1
            continue
        loc = Locator(
            articol=m.group("articol"),
            alineat=m.group("alineat"),
            litera=m.group("litera"),
            punct=m.group("punct"),
        )
        if loc:
            # The leading `\s*,?` of the optional groups can swallow the separator before the
            # locator. Trimming it keeps the span quotable and keeps the gap between two
            # locators readable as the joining word it is.
            start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip(" ,")))
            gasite.append((loc, start, m.end()))
        pozitie = m.end()
    return gasite


def uneste(locuri: list[tuple[Locator, int, int]], text: str) -> list[tuple[Locator, int, int]]:
    """`Alineatul (3) al articolului 8` is one position, written inside out.

    Romanian puts the deeper unit first and hangs the shallower one off it in the genitive. Read
    as two locators it becomes a reference to alineat 3 of nothing plus a reference to article 8
    entire — and the second of those, in an abrogating sentence, reports a whole article repealed
    when only one paragraph was.
    """
    unite: list[tuple[Locator, int, int]] = []
    for loc, start, end in locuri:
        if unite:
            precedent, p_start, p_end = unite[-1]
            ciocnire = any(
                getattr(precedent, camp) and getattr(loc, camp)
                for camp in ("articol", "alineat", "litera", "punct")
            )
            if _LEGATURA_LOC.match(text[p_end:start]) and not ciocnire:
                unite[-1] = (
                    Locator(
                        articol=precedent.articol or loc.articol,
                        alineat=precedent.alineat or loc.alineat,
                        litera=precedent.litera or loc.litera,
                        punct=precedent.punct or loc.punct,
                    ),
                    p_start,
                    end,
                )
                continue
        unite.append((loc, start, end))
    return unite


def referinte(text: str) -> list[Referinta]:
    """Acts and positions, with each position bound to its act where the sentence binds them.

    A locator binds to the act that follows it only across a joining word — `art. 5 din Legea
    nr. 98/2016`. Adjacency alone is not enough: in `art. 5 se modifică. Legea nr. 50/1991 se
    abrogă` the two are in different sentences and binding them would invent an amendment.
    """
    text = normalizeaza(text)
    gasite_acte = acte(text)
    rezultat: list[Referinta] = []
    consumate: set[int] = set()

    for loc, start, end in uneste(locatori(text), text):
        legat = None
        for i, ref in enumerate(gasite_acte):
            if ref.start < end:
                continue
            if _LEGATURA.match(text[end : ref.start]):
                legat = i
            break
        if legat is None:
            rezultat.append(Referinta(None, loc, text[start:end], start, end))
        else:
            ref = gasite_acte[legat]
            consumate.add(legat)
            rezultat.append(Referinta(ref.act, loc, text[start : ref.end], start, ref.end))

    for i, ref in enumerate(gasite_acte):
        if i not in consumate:
            rezultat.append(ref)
    return sorted(rezultat, key=lambda r: r.start)
