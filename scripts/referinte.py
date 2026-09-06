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
from dataclasses import dataclass, replace
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
    # `Constituție` — the dictionary form — was missing, so `din Constituție` matched nothing at
    # all while `din Constituția` matched. It is the commonest way the word is written after a
    # preposition, which is the commonest way an act cites it.
    ("constitutie", r"Constituți(?:a|ei|e)(?:\s+Rom(?:â|a)niei)?"),
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

# `art. I` / `art. II` / `art. III` is the skeleton of every Romanian amending law — the Roman
# articles carry the amendments, the Arabic ones the substantive text, and both live in the same
# act. Reading only the Arabic ones does not lose the citation, it degrades it: the locator comes
# back empty and the reference reads as *the whole act*. Measured on the CCR register, that
# produced 109 of 215 rows claiming an entire law had been struck when the Court had struck one
# article, `Legea nr. 249/2006` among them.
#
# **`artII` is not `art2`.** They are different provisions of the same act and routinely coexist,
# so the numeral is kept in the locator as written rather than converted — converting would merge
# two unrelated texts under one id, which is the collision failure one level down.
#
# Two things make this safe to match. It is scoped **case-sensitive** inside an IGNORECASE
# pattern, because legal Romanian writes numerals in capitals and a case-blind `V?I{1,3}` reads
# the `vii` of `viitor` as article VII. And it requires a non-letter after it, so a numeral that
# is really the start of a word cannot end a match. Covers I–XXXIX, which is past any real
# article number.
_NR_ART_ROMAN = r"(?-i:(?:X{0,3}(?:IX|IV|V?I{1,3}|V)|X{1,3}))(?![A-Za-zĂÂÎȘȚăâîșț])"
# Genitive again, and it is where the first version of this module lost half its locators:
# `alineatul (3) al articolului 8` declines the second noun, and a pattern written for
# `articolul` matches `articol` + `ul` and then meets `ui`, fails, and returns a locator with
# no article — an amendment to alineat 3 of nothing.
_SUF = r"(?:ul(?:ui)?|e(?:le|lor)?)?"
# Arabic first, so a digit is never reached by the Roman branch.
_ARTICOL = rf"(?:articol{_SUF}|art\.?)\s*(?P<articol>{_NR_ART}|{_NR_ART_ROMAN})"
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
# `art. II alin. (1) și (3) din Legea nr. 249/2006` — the enumeration sits between the locator
# and the act it belongs to. Without allowing it here the locator never binds *and* the act comes
# through with an empty locator, so a citation of one paragraph reads as the whole law. That was
# the dominant source of the CCR register's whole-act rows.
#
# Bounded rather than open-ended: a real enumeration is a handful of numbers, and `*` here would
# let an arbitrary run of digits and commas join a locator to an act it has nothing to do with.
_ENUMERARE_COADA = r"(?:\s*(?:,|și|si|ori|sau)\s*\(?\d+(?:\^\d+)?\)?){0,10}"
_LEGATURA = re.compile(
    rf"^{_ENUMERARE_COADA}\s*,?\s*"
    r"(?:din|ale?|ai|dinaintea|prev(?:ă|a)zut[eă]?\s+(?:la|de|în|in))\s+$",
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

# `La articolele 7 și 8` names two articles, not one. The locator pattern stops at the first
# number — there is no `art`/`alin` keyword in front of the second — so everything after it used
# to be dropped, and an amendment to two articles was recorded against one. That is `ref-10` in
# the gold set, kept there as a known miss; this is what closes it.
#
# One number per step, so the run is read as far as it actually goes and no further, and bounded
# by the same reasoning as `_ENUMERARE_COADA`: a real enumeration is a handful of numbers, and an
# unbounded run would let a list of unrelated figures graft itself onto a locator.
#
# The separator is captured because a comma alone does not make an enumeration. `art. 5, 30 de
# zile de la publicare` is a deadline, `art. 7, 2024 a fost anul` is a year, `art. 5, 10% din
# valoare` is a share — and reading the number after the comma as an article invents `art. 30`,
# `art. 2024`, `art. 10`. Deadlines of the first kind are everywhere in Romanian law, so this is
# not a corner case. A real enumeration closes with a conjunction (`7, 8 și 9`), which is what
# `_conjunctie` below requires; a comma-only run is left unread. Missing one is a gap, inventing
# one is a false citation, and this package prefers the gap.
_COADA_NUMAR: Final[re.Pattern[str]] = re.compile(
    r"\s*(?P<sep>,|și|si|ori|sau)\s*\(?(?P<numar>\d+(?:\^\d+)?)\)?", re.IGNORECASE
)
_CONJUNCTIE: Final[frozenset[str]] = frozenset({"și", "si", "ori", "sau"})

# `lit. a) și b)` — the same enumeration one level down, in letters rather than digits. Left
# unexpanded when the numeric tail was written, because writing a digit into `litera` would have
# invented a position; read here with its own pattern instead.
_COADA_LITERA: Final[re.Pattern[str]] = re.compile(
    r"\s*(?P<sep>,|și|si|ori|sau)\s*(?P<litera>[a-zș](?:\^\d+)?)\s*\)", re.IGNORECASE
)

# `lit. a)-c)`, `art. 7-9`: a range names its ends and leaves the middle implied. Only the plain
# ascii letters expand — `ș` and a superscripted `a^1` are left alone rather than guessed a place
# for in a sequence this does not know. Bounded because a long run is more likely a misread than
# a citation: no real provision enumerates thirty articles by dash.
_INTERVAL_NUMAR: Final[re.Pattern[str]] = re.compile(r"\s*[-–—]\s*\(?(?P<pana>\d+)\)?")
_INTERVAL_LITERA: Final[re.Pattern[str]] = re.compile(r"\s*[-–—]\s*(?P<pana>[a-z])\s*\)")
_MAX_INTERVAL: Final[int] = 20
_MAX_ENUMERARE: Final[int] = 10
# Deepest first: the enumeration extends the innermost unit named, because that is the one being
# listed. `art. 5 alin. (2) și (3)` lists paragraphs of article 5, not articles.
_ADANCIME: Final[tuple[str, ...]] = ("punct", "litera", "alineat", "articol")


def _extinde(loc: Locator, numar: str) -> Locator | None:
    """The same position with its innermost unit replaced — one sibling of an enumeration.

    Returns None where the innermost unit is a letter (`lit. a) și b)`): the tail this reads is
    numeric, and writing a digit into `litera` would invent a position that cannot exist. Letter
    enumerations stay unexpanded, as they were.
    """
    for camp in _ADANCIME:
        if getattr(loc, camp):
            return replace(loc, **{camp: numar})
    return None


def _adancimea(loc: Locator) -> str | None:
    """Which unit an enumeration or range would extend — the innermost one named."""
    for camp in _ADANCIME:
        if getattr(loc, camp):
            return camp
    return None


def _sirul(de_la: str, pana_la: str) -> list[str] | None:
    """The values a range covers, ends included, or None when it cannot be read confidently.

    Refused rather than guessed when the ends are not the same kind, when the range descends, and
    when it is longer than `_MAX_INTERVAL` — a citation does not span thirty articles by dash, so
    a long run is a misread and expanding it would invent that many provisions.
    """
    if de_la.isdigit() and pana_la.isdigit():
        a, b = int(de_la), int(pana_la)
        if not 0 < b - a < _MAX_INTERVAL:
            return None
        return [str(n) for n in range(a, b + 1)]
    if len(de_la) == 1 and len(pana_la) == 1 and de_la.isascii() and pana_la.isascii():
        a, b = ord(de_la), ord(pana_la)
        if not 0 < b - a < _MAX_INTERVAL:
            return None
        return [chr(n) for n in range(a, b + 1)]
    return None


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
        # `m.lastgroup` names the last group that matched, which is not the same thing as the act
        # type: with optional trailing groups it can be `lege_an` rather than `lege`. The scan is
        # what actually answers the question, and it used to be preceded by a dead assignment of
        # the other, which read as though `lastgroup` were the fallback. It was never used.
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
    """Every internal position cited, with its span. Empty matches are discarded.

    **Driven off the keywords, not scanned character by character.** All four parts of
    `_LOCATOR` are optional, which is right — `alin. (2)` with no article is a locator — but it
    means the pattern also matches the *empty string*, at every position in the text. Searching
    with it therefore never skips: the engine cannot use the literal prefixes `art`, `alin`,
    `lit`, `pct` to jump ahead, so it evaluates a four-way IGNORECASE alternation once per
    character. Measured at 0.95 µs per character — an act of average length cost 35 ms, of which
    essentially all was this, and the graph over 152 079 acts cost 95 minutes.

    Anchoring is exact rather than approximate: a non-empty match must begin with one of those
    keywords, so the positions where one occurs are precisely the positions worth trying. The
    leading `\\s*,?\\s*` a match could otherwise absorb was being trimmed off the span anyway.
    """
    text = normalizeaza(text)
    gasite: list[tuple[Locator, int, int]] = []
    pozitie = 0
    for ancora in _ANCORA.finditer(text):
        if ancora.start() < pozitie:
            continue  # inside a locator already taken; `pozitie` is the end of the last one
        m = _LOCATOR.match(text, ancora.start())
        if m is None or m.end() == m.start():
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
            # `articolele 7 și 8`: keep reading numbers off the tail, each one a sibling of the
            # locator just matched. Collected first and accepted after, because whether this is an
            # enumeration at all is only known once the run ends — see `_COADA_NUMAR`.
            pozitie = m.end()
            continue
        pozitie = m.end()
    return gasite


# Where a locator can begin. Every non-empty `_LOCATOR` match starts with one of these four
# keyword families, so these positions are exactly the ones worth trying — and `\b` keeps `art`
# out of `parte` and `lit` out of `politica`.
_ANCORA: Final[re.Pattern[str]] = re.compile(r"\b(?:art|alin|lit|punct|pct)", re.IGNORECASE)


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


def extinde_serii(
    locuri: list[tuple[Locator, int, int]], text: str
) -> list[tuple[Locator, int, int]]:
    """Expand `lit. a)-c)` and `art. 7, 8 și 9` into one locator per member.

    Runs **after** `uneste`, and that ordering is the whole point. Romanian hangs the shallower
    unit off the deeper one in the genitive — `lit. a)-c) ale art. 7` — so the article is not known
    until the merge has happened. Expanding first gave `lita`, `litb`, `art7.litc`: only the member
    adjacent to `ale art. 7` picked up the article and the rest were orphaned, which is a worse
    answer than not expanding at all.

    Two shapes, both closed rather than open-ended:

    - a **range**, `a)-c)` or `7-9`, which names its ends and implies the middle. Refused when the
      ends are not the same kind, when it descends, or when it is longer than `_MAX_INTERVAL` — no
      citation spans thirty articles by dash, so a long run is a misread.
    - an **enumeration**, kept only as far as its last `și`/`sau`/`ori`. A comma alone does not
      make one: `art. 5, 30 de zile de la publicare` is a deadline, and reading the 30 as an
      article invents `art. 30`.
    """
    iesire: list[tuple[Locator, int, int]] = []
    for loc, start, end in locuri:
        iesire.append((loc, start, end))
        camp = _adancimea(loc)
        if camp is None:
            continue
        interval = _INTERVAL_LITERA if camp == "litera" else _INTERVAL_NUMAR
        coada = _COADA_LITERA if camp == "litera" else _COADA_NUMAR
        marca = "litera" if camp == "litera" else "numar"

        capat = end
        gama = interval.match(text, capat)
        if gama is not None:
            sir = _sirul(getattr(loc, camp), gama.group("pana"))
            if sir:
                for val in sir[1:]:
                    frate = _extinde(loc, val)
                    if frate is not None:
                        iesire.append((frate, gama.start("pana"), gama.end()))
                capat = gama.end()

        candidati: list[tuple[Locator, int, int, bool]] = []
        for _ in range(_MAX_ENUMERARE):
            pas = coada.match(text, capat)
            if pas is None:
                break
            frate = _extinde(loc, pas.group(marca))
            if frate is None:
                break
            # Span runs to the end of the tail match so a closing `)` is inside it: ending at the
            # marker would leave `) din Legea …` as the gap to the act, which `_LEGATURA` rejects.
            candidati.append(
                (frate, pas.start(marca), pas.end(), pas.group("sep").lower() in _CONJUNCTIE)
            )
            capat = pas.end()
        ultima = max((i for i, c in enumerate(candidati) if c[3]), default=-1)
        iesire.extend((f, a, b) for f, a, b, _ in candidati[: ultima + 1])
    return iesire


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

    for loc, start, end in extinde_serii(uneste(locatori(text), text), text):
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
