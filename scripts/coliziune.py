"""A draft against the provisions the Court struck and nobody repaired.

The register (`neconstitutional.py`) answers a corpus-wide question: which struck provisions were
never brought into line. This asks the drafter's question, which is narrower and far more useful
while a text is being written — *does the article I am touching sit on one of them*.

It is the highest-value thing this package can say to someone drafting, and the cheapest: no
model, no network, no search. The register is a few hundred rows; the draft's citations are read
by `referinte`; the answer is an intersection.

**Two severities that point opposite ways, and conflating them would be the whole bug.** The
register's own `severitate` is *evidential*: `blocking` there means the corpus cannot vouch for
the row — it cannot tell a provision still unrepaired from a repair never collected. The linter's
`severitate` is about *weight*: `blocking` means stop, this must be fixed. So a register row
marked `blocking` must produce a lint finding marked `material`, never `blocking`. A row the data
cannot stand behind is exactly the row that must not stop a bill. `sustinut` carries the
distinction and `_severitate` applies it.

**The match is stricter here than in the register, on purpose.** `neconstitutional._atinge` is
deliberately generous, and it is right to be: a register that misses a row is worse than one that
shows a near miss, because a researcher reads the caveats. A drafter does not — a finding on
screen while they type reads as a verdict. So the reach is graded rather than boolean, and only
the two grades where the cited text is *itself* without legal effect are allowed to block:

- `exact` — the draft cites the struck provision.
- `sub`   — the draft cites inside it (struck art. 7; draft cites art. 7 alin. (2)).
- `peste` — the draft cites around it (struck art. 7 alin. (2); draft cites art. 7). Part of what
            it cites still stands, so this is a warning, not a verdict.
- `tot_actul` — the whole act was struck. 62% of the register's rows are whole-act, and a
            whole-act row matches any citation into that act: the loudest possible finding on the
            weakest possible basis. Material, never blocking.
- `act`   — the draft cites the act with no article, and some article of it is struck.

**Silent where the data cannot reach.** No register shipped means no findings, exactly as the
graph-gated passes behave. An empty pass and a pass that never ran must not look alike to a
reader, so the service reports which it was; this module simply returns nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from scripts.referinte import referinte

# Reach grades in descending order of how directly the draft sits on the struck text.
POTRIVIRI: tuple[str, ...] = ("exact", "sub", "peste", "tot_actul", "act")

# The two grades where the text the draft cites is itself without legal effect.
_DIRECTE: frozenset[str] = frozenset({"exact", "sub"})


@dataclass(frozen=True)
class Coliziune:
    """A draft citation landing on a struck, unrepaired provision."""

    text: str  # the draft's own words, so the finding can be quoted back
    act_id: str
    locator: str  # what the draft cited ('' = the act, no article)
    locator_lovit: str  # what the Court struck ('' = the whole act)
    fel: str  # neconstitutional | abrogat_constitutional
    decizie: str  # the earliest decision that struck it
    publicat: date | None
    decizii: tuple[str, ...]  # every decision in the register that struck this provision
    termen: date | None
    zile_de_la_termen: int | None
    potrivire: str
    sustinut: bool  # whether the register can stand behind the absence of a repair
    limitari: tuple[str, ...]
    citat: str  # the span quoted from the decision — a citation, not the norm
    norma: str  # the struck provision's own words, where the corpus can produce them
    norma_granularitate: str  # exact | articol | '' (not recovered)
    norma_nota: str  # what a reader must be told before quoting `norma`
    temeiuri: tuple  # the constitutional grounds the decision turned on (`temeiuri.py`)

    @property
    def severitate(self) -> str:
        """`blocking` only where the cited text is itself dead *and* the register backs it."""
        if self.potrivire in _DIRECTE and self.sustinut:
            return "blocking"
        return "material"

    @property
    def increderea(self) -> str:
        """The strike is quoted from a decision; that nobody repaired it is always derived from
        what happens to have been collected. The weaker of the two governs."""
        return "derived"

    @property
    def unde(self) -> str:
        return self.act_id if not self.locator_lovit else f"{self.act_id} {self.locator_lovit}"

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
        cand = f" ({self.publicat:%d.%m.%Y})" if self.publicat else ""
        alte = f" și prin încă {len(self.decizii) - 1} decizii" if len(self.decizii) > 1 else ""

        if self.fel == "abrogat_constitutional":
            lovit = (
                f"{self.unde} a fost abrogat prin art. 150 alin. (1) din Constituție, "
                f"constatat prin {self.decizie}{cand}{alte}"
            )
        else:
            intarziere = (
                f", iar termenul de 45 de zile din art. 147 alin. (1) a expirat de "
                f"{self.zile_de_la_termen} de zile"
                if self.zile_de_la_termen
                else ""
            )
            lovit = (
                f"{self.unde} a fost declarat neconstituțional prin {self.decizie}"
                f"{cand}{alte}{intarziere}"
            )

        temei = (" " + self.temei_rezumat) if self.temei_rezumat else ""
        if self.potrivire == "exact":
            return f"{lovit}. Nimic din corpus nu arată că a fost pus în acord.{temei}"
        if self.potrivire == "sub":
            return (
                f"Textul citat ({self.locator}) se află în interiorul unei prevederi lovite: "
                f"{lovit}. Nimic din corpus nu arată că a fost pus în acord.{temei}"
            )
        if self.potrivire == "peste":
            return (
                f"Prevederea citată ({self.locator or 'actul'}) conține o parte lovită și "
                f"nereparată: {lovit}. Restul textului citat rămâne în vigoare.{temei}"
            )
        if self.potrivire == "tot_actul":
            return f"Întregul act a fost lovit: {lovit}.{temei}"
        return f"Actul citat conține o prevedere lovită și nereparată: {lovit}.{temei}"


def _potrivire(loc_draft: str, loc_lovit: str) -> str | None:
    """How directly a draft citation sits on a struck provision, or `None` if it does not."""
    if not loc_lovit:
        return "tot_actul"
    if not loc_draft:
        return "act"
    if loc_draft == loc_lovit:
        return "exact"
    if loc_draft.startswith(loc_lovit + "."):
        return "sub"
    if loc_lovit.startswith(loc_draft + "."):
        return "peste"
    return None


def _data(brut) -> date | None:
    if isinstance(brut, date):
        return brut
    try:
        return date.fromisoformat(brut) if brut else None
    except (TypeError, ValueError):
        return None


def _rang(c: Coliziune) -> tuple:
    return (
        POTRIVIRI.index(c.potrivire),
        0 if c.severitate == "blocking" else 1,
        -(c.zile_de_la_termen or 0),
        c.act_id,
        c.locator_lovit,
    )


def coliziuni(draft: str, registru: list[dict]) -> list[Coliziune]:
    """Every place the draft touches a struck, unrepaired provision, worst reach first.

    `registru` is the shipped report — the plain dicts `servicii.construieste_neconstitutional`
    writes — so this runs identically on the localhost server and in the browser, over a file, with
    no database open. A few hundred rows against a handful of citations: the cost is the regex pass
    over the draft, not the matching.
    """
    if not registru:
        return []

    # The register carries one row per *decision*, and several provisions were struck repeatedly —
    # `art. 224 din Codul penal` by four separate decisions. Four identical findings on one line of
    # a draft is noise, so they collapse to the provision, named by the decision whose clock ran
    # first, and the rest are counted.
    pe_prevedere: dict[tuple[str, str], list[dict]] = {}
    for r in registru:
        act = r.get("act_id") or ""
        if act:
            pe_prevedere.setdefault((act, r.get("locator") or ""), []).append(r)

    pe_act: dict[str, list[tuple[str, list[dict]]]] = {}
    for (act, loc), randuri in pe_prevedere.items():
        pe_act.setdefault(act, []).append((loc, randuri))

    gasite: list[Coliziune] = []
    vazute: set[tuple[str, str, str]] = set()
    for r in referinte(draft):
        if r.act is None or r.act.id not in pe_act:
            continue
        for loc_lovit, randuri in pe_act[r.act.id]:
            grad = _potrivire(r.locator.id, loc_lovit)
            if grad is None:
                continue
            cheie = (r.act.id, r.locator.id, loc_lovit)
            if cheie in vazute:
                continue
            vazute.add(cheie)

            prima = min(
                randuri,
                key=lambda x: (_data(x.get("publicat")) or date.max, x.get("decizie") or ""),
            )
            gasite.append(
                Coliziune(
                    text=r.text,
                    act_id=r.act.id,
                    locator=r.locator.id,
                    locator_lovit=loc_lovit,
                    fel=prima.get("fel") or "neconstitutional",
                    decizie=prima.get("decizie") or "",
                    publicat=_data(prima.get("publicat")),
                    decizii=tuple(sorted({x.get("decizie") or "" for x in randuri})),
                    termen=_data(prima.get("termen")),
                    zile_de_la_termen=max(
                        (x.get("zile_de_la_termen") or 0 for x in randuri), default=0
                    )
                    or None,
                    potrivire=grad,
                    # Backed only if *every* decision that struck it is backed: one row the corpus
                    # cannot vouch for is enough to stop the finding blocking a bill.
                    sustinut=all(x.get("severitate") != "blocking" for x in randuri),
                    limitari=tuple(
                        dict.fromkeys(lim for x in randuri for lim in x.get("limitari", []))
                    ),
                    citat=(prima.get("text") or "")[:300],
                    norma=prima.get("norma") or "",
                    norma_granularitate=prima.get("norma_granularitate") or "",
                    norma_nota=prima.get("norma_nota") or "",
                    temeiuri=tuple(prima.get("temeiuri") or ()),
                )
            )
    return sorted(gasite, key=_rang)


def raport(gasite: list[Coliziune]) -> str:
    """The findings as a person reads them, each with its caveats attached to its own row."""
    if not gasite:
        return "Nicio prevedere lovită și nereparată printre cele citate de proiect."
    linii = []
    for c in gasite:
        linii.append(f"[{c.severitate}] {c.text.strip()[:80]} → {c.motiv}")
        if c.citat:
            linii.append(f'    din decizie: „{c.citat[:120]}"')
        if c.norma:
            eticheta = (
                "textul lovit" if c.norma_granularitate == "exact" else "articolul care îl conține"
            )
            linii.append(f'    {eticheta}: „{" ".join(c.norma.split())[:200]}"')
        if c.norma_nota:
            linii.append(f"    ⚠ {c.norma_nota}")
        for lim in c.limitari:
            linii.append(f"    ⚠ {lim}")
    return "\n".join(linii)
