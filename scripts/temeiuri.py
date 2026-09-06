"""On what constitutional ground a provision was struck.

The register says *that* a provision was struck; `prevedere.py` says *what* was struck. This says
**why** — which article of the Constitution the Court found violated — and it is the thing a
drafter actually needs, because it is the only one of the three that transfers. Knowing that art.
224 of the old Penal Code fell is a fact about that article; knowing it fell on equality grounds
tells you something about the rule you are writing now.

Deterministic, offline, no model: the Court states its grounds in the *considerente*, in a fixed
formula — `contravine dispozițiilor art. 16 din Constituție`.

**Two strengths, and conflating them would be the whole error.** A decision discusses the grounds
it *rejects* as fully as the ones it accepts, so a bare mention proves nothing:

    invoked   median 3 articles per decision, p90 8   — argued about, outcome unknown
    violated  median 1,                        p90 3  — the Court used a verb of violation

`fel` carries the difference. 320 of the 443 striking decisions yield at least one `încălcat`; the
other 123 state their reasoning without a verb this can key on, and come back `invocat` — which is
honest, and weaker, and says so.

**The Court's own articles are not grounds.** Article 147 appears in 17 221 of 20 006 decisions
because it is the article that makes its rulings binding — recited in every decision, a ground in
none. Articles 142–147 (and 144–145 before the revision) are the Court's competence and the effect
of its judgments; they are excluded, or the top ground in Romanian constitutional law would appear
to be "the Constitutional Court exists".

**The Constitution was renumbered in 2003, and the names have to follow.** The revision of 29
October 2003 moved property from article 41 to 44, restriction of rights from 49 to 53, the courts
from 125 to 126. A decision from 1998 citing `art. 41` is about property; one from 2018 citing the
same number is about labour. Naming them from one table would mislabel two decades of case law —
the same mistake `prevedere.py` avoids by resolving a code to the version in force when it was
struck, and avoided here the same way, by the decision's date.

Where a number is not in either table it stays unnamed rather than guessed. A wrong ground is worse
than a bare article number, because a bare number sends a reader to the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

# Legea de revizuire nr. 429/2003, approved by referendum and in force from 29 October 2003.
REVIZUIRE: Final[date] = date(2003, 10, 29)

# The Court's competence and the effect of its decisions. Recited everywhere, a ground nowhere.
PROCEDURALE: Final[frozenset[str]] = frozenset({"140", "142", "143", "144", "145", "146", "147"})

# Only articles whose subject is well known and stable enough to name. Everything else keeps its
# number: a reader can look up a number, and cannot un-read a wrong label.
TITLURI_DUPA_2003: Final[dict[str, str]] = {
    "1": "statul de drept, claritatea și previzibilitatea legii",
    "11": "dreptul internațional și dreptul intern",
    "15": "universalitatea; neretroactivitatea legii",
    "16": "egalitatea în drepturi",
    "20": "tratatele internaționale privind drepturile omului",
    "21": "accesul liber la justiție",
    "23": "libertatea individuală",
    "24": "dreptul la apărare",
    "41": "munca și protecția socială a muncii",
    "44": "dreptul de proprietate privată",
    "45": "libertatea economică",
    "47": "nivelul de trai",
    "53": "restrângerea exercițiului unor drepturi sau libertăți",
    "61": "rolul și structura Parlamentului",
    "73": "categorii de legi",
    "115": "delegarea legislativă",
    "124": "înfăptuirea justiției",
    "126": "instanțele judecătorești",
    "129": "folosirea căilor de atac",
    "148": "integrarea în Uniunea Europeană",
}

# The 1991 numbering, for decisions predating the revision.
TITLURI_PANA_2003: Final[dict[str, str]] = {
    "1": "statul de drept",
    "11": "dreptul internațional și dreptul intern",
    "15": "universalitatea; neretroactivitatea legii",
    "16": "egalitatea în drepturi",
    "20": "tratatele internaționale privind drepturile omului",
    "21": "accesul liber la justiție",
    "23": "libertatea individuală",
    "24": "dreptul la apărare",
    "38": "dreptul la muncă",
    "41": "protecția proprietății private",
    "43": "nivelul de trai",
    "49": "restrângerea exercițiului unor drepturi sau libertăți",
    "58": "rolul Parlamentului",
    "72": "categorii de legi",
    "114": "delegarea legislativă",
    "123": "înfăptuirea justiției",
    "125": "instanțele judecătorești",
    "128": "folosirea căilor de atac",
}

_ART = (
    r"art(?:icolul|\.)\s*(\d+)(?:\s*alin\.?\s*\(?(\d+)\)?)?"
    r"[^.;]{0,80}?\bdin\s+(?:Constitu[țt]i[ae]|Legea\s+fundamental[ăa])"
)

# Any reference to a constitutional article in the reasoning.
_INVOCAT: Final[re.Pattern[str]] = re.compile(_ART, re.IGNORECASE)

# The same, preceded by a verb the Court uses when it accepts a ground. The window is short
# because "încalcă" three clauses earlier is about a different article.
_INCALCAT: Final[re.Pattern[str]] = re.compile(
    r"(?:încalc[ăa]|contravin[e]?|nesocote[șs]te|sunt contrare|este contrar[ăa]?|"
    r"aduce atingere|contrar dispozi[țt]iilor)[^.;]{0,120}?" + _ART,
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Temei:
    """One constitutional article the decision's reasoning turns on.

    One row per *article*, not per mention. A decision names `art. 21`, then `art. 21 alin. (1)`,
    then `art. 21` again; 212 of the 443 striking decisions repeat an article that way, and three
    rows for one ground is noise on a card that has room for a sentence. The paragraphs are kept
    together in `alineate`, because which paragraph the Court meant is information — it is just not
    a separate ground.
    """

    articol: str
    alineate: tuple[str, ...]
    fel: str  # incalcat | invocat
    nume: str  # '' where the number is not one this module will name
    text: str  # the span it was read from, so a finding can quote it

    @property
    def increderea(self) -> str:
        """`încălcat` is quoted from a verb of violation next to the article; `invocat` is only
        that the article appears in reasoning that may well have rejected it."""
        return "verbatim" if self.fel == "incalcat" else "derived"

    @property
    def eticheta(self) -> str:
        loc = f"art. {self.articol}"
        if self.alineate:
            loc += " alin. " + ", ".join(f"({a})" for a in self.alineate)
        return f"{loc} — {self.nume}" if self.nume else loc


def considerente(text: str) -> str:
    """The reasoning, which is everything before the operative part.

    95% of a decision by length: the dispositive is a paragraph, the considerente are the case.
    A decision whose dispositive cannot be located is returned whole rather than truncated at a
    guess — reading the operative part as reasoning costs a little noise, and cutting the reasoning
    at the wrong place costs the grounds.
    """
    from scripts.decizii import dispozitiv

    disp = dispozitiv(text)
    if not disp:
        return text
    taiat = text.rfind(disp)
    return text[:taiat] if taiat > 0 else text


def titluri(la_data: date | None) -> dict[str, str]:
    """The naming table in force when the decision was given."""
    if la_data is not None and la_data < REVIZUIRE:
        return TITLURI_PANA_2003
    return TITLURI_DUPA_2003


def temeiuri(text: str, la_data: date | None = None) -> list[Temei]:
    """The constitutional grounds in a decision's reasoning, violations first.

    `la_data` is the decision's publication date and decides which numbering the articles are read
    under. Passing `None` assumes the current Constitution, which is right for anything recent and
    wrong for the 1990s — so callers that have the date should give it.
    """
    cons = considerente(text)
    tabel = titluri(la_data)

    def aduna(rx: re.Pattern[str]) -> dict[str, tuple[set[str], str]]:
        gasite: dict[str, tuple[set[str], str]] = {}
        for m in rx.finditer(cons):
            articol, alineat = m.group(1), m.group(2)
            if articol in PROCEDURALE:
                continue
            alineate, citat = gasite.setdefault(articol, (set(), m.group(0).strip()[:300]))
            if alineat:
                alineate.add(alineat)
        return gasite

    incalcate = aduna(_INCALCAT)
    # An article the Court found violated is not also reported as merely invoked — the stronger
    # reading of the same ground supersedes the weaker one rather than sitting beside it.
    invocate = {a: v for a, v in aduna(_INVOCAT).items() if a not in incalcate}

    def fa(sursa: dict[str, tuple[set[str], str]], fel: str) -> list[Temei]:
        return [
            Temei(
                articol=a,
                alineate=tuple(sorted(alin, key=lambda x: int(x))),
                fel=fel,
                nume=tabel.get(a, ""),
                text=citat,
            )
            for a, (alin, citat) in sursa.items()
        ]

    lista = [*fa(incalcate, "incalcat"), *fa(invocate, "invocat")]
    return sorted(lista, key=lambda t: (0 if t.fel == "incalcat" else 1, int(t.articol)))


def rezumat(lista: list[Temei]) -> str:
    """One line naming the grounds, for a card that has room for a sentence and not a table."""
    incalcate = [t for t in lista if t.fel == "incalcat"]
    if incalcate:
        return "încalcă " + ", ".join(t.eticheta for t in incalcate[:3])
    if lista:
        return "invocate în considerente: " + ", ".join(t.eticheta for t in lista[:3])
    return ""
