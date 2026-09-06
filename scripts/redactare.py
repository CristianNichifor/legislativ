"""Legistic drafting form: is the amendment phrased the way the law requires, and how should it be.

The other passes check a draft against the *corpus*; this checks it against the *rules for writing
it*. Romanian legislative drafting is not free prose — Legea nr. 24/2000 and the Consiliul
Legislativ's drafting guide fix the exact words an amendment must use: a text is changed with
`se modifică și va avea următorul cuprins`, repealed with `se abrogă`, a provision added with
`se introduce ... cu următorul cuprins`, several changes gathered under
`... se modifică și/sau completează, după cum urmează:` with arabic-numbered points. A drafter
who writes "articolul 7 se schimbă" has said what they mean and said it in a form the Council
will send back.

So this does two things, both grounded in the guide:

- **`conformitate`** reads a draft and flags intent expressed in the wrong form — a repeal written
  as "se elimină", a modification as "se rescrie", a modification that supplies new text without
  the mandatory "va avea următorul cuprins". Each flag names the correct formula, because the
  point is to fix the draft, not just mark it. This is where the tool meets a user rewriting in
  natural language: it turns "close" into "correct".

- **`redacteaza`** goes the other way, from a structured intent to the mandated text: give it the
  operation, the act and the article, and it returns the phrasing Legea 24/2000 requires, ready to
  paste. The template a form fills, so a plain request becomes a proper amendment.

The verbs here are the non-standard ones the extractors deliberately do *not* match — `amendamente`
recognises only correct legistic form, so a near-miss slips past it silently, and that silence is
exactly what this catches. Standard library only; the rules are read from the guide, not fetched
at runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.text import normalizeaza

# Non-standard ways drafters express each operation, mapped to the mandated verb. These are the
# forms the Council rejects — the extractors ignore them, so they would otherwise pass unseen.
NESTANDARD: dict[str, list[str]] = {
    "modifica": [
        r"se\s+schimb[ăa]",
        r"se\s+rescrie",
        r"se\s+reformuleaz[ăa]",
        r"se\s+modific[ăa]\s+astfel(?!\s*:)",
        r"devine\b",
    ],
    "abroga": [
        r"se\s+elimin[ăa]",
        r"se\s+anuleaz[ăa]",
        r"se\s+suprim[ăa]",
        r"se\s+[șs]terge",
        r"se\s+desfiin[țt]eaz[ăa]",
        r"(î|i)nceteaz[ăa]\s+aplicabilitatea",
    ],
    "completeaza": [r"se\s+adaug[ăa](?!\s+un)", r"se\s+suplimenteaz[ăa]"],
}
CORECT: dict[str, str] = {
    "modifica": "se modifică și va avea următorul cuprins:",
    "abroga": "se abrogă",
    "completeaza": "se completează",
    "introduce": "se introduce ... cu următorul cuprins:",
}
LEGEA_24 = "Legea nr. 24/2000 privind normele de tehnică legislativă"

# Normative-language rules the guide fixes but the verb map above does not touch: the register a
# provision is written in, not the operation it performs. These are the "correct intent, wrong
# words" errors a Council also sends back — future tense where the norm speaks in the present, an
# open-ended enumeration, an obligation stated as a wish, an ambiguous conjunction. Each carries
# its own message because none of them maps onto an operation in CORECT. Patterns run over
# `normalizeaza` (case and diacritics kept), so `ș` and mixed case match as written.
LIMBAJ: list[tuple[str, str]] = [
    (
        r"se\s+va\b",
        "«se va» pune verbul la viitor; textul normativ se scrie la timpul prezent — "
        f"«se» + verb la prezent ({LEGEA_24}).",
    ),
    (
        r"se\s+vor\b",
        "«se vor» pune verbul la viitor; textul normativ se scrie la timpul prezent — "
        f"«se» + verb la prezent ({LEGEA_24}).",
    ),
    (
        r"\btrebuie\s+s[ăa]\b",
        "«trebuie să» exprimă obligația indirect; norma o exprimă la prezent sau prin "
        f"«are obligația să» ({LEGEA_24}).",
    ),
    (
        r"\bși\s*/\s*sau\b",
        "«și/sau» este ambiguu; alege «și», «sau», ori enumeră explicit ambele variante "
        "(Consiliul Legislativ).",
    ),
    (
        r"\betc\.?",
        "«etc.» lasă enumerarea deschisă; în textul normativ enumerările sunt complete "
        f"({LEGEA_24}).",
    ),
    (
        r"\bș\.\s*a\.",
        "«ș.a.» lasă enumerarea deschisă; în textul normativ enumerările sunt complete "
        f"({LEGEA_24}).",
    ),
]

# A modification that gives new text must carry this; without it the amendment is incomplete.
_MODIFICA = re.compile(r"se\s+modific[ăa]", re.IGNORECASE)
_CUPRINS = re.compile(r"va\s+avea\s+urm[ăa]torul\s+cuprins", re.IGNORECASE)
_FRAZA = re.compile(r"(?<!\bart)(?<!\balin)(?<!\bnr)(?<!\blit)\.\s+")


@dataclass(frozen=True)
class Abatere:
    """One place a draft departs from mandated legistic form or normative language.

    Most departures are operation-form errors: intent in the wrong verb, keyed by `operatie` into
    `CORECT` for the fix. A normative-language finding (`operatie == "limbaj"`) is not about an
    operation, so it carries its own `mesaj` and the property returns that verbatim.
    """

    fragment: str
    gasit: str
    operatie: str
    mesaj: str | None = None  # set for `limbaj` findings, which do not map onto a CORECT form

    @property
    def explicatie(self) -> str:
        if self.mesaj is not None:
            return self.mesaj
        return (
            f"«{self.gasit}» nu este forma legistică pentru {self.operatie}; "
            f"folosește «{CORECT[self.operatie]}» ({LEGEA_24})."
        )

    @property
    def increderea(self) -> str:
        return "derived"  # a form judgement, not a quotation


def limbaj_normativ(draft: str) -> list[Abatere]:
    """Where a draft is written in the wrong register — future tense, an open enumeration, an
    obligation stated as a wish, an ambiguous conjunction. Each finding carries its own message and
    cites the rule; `operatie` is `"limbaj"` so it reads apart from an operation-form error.
    """
    text = normalizeaza(draft)
    gasite: list[Abatere] = []
    vazute: set[tuple[int, str]] = set()
    for sablon, mesaj in LIMBAJ:
        for m in re.finditer(sablon, text, re.IGNORECASE):
            cheie = (m.start(), sablon)
            if cheie in vazute:
                continue
            vazute.add(cheie)
            inceput = max(0, m.start() - 40)
            gasite.append(
                Abatere(text[inceput : m.end() + 20].strip(), m.group(0).strip(), "limbaj", mesaj)
            )
    return gasite


def conformitate(draft: str) -> list[Abatere]:
    """Where a draft says the right thing the wrong way. Empty means the form is clean.

    Three checks: intent in a non-standard verb (a repeal as "se elimină"); a modification that
    supplies text without the mandatory "va avea următorul cuprins"; and normative-language
    departures (`limbaj_normativ` — future tense, "etc.", "trebuie să", "și/sau"). Each cites its
    rule and, where there is one, the correct form.
    """
    text = normalizeaza(draft)
    abateri: list[Abatere] = []
    vazute: set[tuple[int, str]] = set()

    for operatie, sabloane in NESTANDARD.items():
        for sablon in sabloane:
            for m in re.finditer(sablon, text, re.IGNORECASE):
                cheie = (m.start(), operatie)
                if cheie in vazute:
                    continue
                vazute.add(cheie)
                inceput = max(0, m.start() - 40)
                abateri.append(
                    Abatere(text[inceput : m.end() + 20].strip(), m.group(0).strip(), operatie)
                )

    abateri += limbaj_normativ(draft)

    # `se modifică` that provides new text but omits `va avea următorul cuprins`. Checked per
    # sentence: a bare "se modifică" pointing forward to a quoted block, with no cuprins clause.
    for fraza in _FRAZA.split(text):
        if (
            _MODIFICA.search(fraza)
            and not _CUPRINS.search(fraza)
            and ("«" in fraza or '"' in fraza or "următor" in fraza.lower())
        ):
            m = _MODIFICA.search(fraza)
            abateri.append(
                Abatere(
                    fraza.strip()[:90], "se modifică (fără „va avea următorul cuprins”)", "modifica"
                )
            )

    return sorted(abateri, key=lambda a: draft.find(a.fragment[:20]) if a.fragment else 0)


def redacteaza(
    operatie: str,
    act: str,
    *,
    articol: str | None = None,
    alineat: str | None = None,
    litera: str | None = None,
    text_nou: str = "…",
    articol_nou: str | None = None,
) -> str:
    """From a structured intent to the mandated legistic phrasing, ready to paste.

    The inverse of the check: a form gives the operation and the target, this returns the words
    Legea 24/2000 requires. `act` is the act as it must be cited, with its identification elements
    ("Legea nr. 98/2016 privind achizițiile publice, cu modificările și completările ulterioare").
    """
    # The guide's form leads with the article and cites the act after it, then names the deeper
    # unit last: "La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică…". With only an
    # article, the act follows it directly and there is no leading "La".
    subunitate = _subunitate(alineat, litera)
    if articol and subunitate:
        tinta = f"La articolul {articol} din {act}, {subunitate}"
    elif articol:
        tinta = f"Articolul {articol} din {act}"
    elif subunitate:
        tinta = f"{subunitate[0].upper()}{subunitate[1:]} din {act}"
    else:
        tinta = act

    if operatie == "modifica":
        return f"{tinta} se modifică și va avea următorul cuprins:\n«{text_nou}»"
    if operatie == "abroga":
        return f"{tinta} se abrogă."
    if operatie == "completeaza":
        return f"{tinta} se completează cu următorul cuprins:\n«{text_nou}»"
    if operatie == "introduce":
        dupa = f"articolul {articol}" if articol else "articolul …"
        return (
            f"După {dupa} din {act} se introduce un nou articol, "
            f"{articol_nou or 'art. …'}, cu următorul cuprins:\n«{text_nou}»"
        )
    raise ValueError(f"operație necunoscută: {operatie}")


def titlu_modificator(operatie: str, act: str, *, articol: str | None = None) -> str:
    """The title an amending act must carry when it touches a single element (guide §2.2.1)."""
    verb = {"modifica": "modificarea", "completeaza": "completarea", "abroga": "abrogarea"}.get(
        operatie, "modificarea"
    )
    unde = f"art. {articol} din " if articol else ""
    return f"Lege pentru {verb} {unde}{act}"


def _subunitate(alineat: str | None, litera: str | None) -> str:
    """The sub-article part, deepest last, as the guide names it: 'alineatul (2), litera a)'."""
    parti = []
    if alineat:
        parti.append(f"alineatul ({alineat})")
    if litera:
        parti.append(f"litera {litera})")
    return ", ".join(parti)
