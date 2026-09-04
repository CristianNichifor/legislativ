"""What an act *does* to another act: the edges of the graph.

A reference says two acts are related. An amendment says how, and the how is the whole
product — `REFERENCES` between two laws is almost information-free, while `ABROGATES` with a
date decides whether a provision an MP is about to contradict is even in force.

**The target of an amendment is usually not in the sentence that amends it.** Romanian amending
acts are written as a chapeau followed by numbered points:

    Legea nr. 98/2016 privind achizițiile publice ... se modifică și se completează după cum
    urmează:
    1. La articolul 7, alineatul (2) se modifică și va avea următorul cuprins:
    2. Articolul 15 se abrogă.

Point 2 abrogates article 15 *of Legea 98/2016*, and says so nowhere. Read point by point,
every amendment in a real Romanian amending act comes out with no target act — which is not a
low recall figure, it is a graph with no edges at all. So the chapeau is parsed first and its
act is carried down until another chapeau replaces it. Whether a target was read from the
sentence or inherited from a chapeau travels with the amendment as `mostenit`, because the two
are not equally certain and the repository's rule is that a derived value says it is derived.

**`se abrogă` has two grammatical subjects and they point opposite ways.** `Articolul 15 se
abrogă` abrogates something inside the act being read; `La data intrării în vigoare a prezentei
legi se abrogă Legea nr. 50/1991` abrogates a different act entirely. The first is an edge to
one of the host act's own articles, the second is an edge to another act's root. Getting these
backwards inverts the direction of the most consequential edge in the graph, so the position of
the reference relative to the verb decides, and both forms are in the gold set.

**What this module does not do is decide what the amended text now says.** Applying an
amendment — taking `va avea următorul cuprins:` and substituting the quoted block — is
consolidation, and consolidation is a separate problem with its own failure modes. This module
records that article 7(2) changed on a date and by which act. That is enough to warn an MP that
they are citing a provision which has moved, which is the job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from scripts.referinte import Act, Locator, acte, locatori, referinte, uneste
from scripts.text import normalizeaza

# Ordered by specificity: `se modifică și se completează` must not be read as a bare
# `se completează`, and `se abrogă` inside `nu se abrogă` is not an abrogation.
VERBE: Final[list[tuple[str, str]]] = [
    ("introduce", r"se\s+introduc(?:e|)\b"),
    ("abroga", r"se\s+abrog(?:ă|a)\b"),
    ("modifica", r"se\s+modific(?:ă|a)\b"),
    ("completeaza", r"se\s+completeaz(?:ă|a)\b"),
    ("proroga", r"se\s+prorog(?:ă|a)\b"),
    ("suspenda", r"se\s+suspend(?:ă|a)\b"),
    # `se înlocuiește` / `se înlocuiesc`. The first version of this pattern spelled the
    # third-person singular as `înlocuiesc?`, which matches `înlocuiesc` and `înlocuies` and not
    # the form the singular actually takes — so every global substitution of a phrase, which
    # silently rewrites dozens of articles at once, went unrecorded.
    ("inlocuieste", r"se\s+(?:î|i)nlocuie(?:ș|s)(?:te|c)\b"),
]
_VERBE = re.compile("|".join(rf"(?P<{fel}>{s})" for fel, s in VERBE), re.IGNORECASE)
_NEGAT = re.compile(r"\bnu\s+$", re.IGNORECASE)

_DEROGARE = re.compile(r"prin\s+derogare\s+de\s+la\b", re.IGNORECASE)

_CHAPEAU = re.compile(
    r"(?P<act>(?:Leg(?:ea|ii)|Ordonanț|O\.?\s?U\.?\s?G|O\.?\s?G|Hot(?:ă|a)r|H\.?\s?G|Ordin|Codul)"
    r"[^\n:]{0,240}?\d{1,5}\s*/\s*(?:19|20)\d{2}[^\n:]{0,240}?)"
    r"\s+se\s+(?:modific(?:ă|a)|completeaz(?:ă|a)|abrog(?:ă|a))"
    r"(?:\s+(?:și|si)\s+se\s+(?:completeaz(?:ă|a)|modific(?:ă|a)))?"
    r"\s*,?\s*(?:după\s+cum\s+urmează|dup(?:ă|a)\s+cum\s+urmeaz(?:ă|a)|astfel)\s*:",
    re.IGNORECASE,
)

# A numbered point, at the start of a line: `12. La articolul 7, ...`
_PUNCT_NUMEROTAT = re.compile(r"^\s{0,4}\d{1,3}\.\s+", re.MULTILINE)
# Sentence end, guarding the abbreviations that legally must end in a full stop.
_SFARSIT_FRAZA = re.compile(
    r"(?<!\bart)(?<!\balin)(?<!\blit)(?<!\bpct)(?<!\bnr)(?<!\blett)\.\s+(?=[A-ZĂÂÎȘȚ])"
)


@dataclass(frozen=True)
class Amendament:
    """One operation of one act upon a provision, with the span it was read from."""

    fel: str
    act_tinta: Act | None
    locator: Locator
    text: str
    start: int
    end: int
    mostenit: bool = False
    locator_nou: Locator | None = None
    articole_noi: tuple[str, ...] = field(default=())

    @property
    def increderea(self) -> str:
        """The repository's provenance vocabulary. A target read from the sentence is verbatim;
        one carried down from a chapeau is derived, and says so wherever it is shown."""
        return "derived" if self.mostenit else "verbatim"


def unitati(text: str) -> list[tuple[str, int]]:
    """The passage split into the units an amendment lives in, with each unit's offset.

    Numbered points win over sentences: a point can contain several sentences, including the
    quoted new text of the provision, and splitting inside it would attach the amending verb to
    one half and the target to the other.
    """
    text = normalizeaza(text)
    taieturi = [0, *(m.start() for m in _PUNCT_NUMEROTAT.finditer(text)), len(text)]
    taieturi = sorted(set(taieturi))
    brute: list[tuple[str, int]] = []
    for inceput, sfarsit in zip(taieturi, taieturi[1:], strict=False):
        bucata = text[inceput:sfarsit]
        if not bucata.strip():
            continue
        if _PUNCT_NUMEROTAT.match(bucata):
            brute.append((bucata, inceput))
            continue
        pozitie = inceput
        for fraza in _SFARSIT_FRAZA.split(bucata):
            if fraza.strip():
                gasit = text.find(fraza, pozitie)
                brute.append((fraza, gasit if gasit >= 0 else pozitie))
            pozitie += len(fraza)
    return brute


def _fel(unitate: str) -> tuple[str, int] | None:
    if _DEROGARE.search(unitate):
        return "deroga", _DEROGARE.search(unitate).start()
    for m in _VERBE.finditer(unitate):
        if _NEGAT.search(unitate[max(0, m.start() - 6) : m.start()]):
            continue
        fel = next(f for f, _ in VERBE if m.group(f) is not None)
        return fel, m.start()
    return None


def amendamente(text: str, act_gazda: Act | None = None) -> list[Amendament]:
    """Every operation the passage performs, with its target resolved as far as the text allows.

    `act_gazda` is the act being read. It is the fallback target for an internal reference that
    no chapeau covers — `Articolul 15 se abrogă` in an act's own final provisions abrogates its
    own article 15 — and it is the caller's knowledge, not the text's, which is why it is a
    parameter rather than something this module tries to infer.
    """
    text = normalizeaza(text)
    chapeaux = [(m.start(), acte(m.group("act"))) for m in _CHAPEAU.finditer(text)]
    gasite: list[Amendament] = []

    for unitate, offset in unitati(text):
        felul = _fel(unitate)
        if felul is None:
            continue
        fel, poz_verb = felul

        tinta_chapeau: Act | None = None
        for start, refs in chapeaux:
            if start < offset + poz_verb and refs:
                tinta_chapeau = refs[0].act
        # A chapeau does not reach into its own sentence: the act it names is the one being
        # amended, not a target the point below inherits.
        in_chapeau = any(
            start <= offset + poz_verb < start + 400
            and _CHAPEAU.match(text, start)
            and offset + poz_verb < _CHAPEAU.match(text, start).end()
            for start, _ in chapeaux
        )
        if in_chapeau:
            continue

        acte_unitate = acte(unitate)
        dupa_verb = [r for r in acte_unitate if r.start >= poz_verb]
        primul = acte_unitate[0].act if acte_unitate else None
        explicit = dupa_verb[0].act if dupa_verb else primul

        locuri = uneste(locatori(unitate), unitate)
        inainte = [lc for lc in locuri if lc[2] <= poz_verb]
        dupa = [lc for lc in locuri if lc[1] >= poz_verb]

        # `se abrogă Legea nr. 50/1991` names its target after the verb and it is a whole act.
        # `prin derogare de la art. 5 din Legea nr. 98/2016` also names it after the verb, but
        # with a locator bound to it — and dropping that locator turns a derogation from one
        # article into a derogation from an entire law.
        tinteste_alt_act = bool(dupa_verb) and not inainte
        if tinteste_alt_act:
            legata = next(
                (
                    r.locator
                    for r in referinte(unitate)
                    if r.act is not None and r.act == explicit and r.locator
                ),
                Locator(),
            )
            tinta, mostenit, locator = explicit, False, legata
        else:
            tinta = explicit if (explicit and acte_unitate[0].start < poz_verb) else tinta_chapeau
            mostenit = tinta is not None and tinta is tinta_chapeau
            if tinta is None:
                tinta, mostenit = act_gazda, act_gazda is not None
            locator = inainte[0][0] if inainte else (dupa[0][0] if dupa else Locator())

        noi = tuple(lc[0].articol for lc in dupa if lc[0].articol) if fel == "introduce" else ()
        gasite.append(
            Amendament(
                fel=fel,
                act_tinta=tinta,
                locator=locator,
                text=unitate.strip(),
                start=offset,
                end=offset + len(unitate),
                mostenit=mostenit,
                locator_nou=dupa[0][0] if fel == "introduce" and dupa else None,
                articole_noi=noi,
            )
        )
    return gasite
