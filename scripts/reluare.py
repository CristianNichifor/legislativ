"""A draft that re-enacts wording the Court has already struck.

`coliziune.py` answers the citation question: does the draft *touch* a provision that was struck
and never repaired. This answers the wording question, which article 147 (4) is what makes worth
asking — a decision of the Court binds *erga omnes*, so it reaches a norm identical in substance
however it is renumbered, relocated or re-titled. A draft can therefore re-enact a struck rule
while citing nothing at all, and the citation check will say nothing.

**Deterministic, offline, no model.** Character 5-gram shingles over normalised text, compared
provision to provision. Romanian re-enactment is near-verbatim — a rule is re-passed in the words
it was written in — so the overlap is visible without embeddings, and, unlike a similarity score
from a model, every finding can point at the characters it matched.

**The metric took two corrections, both from measurement.** Containment alone (`how much of the
struck norm appears here`) called every whole-document row a re-enactment: a 200 KB act's 5-gram
set holds nearly all of Romanian legal prose, so it contains everything. Jaccard alone fixed that
and broke the realistic case, scoring 0.799 for a struck norm embedded in a slightly longer draft
article — below any threshold worth having. What works is containment for the signal plus a **size
guard**: the matched unit may not be more than `RAPORT_MAX` times the norm, so "contains" cannot be
satisfied by being enormous.

Calibrated on the 174 struck norms the corpus can quote, every one against every other — unrelated
provisions of Romanian law, which is the noise floor of shared legistic boilerplate:

    unrelated pairs   median 0.105 · p99 0.542 · ≥0.80 in 0.03% of 30 102 pairs
    identical                       1.000
    one word in twelve dropped      0.885
    embedded in a longer article    1.000
    half the norm                   0.576

`PRAG = 0.80` sits above the noise and below a lightly-redrafted copy. The 0.03% residue is
same-act structural repetition — an alineat against its own letter, two parallel paragraphs — which
does not arise between a draft and a struck norm.

**Never blocking.** Wording similarity is evidence that a lawyer should look, not a finding that a
provision is unconstitutional: whether a re-enacted norm is *the same norm* in the Court's sense is
a legal judgement about substance, and this is a measurement about characters. Article 147 (4) is
the reason to raise it and not the authority to decide it.

**What it cannot see, it says.** The corpus can quote 174 of the 300 struck provisions with enough
text to compare; the rest are named in the register and have no words attached, so a draft can
re-enact them and nothing here will notice. `acoperire()` is reported next to the findings for
that reason — with a check like this, "no match" and "nothing to match against" are the same
screen and must not be the same sentence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from scripts.parsare_text import parseaza_text

# Characters per shingle. Five is short enough to survive inflection — Romanian legal text
# declines heavily — and long enough that shared function words do not manufacture overlap.
N: Final[int] = 5

# Containment at or above this is reported. See the calibration in the module docstring.
PRAG: Final[float] = 0.80

# Above this, the wording is effectively the struck text rather than merely close to it.
PRAG_APROAPE_IDENTIC: Final[float] = 0.95

# How much larger than the norm a matched unit may be. Containment is trivially satisfied by
# anything big enough to contain everything; this is what stops that.
RAPORT_MAX: Final[float] = 3.0

# Below this many words a provision is too generic to match on: "Prezenta lege intră în vigoare"
# is not a norm anybody re-enacts, it is a sentence every act contains.
CUVINTE_MINIM: Final[int] = 15


def aplatizeaza(text: str) -> str:
    """Lowercase, diacritics removed, punctuation collapsed — the form shingles are cut from.

    Diacritics go because Romanian legal text is transcribed inconsistently (`și`/`si`,
    `condiționată`/`conditionata`), and a re-enactment typed without them is still a re-enactment.
    `provizii_fts` already indexes this way (`remove_diacritics 2`), so the two agree.
    """
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", t)).strip()


@lru_cache(maxsize=512)
def amprenta(text: str) -> frozenset[str]:
    """The set of character 5-grams — an order-insensitive fingerprint of the wording.

    Cached because the comparison set does not change between requests: the shipped norms are the
    same few hundred strings on every lint, and rebuilding their fingerprints was 66 of the pass's
    68 ms — the whole cost, paid again on every keystroke. The cache holds more than the register
    has rows, so the draft's own units never evict a norm.
    """
    plat = aplatizeaza(text)
    return frozenset(plat[i : i + N] for i in range(len(plat) - N + 1))


def continut(unitate: frozenset[str], norma: frozenset[str]) -> float:
    """How much of the struck norm appears in the unit."""
    return len(unitate & norma) / len(norma) if norma else 0.0


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Symmetric overlap — reported so a reader can see whether the unit is the norm or merely
    contains it. Not the gate: it scores 0.799 for a norm inside a slightly longer article."""
    return len(a & b) / len(a | b) if (a or b) else 0.0


@dataclass(frozen=True)
class Reluare:
    """A passage of the draft whose wording tracks a provision the Court struck."""

    unitate: str  # where in the draft — 'art3.alin2', or '' for an unstructured passage
    text: str  # the draft's own words
    act_id: str  # the struck provision's act
    locator: str
    decizie: str
    publicat: str | None
    scor: float  # containment of the struck norm in this unit
    suprapunere: float  # jaccard, for shape
    granularitate: str  # how precisely the struck text itself was recovered
    norma: str  # the struck wording
    temeiuri: tuple  # the constitutional grounds the decision turned on (`temeiuri.py`)

    @property
    def severitate(self) -> str:
        """Always `material`. Whether a re-enacted norm is *the same norm* in the Court's sense is
        a legal judgement about substance; this is a measurement about characters."""
        return "material"

    @property
    def increderea(self) -> str:
        return "derived"

    @property
    def aproape_identic(self) -> bool:
        return self.scor >= PRAG_APROAPE_IDENTIC

    @property
    def temei_rezumat(self) -> str:
        """The constitutional ground, named. `încălcat` is quoted from a verb of violation next to
        the article; a bare mention is only that the article appears in reasoning which may well
        have rejected it, so the two are never phrased alike."""
        incalcate = [t for t in self.temeiuri if t.get("fel") == "incalcat"]
        if incalcate:
            return "Motiv: încalcă " + ", ".join(t["eticheta"] for t in incalcate[:2]) + "."
        if self.temeiuri:
            return (
                "Invocate în considerente (fără a rezulta care au fost reținute): "
                + ", ".join(t["eticheta"] for t in self.temeiuri[:2])
                + "."
            )
        return ""

    @property
    def motiv(self) -> str:
        cand = f" ({self.publicat})" if self.publicat else ""
        cat = "reia aproape identic" if self.aproape_identic else "urmărește îndeaproape"
        unde = f"{self.act_id} {self.locator}".strip()
        nota_gran = (
            ""
            if self.granularitate == "exact"
            else " (textul lovit e cunoscut doar la nivel de articol, nu de alineat)"
        )
        return (
            f"Textul {cat} o prevedere declarată neconstituțională: {unde}, prin "
            f"{self.decizie}{cand}. Suprapunere {self.scor:.0%}{nota_gran}. "
            "Art. 147 alin. (4) leagă erga omnes, deci o normă identică în substanță intră sub "
            "aceeași decizie chiar dacă e renumerotată sau mutată în alt act. "
            "Verifică cu un jurist dacă e aceeași normă."
            + ((" " + self.temei_rezumat) if self.temei_rezumat else "")
        )


def unitati(draft: str) -> list[tuple[str, str]]:
    """The draft cut into provisions: (locator, text).

    Compared provision to provision, never draft to norm. A whole bill contains every norm it
    touches, so scoring the bill as one blob makes containment meaningless — the same failure the
    whole-document rows produced during calibration. A draft with no recoverable structure is
    compared as a single unnamed unit, which is right for the paste-one-article case the UI is
    mostly used for.
    """
    arbore = parseaza_text(draft)
    iesire: list[tuple[str, str]] = []

    def coboara(noduri: list[dict], prefix: str) -> None:
        for n in noduri:
            numar = n.get("numar") or ""
            cale = f"{prefix}.{n['nivel']}{numar}" if prefix else f"{n['nivel']}{numar}"
            cale = cale.strip(".")
            propriu = (n.get("text") or "").strip()
            copii = n.get("copii") or []
            intreg = "\n".join([propriu, *[(c.get("text") or "").strip() for c in copii]]).strip()
            if intreg:
                iesire.append((cale if numar else "", intreg))
            coboara(copii, cale if numar else prefix)

    coboara(arbore["noduri"], "")
    if not iesire and draft.strip():
        iesire.append(("", draft.strip()))
    return iesire


def _lung(text: str) -> bool:
    return len(text.split()) >= CUVINTE_MINIM


def reluari(draft: str, norme: list[dict], *, prag: float = PRAG) -> list[Reluare]:
    """Every passage of the draft whose wording tracks a struck provision, strongest first.

    `norme` is the shipped report — the plain dicts `servicii.construieste_norme_lovite` writes —
    so this runs identically on the localhost server and in the browser, over a file, with no
    database open.
    """
    if not norme:
        return []

    amprente = []
    for rand in norme:
        text = rand.get("norma") or ""
        if _lung(text):
            amprente.append((rand, amprenta(text)))
    if not amprente:
        return []

    gasite: list[Reluare] = []
    vazute: set[tuple[str, str, str]] = set()
    for locator, text in unitati(draft):
        if not _lung(text):
            continue
        a_unitate = amprenta(text)
        for rand, a_norma in amprente:
            # The size guard, before the score: containment is trivially satisfied by anything
            # large enough to contain everything.
            if len(a_unitate) > RAPORT_MAX * len(a_norma):
                continue
            scor = continut(a_unitate, a_norma)
            if scor < prag:
                continue
            cheie = (locator, rand.get("act_id") or "", rand.get("locator") or "")
            if cheie in vazute:
                continue
            vazute.add(cheie)
            gasite.append(
                Reluare(
                    unitate=locator,
                    text=text,
                    act_id=rand.get("act_id") or "",
                    locator=rand.get("locator") or "",
                    decizie=rand.get("decizie") or "",
                    publicat=rand.get("publicat"),
                    scor=scor,
                    suprapunere=jaccard(a_unitate, a_norma),
                    granularitate=rand.get("norma_granularitate") or "",
                    norma=rand.get("norma") or "",
                    temeiuri=tuple(rand.get("temeiuri") or ()),
                )
            )
    return sorted(_cel_mai_strans(gasite), key=lambda r: (-r.scor, r.act_id, r.locator))


def _cel_mai_strans(gasite: list[Reluare]) -> list[Reluare]:
    """One finding per re-enactment, at the tightest unit that carries it.

    An article contains its own alineate, so a norm re-enacted in `art1.alin2` matches `art1` as
    well and the same fact is reported twice at two levels. The narrower unit is the useful one:
    it points at the sentence a drafter has to change, and its score is not diluted by the
    surrounding text. Only nesting is collapsed — two different articles that both re-enact the
    same norm are two separate problems and both are reported.
    """
    pastrate: list[Reluare] = []
    for r in gasite:
        acoperit = any(
            alt is not r
            and (alt.act_id, alt.locator) == (r.act_id, r.locator)
            and alt.unitate != r.unitate
            and r.unitate
            and alt.unitate.startswith(r.unitate + ".")
            for alt in gasite
        )
        if not acoperit:
            pastrate.append(r)
    return pastrate


def acoperire(norme: list[dict]) -> dict:
    """How much of the register this check can actually see.

    Reported next to the findings, because with a check like this "no match" and "nothing to match
    against" appear on the same screen and must not read as the same sentence.
    """
    total = len(norme)
    comparabile = sum(1 for n in norme if _lung(n.get("norma") or ""))
    return {
        "prevederi": total,
        "comparabile": comparabile,
        "procent": round(100 * comparabile / total) if total else 0,
    }


def raport(gasite: list[Reluare], coperta: dict | None = None) -> str:
    linii = []
    if coperta:
        linii.append(
            f"Comparat cu {coperta['comparabile']} din {coperta['prevederi']} prevederi lovite "
            f"({coperta['procent']}%) — restul sunt cunoscute doar ca trimitere, fără text."
        )
    if not gasite:
        linii.append("Nicio formulare din proiect nu reia o prevedere lovită.")
        return "\n".join(linii)
    for r in gasite:
        unde = f"[{r.unitate}] " if r.unitate else ""
        linii.append(f"{unde}{r.scor:.0%} · {r.act_id} {r.locator} — {r.decizie}")
        linii.append(f'    proiect: „{" ".join(r.text.split())[:140]}"')
        linii.append(f'    lovit  : „{" ".join(r.norma.split())[:140]}"')
    return "\n".join(linii)
