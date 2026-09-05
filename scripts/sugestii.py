"""While a draft is being written: the legistic form of what the line seems to intend.

The draft assistant (`redactare.py`) works from a filled form — operation, act, article. This works
from the sentence itself, as it is typed, and it is the half that meets a person who thinks in
plain language rather than in Legea 24/2000 formulas. Given a line like `vreau să schimb articolul 7
din Legea 98/2016`, it recognises the intent (a modification of art. 7), and offers two readings of
it side by side:

- **plain** — what the operation does, said the way a person would say it, so the writer can confirm
  the tool understood them before taking anything;
- **formula** — the exact phrasing Legea 24/2000 requires for that operation, ready to paste, built
  by `redactare.redacteaza` so there is one source of truth for the mandated form.

**Deterministic, no language model** — the invariant the whole package and its UI advertise. It
recognises the operation from a fixed vocabulary (the standard legistic verbs, and the non-standard
ones `redactare.NESTANDARD` already maps to their correct form), and the target from
`referinte.py`. It does not paraphrase arbitrary prose; when it recognises nothing it says nothing,
because a suggestion the tool is not sure of is worse than no suggestion in a place a writer trusts.
A model that could restate any sentence in plain language is a later, opt-in possibility, not this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.amendamente import VERBE
from scripts.redactare import NESTANDARD, redacteaza
from scripts.referinte import Act, Locator, acte, locatori, uneste
from scripts.text import normalizeaza

# The operations `redactare.redacteaza` can phrase — the ones a suggestion is useful for. Other
# verbs (prorogă, suspendă, înlocuiește) are recognised by the extractors but have no single
# paste-ready form here, so a suggestion is not offered rather than half-offered.
_REDACTABILE = {"modifica", "abroga", "completeaza", "introduce"}

_NEGAT = re.compile(r"\bnu\s+$", re.IGNORECASE)

# Cite an act the way it must be cited, reconstructed from what `referinte` parsed. The writer's
# own phrasing may carry more ("privind achizițiile publice") and they can keep it; this is the
# minimum correct citation so the formula is not left with a blank where the act goes.
_CITARE: dict[str, str] = {
    "lege": "Legea nr. {n}/{an}",
    "oug": "Ordonanța de urgență a Guvernului nr. {n}/{an}",
    "og": "Ordonanța Guvernului nr. {n}/{an}",
    "hg": "Hotărârea Guvernului nr. {n}/{an}",
    "ordin": "Ordinul nr. {n}/{an}",
    "decret": "Decretul nr. {n}/{an}",
}
_CODURI: dict[str, str] = {
    "constitutie": "Constituția României",
    "cod-fiscal": "Codul fiscal",
    "cod-civil": "Codul civil",
    "cod-penal": "Codul penal",
    "cod-muncii": "Codul muncii",
    "cod-administrativ": "Codul administrativ",
    "cod-procedura-civila": "Codul de procedură civilă",
    "cod-procedura-penala": "Codul de procedură penală",
    "cod-procedura-fiscala": "Codul de procedură fiscală",
}


@dataclass(frozen=True)
class Sugestie:
    """One reading of a line: what it does (plain) and how the law makes it say it (formula)."""

    fel: str
    act_id: str
    locator_id: str
    simplu: str  # plain-language restatement — the "did I understand you" half
    formula: str  # the Legea 24/2000 phrasing, ready to paste
    nestandard: bool  # the writer used a form the Council would reject; the formula corrects it


def _combina(locuri) -> Locator:
    """One target from a line's locator pieces. `articolul 7 din Legea 98/2016, alineatul (2)` is
    read as two locators because the act citation sits between them; a drafting line means one
    provision, so the deepest of each level is folded into a single locator. Best-effort, since
    the writer confirms the suggestion before taking it."""
    art = alin = lit = pct = None
    for lo in locuri:
        art = art or lo.articol
        alin = alin or lo.alineat
        lit = lit or lo.litera
        pct = pct or lo.punct
    return Locator(articol=art, alineat=alin, litera=lit, punct=pct)


def _citare(act: Act) -> str:
    if act.tip in _CODURI:
        return _CODURI[act.tip]
    sablon = _CITARE.get(act.tip)
    if sablon and act.numar and act.an:
        return sablon.format(n=act.numar, an=act.an)
    return "actul vizat"


def _locator_ro(loc: Locator) -> str:
    """The target in declined Romanian, deepest unit first — `litera a) a alineatului (2) al
    articolului 7`. Only the combinations a locator actually produces are spelled out."""
    art_n = f"articolul {loc.articol}"  # nominative, when the article is the head
    art_g = f"articolului {loc.articol}"  # genitive, when something hangs off it
    alin_n = f"alineatul ({loc.alineat})"
    alin_g = f"alineatului ({loc.alineat})"
    lit = f"litera {loc.litera})"
    if loc.litera and loc.alineat and loc.articol:
        return f"{lit} a {alin_g} al {art_g}"
    if loc.alineat and loc.articol:
        return f"{alin_n} al {art_g}"
    if loc.litera and loc.articol:
        return f"{lit} a {art_g}"
    if loc.articol:
        return art_n
    if loc.alineat:
        return alin_n
    if loc.litera:
        return lit
    return "prevederea vizată"


def _detecteaza(text: str) -> tuple[str, bool] | None:
    """The operation the line intends, and whether it was said in a non-standard form.

    Standard legistic verbs win; failing those, the non-standard forms `redactare` maps to a
    correct operation are tried, because catching `se schimbă` and offering `se modifică ...` is
    the whole point of suggesting while someone writes informally. A verb negated by a preceding
    `nu` is not an operation."""
    for fel, sablon in VERBE:
        for m in re.finditer(sablon, text, re.IGNORECASE):
            if not _NEGAT.search(text[max(0, m.start() - 6) : m.start()]):
                return fel, False
    for op, sabloane in NESTANDARD.items():
        for sablon in sabloane:
            if re.search(sablon, text, re.IGNORECASE):
                return op, True
    return None


_GLOSA: dict[str, str] = {
    "modifica": "Rescrii {loc} din {act} cu un text nou.",
    "abroga": "Elimini {loc} din {act} — nu se mai aplică.",
    "completeaza": "Adaugi text nou la {loc} din {act}, fără a rescrie ce există.",
    "introduce": "Introduci o prevedere nouă după {loc} din {act}.",
}


def sugereaza(linie: str) -> Sugestie | None:
    """The suggestion for one line of a draft, or None when nothing is recognised.

    `linie` is the paragraph the caret is in, not the whole draft: a suggestion is about the
    sentence being written, and running the detectors over the whole text would offer the first
    amendment in it no matter where the writer is."""
    text = normalizeaza(linie)
    det = _detecteaza(text)
    if det is None:
        return None
    fel, nestandard = det
    if fel not in _REDACTABILE:
        return None

    refs = acte(text)
    act = refs[0].act if refs else None
    loc = _combina(lc[0] for lc in uneste(locatori(text), text))
    if act is None and not loc:
        return None  # nothing to point the operation at

    citare = _citare(act) if act else "actul vizat"
    formula = redacteaza(
        fel,
        citare,
        articol=loc.articol,
        alineat=loc.alineat,
        litera=loc.litera,
    )
    simplu = _GLOSA[fel].format(loc=_locator_ro(loc), act=citare)
    return Sugestie(
        fel=fel,
        act_id=act.id if act else "",
        locator_id=loc.id,
        simplu=simplu,
        formula=formula,
        nestandard=nestandard,
    )
