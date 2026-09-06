"""The terms a law defines for itself, and drafts that talk around them.

Romanian legislative drafting norms require an act to define its own vocabulary, and acts
generally comply, in a shape regular enough to parse:

    Art. 3. - În sensul prezentei legi, termenii și expresiile de mai jos au următoarele
    semnificații:
    a) achiziție publică - achiziția de lucrări, de produse sau de servicii ...;
    b) autoritate contractantă - entitățile prevăzute la art. 4 ...;

That makes the terminology check the cheapest genuinely useful thing the linter does, and the
only one of the three headline outputs that is close to exact. A term either matches a
definition in force or it does not.

**The warning worth issuing is not "undefined word".** It is: *this draft says «achiziții de
stat», the law it amends defines «achiziție publică», and those are not the same term.* A
near-synonym of a defined term is how a bill accidentally creates a second, parallel legal
category — the drafting error that produces litigation years later, and one a model is not
needed to catch. An exact use of a defined term is correct usage and is silent.

**The similarity test is a heuristic and is labelled as one.** Matching is on a diacritic- and
case-folded form, over word windows the length of the defined term, using a sequence ratio.
That catches `achiziții de stat` against `achiziție publică` weakly and `autoritate
contractanta` against `autoritate contractantă` strongly, and it will occasionally flag an
innocent phrase. The threshold is a parameter rather than a constant for that reason, and every
warning carries the score it was raised at so a reader can discount it. This is the one output
in the package where a false positive is cheap: it costs a drafter ten seconds.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from scripts.referinte import Act, Locator
from scripts.text import cheie, normalizeaza, radacini

# The chapeau wraps. `... au următoarele\nsemnificații:` is one sentence with a line break in
# the middle of it, which is how every source that wraps at a column width delivers it, and a
# pattern that forbade newlines here found no definition article in any real document.
_CHAPEAU_DEF = re.compile(
    r"(?:în|in)\s+(?:sensul|(?:î|i)n(?:ț|t)elesul)\s+prezent(?:ei|ului)\s+"
    r"(?:legi|ordonan(?:ț|t)e|hot(?:ă|a)r(?:â|a)ri|cod)[^:]{0,160}:",
    re.IGNORECASE,
)
# `a) achiziție publică - definiția;` and the `înseamnă` / `reprezintă` variants. The definition
# runs to its semicolon or to the next lettered entry, not to the end of the line: definitions
# wrap too, and stopping at the first newline truncates most of them.
_INTRARE = re.compile(
    r"^\s*(?P<litera>[a-zș][\^\d]*)\)\s*(?P<termen>[^\n\-–—]{2,80}?)\s*"
    r"(?:-|–|—|înseamn(?:ă|a)|reprezint(?:ă|a)|este)\s+"
    r"(?P<definitie>.+?)(?=;|\n\s*[a-zș][\^\d]*\)|\Z)",
    re.MULTILINE | re.DOTALL,
)
_INLINE = re.compile(
    r"prin\s+(?P<termen>[^,;.\n]{2,60}?)\s+se\s+(?:în|in)(?:ț|t)elege\s+(?P<definitie>[^;.\n]{5,300})",
    re.IGNORECASE,
)
_CUVANT = re.compile(r"[\w\^]+", re.UNICODE)


@dataclass(frozen=True)
class Termen:
    """A term as one act defines it, with where to check the definition."""

    termen: str
    definitie: str
    act: Act | None = None
    locator: Locator = Locator()

    @property
    def cheia(self) -> str:
        return cheie(self.termen)

    @property
    def radacina(self) -> str:
        """What the term is actually matched on, so that its own plural is not a deviation."""
        return radacini(self.termen)


@dataclass(frozen=True)
class Avertisment:
    """A phrase in a draft that resembles a defined term without being it."""

    fragment: str
    termen: Termen
    scor: float
    regula: str
    start: int
    end: int

    @property
    def increderea(self) -> str:
        """Never verbatim: the match is a similarity score, not a quotation."""
        return "derived"

    @property
    def explicatie(self) -> str:
        if self.regula == "categorie-paralela":
            return (
                f"«{self.fragment}» pornește de la același cuvânt ca termenul definit "
                f"«{self.termen.termen}», dar nu este el. Două categorii juridice paralele."
            )
        return (
            f"«{self.fragment}» diferă de termenul definit «{self.termen.termen}» "
            f"(asemănare {self.scor:.2f})."
        )


def definitii(text: str, act: Act | None = None, locator: Locator | None = None) -> list[Termen]:
    """Every term the passage defines, from both the enumerated and the inline form."""
    text = normalizeaza(text)
    gasite: list[Termen] = []
    vazute: set[str] = set()

    for chapeau in _CHAPEAU_DEF.finditer(text):
        # The enumeration runs to the end of the passage or to the next definition chapeau.
        urmator = _CHAPEAU_DEF.search(text, chapeau.end())
        corp = text[chapeau.end() : urmator.start() if urmator else len(text)]
        for intrare in _INTRARE.finditer(corp):
            termen = intrare.group("termen").strip(" .,")
            if not termen or cheie(termen) in vazute:
                continue
            vazute.add(cheie(termen))
            gasite.append(
                Termen(
                    termen=termen,
                    definitie=" ".join(intrare.group("definitie").split())[:400],
                    act=act,
                    locator=locator or Locator(litera=intrare.group("litera")),
                )
            )

    for m in _INLINE.finditer(text):
        termen = m.group("termen").strip(" \"'.,")
        if cheie(termen) in vazute:
            continue
        vazute.add(cheie(termen))
        gasite.append(
            Termen(
                termen=termen,
                definitie=" ".join(m.group("definitie").split()),
                act=act,
                locator=locator or Locator(),
            )
        )
    return gasite


def _ferestre(text: str, cuvinte: int) -> list[tuple[str, int, int]]:
    jetoane = [(m.group(0), m.start(), m.end()) for m in _CUVANT.finditer(text)]
    ferestre: list[tuple[str, int, int]] = []
    for i in range(len(jetoane) - cuvinte + 1):
        start, sfarsit = jetoane[i][1], jetoane[i + cuvinte - 1][2]
        ferestre.append((text[start:sfarsit], start, sfarsit))
    return ferestre


def _acoperit(spanuri: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(not (end <= s or start >= e) for s, e in spanuri)


def _spanuri_exacte(proiect: str, termeni: list[Termen]) -> list[tuple[int, int]]:
    """Where the draft uses a defined term, in any of its inflected forms. Nothing inside is a
    warning.

    The first version of this compared surface strings, and so flagged `o autoritate
    contractantă` and `autorități contractante` — an article and a plural — while missing
    `achiziții de stat`, which is the error the check exists for. Masking correct usage first,
    on stems, is what turns the output from noise into a finding.
    """
    spanuri: list[tuple[int, int]] = []
    radacini_termeni = {t.radacina for t in termeni}
    for termen in termeni:
        n = len(termen.radacina.split())
        for fragment, start, end in _ferestre(proiect, n):
            if radacini(fragment) in radacini_termeni:
                spanuri.append((start, end))
    return spanuri


@dataclass(frozen=True)
class Ocurenta:
    """Where a draft uses a defined term — the positive `jargon` masks before it warns."""

    fragment: str  # the surface form in the draft, e.g. "autorității contractante"
    termen: Termen  # the definition it is a use of
    start: int
    end: int


def recunoaste(proiect: str, termeni: list[Termen]) -> list[Ocurenta]:
    """Every place the draft uses a defined term, in any inflection — so the editor can chip it.

    The inverse of `jargon`: that flags phrases that *miss* a defined term, this surfaces the ones
    that *hit* it, each with the definition to show on hover. Matching is on stems (via `radacini`),
    so a plural or an article-suffixed form counts as the term, not as a deviation — the same reason
    `_spanuri_exacte` masks these before the warning pass. One occurrence per term (the first), in
    reading order; duplicate definitions of the same term collapse to the first seen.
    """
    proiect = normalizeaza(proiect)
    dupa_radacina: dict[str, Termen] = {}
    for t in termeni:
        if t.radacina:
            dupa_radacina.setdefault(t.radacina, t)

    gasite: dict[str, Ocurenta] = {}
    for n in {len(r.split()) for r in dupa_radacina}:
        if n < 1:
            continue
        for fragment, start, end in _ferestre(proiect, n):
            r = radacini(fragment)
            termen = dupa_radacina.get(r)
            if termen is not None and r not in gasite:
                gasite[r] = Ocurenta(fragment=fragment, termen=termen, start=start, end=end)

    # A one-word term nested in a multi-word one ("funcționar" inside "funcționar public") is noise:
    # keep the longest match over any span and drop occurrences it fully contains.
    ocurente = sorted(gasite.values(), key=lambda o: (o.start - o.end, o.start))
    pastrate: list[Ocurenta] = []
    for o in ocurente:
        if not any(p.start <= o.start and o.end <= p.end for p in pastrate):
            pastrate.append(o)
    return sorted(pastrate, key=lambda o: o.start)


def jargon(
    proiect: str,
    termeni: list[Termen],
    prag: float = 0.82,
    prag_cap: float = 0.85,
) -> list[Avertisment]:
    """Phrases in the draft that miss a defined term, under two named rules.

    Both rules compare stems, not surface forms, because Romanian inflection is not a drafting
    error. `varianta` is what survives that: a phrase whose stems are close to the defined term's
    without being them — `autoritate contractuală` against `autoritate contractantă`.
    `categorie-paralela` is the more consequential one — the draft opens with the defined term's
    own head word and then qualifies it differently, which is how a bill quietly creates a second
    legal category alongside the one the law already defines.

    Correct uses, in any inflection, are masked before either rule runs.
    """
    proiect = normalizeaza(proiect)
    radacini_termeni = {t.radacina for t in termeni}
    mascate = _spanuri_exacte(proiect, termeni)
    candidati: dict[tuple[int, int], Avertisment] = {}

    def propune(av: Avertisment) -> None:
        pozitie = (av.start, av.end)
        anterior = candidati.get(pozitie)
        if anterior is None or (av.regula, av.scor) > (anterior.regula, anterior.scor):
            candidati[pozitie] = av

    for termen in termeni:
        cuvinte_termen = termen.radacina.split()
        n = len(cuvinte_termen)
        for latime in {max(1, n - 1), n, n + 1}:
            for fragment, start, end in _ferestre(proiect, latime):
                radacina_fragment = radacini(fragment)
                if radacina_fragment in radacini_termeni or _acoperit(mascate, start, end):
                    continue
                scor = difflib.SequenceMatcher(None, radacina_fragment, termen.radacina).ratio()
                if prag <= scor < 1.0:
                    propune(Avertisment(fragment, termen, round(scor, 3), "varianta", start, end))
                    continue
                # A single-word definition has no qualifier to diverge in, so the parallel
                # category rule would fire on every noun that shares its stem.
                if n < 2 or latime < 2:
                    continue
                cap = difflib.SequenceMatcher(
                    None, radacina_fragment.split()[0], cuvinte_termen[0]
                ).ratio()
                if cap >= prag_cap and scor < prag:
                    propune(
                        Avertisment(
                            fragment, termen, round(cap, 3), "categorie-paralela", start, end
                        )
                    )

    # Wider first at equal score: `achiziții de stat` is the finding, `achiziții de` is the same
    # finding with the qualifier cut off, and the qualifier is the point.
    ordonate = sorted(candidati.values(), key=lambda a: (-a.scor, -(a.end - a.start), a.start))
    pastrate: list[Avertisment] = []
    for a in ordonate:
        if any(not (a.end <= p.start or a.start >= p.end) for p in pastrate):
            continue
        pastrate.append(a)
    return sorted(pastrate, key=lambda a: a.start)
