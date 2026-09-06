"""What is still in force, and what a draft cites that is not.

The failure this package's first critique named as the one that loses credibility in public: a
linter that flags a contradiction with an article repealed years ago, or lets a drafter cite a
provision that no longer exists. The graph now makes it avoidable. An `abroga` edge is a repeal
with a date — `de_la` is when it took effect — so "is this article still in force" is a query, not
a guess: an article is repealed if some act points an `abroga` edge at it.

**Two grains, because repeal has two.** A whole act is repealed when an `abroga` edge targets it
with no locator (`se abrogă Legea nr. 50/1991`); a single article is repealed when the edge
carries that article's locator (`Articolul 15 se abrogă`). Both are answered here, and a citation
to a repealed article is caught even when the act around it lives on.

**Honest about its reach, like the gap report.** The graph sees only repeals whose acts are in the
corpus, so this can miss a repeal not yet collected — it never invents one. So a repeal is reported
with its date and its source act, for a human to weigh, and where the data cannot reach the answer
is "not known repealed", never "in force" asserted.

**Republication is a renumbering boundary, so it is not asserted across.** After a law is
republished, `art. 15` means a different provision than before. This package does not remap
locators across that boundary — nothing in the corpus carries the old-to-new correspondence — so
where a match depends on crossing it, the finding is *qualified* instead of asserted: it keeps its
place in the report, says that the repeal predates the republication and that the locator may name
a different provision, and drops from blocking to material. Silently asserting it would tell a
drafter their citation is dead when the article now numbered 15 may never have been touched, and
that is the false positive this whole package exists to avoid. `consolidare.py` refuses across the
same boundary for the same reason.

Two things are deliberately *not* qualified. A **whole-act** repeal does not depend on numbering —
the act is gone whatever its articles are called — so it stays blocking. And where no republication
date is known the behaviour is exactly as before, because an absent date is not evidence of a
boundary.

Read-only on the graph, so it runs while the corpus and graph fill.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from scripts.graf import _muchie
from scripts.referinte import referinte

# act_id -> the date it was republished, where the corpus records one. Callers that have no such
# data pass nothing and every finding behaves exactly as it did before.
Republicari = Mapping[str, date | None]


def _peste_republicare(
    locator: str, de_la: date | None, republicat_din: date | None
) -> date | None:
    """The republication date a locator match must cross to hold, or None if it crosses none.

    A whole-act edge (no locator) never crosses one: renumbering cannot save an act that is gone.
    A dateless edge cannot be placed relative to the boundary, so with a republication on record it
    counts as crossing — the same call `consolidare.py` makes for an operation it cannot date.
    """
    if not locator or republicat_din is None:
        return None
    return republicat_din if de_la is None or de_la < republicat_din else None


@dataclass(frozen=True)
class Abrogare:
    """A repeal the graph asserts: what was repealed, when, by which act."""

    act_id: str
    locator: str  # '' = the whole act
    de_la: date | None
    de_catre: str

    @property
    def este_intregul_act(self) -> bool:
        return self.locator == ""


def _abrogari(graf: sqlite3.Connection, act_id: str) -> list[Abrogare]:
    randuri = graf.execute(
        "SELECT * FROM muchii WHERE catre_act = ? AND fel = 'abroga' ORDER BY de_la", (act_id,)
    ).fetchall()
    return [Abrogare(act_id, m.locator, m.de_la, m.din_act) for m in (_muchie(r) for r in randuri)]


def este_abrogat(graf: sqlite3.Connection, act_id: str) -> Abrogare | None:
    """The whole-act repeal, if any. A citation to any part of the act is stale once this holds."""
    return next((a for a in _abrogari(graf, act_id) if a.este_intregul_act), None)


def locatori_abrogati(graf: sqlite3.Connection, act_id: str) -> dict[str, Abrogare]:
    """Which articles of the act the graph shows repealed, keyed by locator."""
    return {a.locator: a for a in _abrogari(graf, act_id) if a.locator}


@dataclass(frozen=True)
class CitareMoarta:
    """A reference in a draft to something the graph shows repealed.

    `peste_republicare` is set when the match only holds by reading a pre-republication locator as
    if it were current numbering. Then the finding is a question, not a verdict.
    """

    text: str
    act_id: str
    locator: str
    abrogare: Abrogare
    peste_republicare: date | None = None

    @property
    def severitate(self) -> str:
        return "material" if self.peste_republicare else "blocking"

    @property
    def motiv(self) -> str:
        cand = f" ({self.abrogare.de_la:%d.%m.%Y})" if self.abrogare.de_la else ""
        de = f" prin {self.abrogare.de_catre}" if self.abrogare.de_catre else ""
        if self.abrogare.este_intregul_act:
            return f"actul {self.act_id} este abrogat în întregime{de}{cand}"
        baza = f"{self.act_id} {self.locator} este abrogat{de}{cand}"
        if self.peste_republicare is None:
            return baza
        # Say what is uncertain and why, rather than asserting a repeal the numbering may not bear
        return (
            f"{baza} — dar abrogarea este anterioară republicării actului "
            f"({self.peste_republicare:%d.%m.%Y}), așa că «{self.locator}» se poate referi la altă "
            f"prevedere decât cea numerotată azi astfel; de verificat în textul republicat"
        )


def citari_moarte(
    draft: str, graf: sqlite3.Connection, republicari: Republicari | None = None
) -> list[CitareMoarta]:
    """Every reference in the draft that points at a repealed act or article.

    A whole-act repeal condemns any citation into that act; an article repeal condemns a citation
    to that article or anything under it. The point is narrow and load-bearing: do not let a draft
    build on law that is gone.

    `republicari` maps an act to its republication date. Where one is known and the repeal predates
    it, the article-level finding is qualified rather than asserted (see the module docstring); pass
    nothing and every finding behaves as it did before.
    """
    rep = republicari or {}
    gasite: list[CitareMoarta] = []
    vazute: set[tuple[str, str]] = set()
    for r in referinte(draft):
        if r.act is None:
            continue
        cheie = (r.act.id, r.locator.id)
        if cheie in vazute:
            continue
        vazute.add(cheie)

        intreg = este_abrogat(graf, r.act.id)
        if intreg is not None:
            # whole-act: no locator to renumber, so never qualified
            gasite.append(CitareMoarta(r.text, r.act.id, r.locator.id, intreg))
            continue
        if r.locator.id:
            abrogati = locatori_abrogati(graf, r.act.id)
            # a citation to art7.alin2 is dead if art7.alin2 or its parent art7 was repealed
            for loc, ab in abrogati.items():
                if r.locator.id == loc or r.locator.id.startswith(loc + "."):
                    gasite.append(
                        CitareMoarta(
                            r.text,
                            r.act.id,
                            r.locator.id,
                            ab,
                            _peste_republicare(loc, ab.de_la, rep.get(r.act.id)),
                        )
                    )
                    break
    return gasite


# Repeal is not the only thing that qualifies a citation. The graph also records that an act was
# *suspended* (temporarily not in force), that another act *derogates* from it (an exception applies
# in the derogating act's scope), or that a term in it was *prorogated* (a deadline pushed back).
# None of these is death, so they are not `citari_moarte` — but a drafter citing such a provision as
# if it stood unqualified is building on shifting ground, and the graph already carries the edges.
_CALIFICARI: dict[str, str] = {
    "suspenda": "suspendat",
    "deroga": "derogare",
    "proroga": "prorogat",
}


@dataclass(frozen=True)
class Calificare:
    """A qualification the graph asserts over an act or article: what, when, by which act."""

    act_id: str
    locator: str  # '' = the whole act
    fel: str  # suspenda | deroga | proroga
    de_la: date | None
    de_catre: str

    @property
    def este_intregul_act(self) -> bool:
        return self.locator == ""


def _calificari(graf: sqlite3.Connection, act_id: str) -> list[Calificare]:
    marcaje = ",".join("?" * len(_CALIFICARI))
    randuri = graf.execute(
        f"SELECT * FROM muchii WHERE catre_act = ? AND fel IN ({marcaje}) ORDER BY de_la",
        (act_id, *_CALIFICARI),
    ).fetchall()
    muchii = (_muchie(r) for r in randuri)
    return [Calificare(act_id, m.locator, m.fel, m.de_la, m.din_act) for m in muchii]


@dataclass(frozen=True)
class CitareCalificata:
    """A reference in a draft to a provision the graph shows suspended, derogated or prorogated."""

    text: str
    act_id: str
    locator: str
    calificare: Calificare
    peste_republicare: date | None = None

    @property
    def motiv(self) -> str:
        cand = f" ({self.calificare.de_la:%d.%m.%Y})" if self.calificare.de_la else ""
        de = f" prin {self.calificare.de_catre}" if self.calificare.de_catre else ""
        unde = self.act_id if self.calificare.este_intregul_act else f"{self.act_id} {self.locator}"
        if self.calificare.fel == "suspenda":
            baza = f"aplicarea {unde} este suspendată{de}{cand}"
        elif self.calificare.fel == "deroga":
            cine = self.calificare.de_catre or "un act"
            baza = f"{cine} derogă de la {unde}{cand} — se aplică o excepție"
        else:
            baza = f"un termen din {unde} a fost prorogat{de}{cand}"
        if self.peste_republicare is None:
            return baza
        return (
            f"{baza} — dar este anterioară republicării actului "
            f"({self.peste_republicare:%d.%m.%Y}), așa că «{self.locator}» se poate referi la altă "
            f"prevedere decât cea numerotată azi astfel"
        )

    @property
    def eticheta(self) -> str:
        return _CALIFICARI.get(self.calificare.fel, self.calificare.fel)


def citari_calificate(
    draft: str, graf: sqlite3.Connection, republicari: Republicari | None = None
) -> list[CitareCalificata]:
    """Every reference in the draft to a provision with a qualified status short of repeal.

    Same reach rule as `citari_moarte`: a whole-act qualification touches any citation into the act;
    an article-level one touches that article or anything under it. A provision already caught as
    repealed is not repeated here — death subsumes qualification. The same republication boundary
    applies, for the same reason: these edges carry locators too.
    """
    rep = republicari or {}
    morti = {(c.act_id, c.locator) for c in citari_moarte(draft, graf, rep)}
    gasite: list[CitareCalificata] = []
    vazute: set[tuple[str, str]] = set()
    for r in referinte(draft):
        if r.act is None:
            continue
        cheie = (r.act.id, r.locator.id)
        if cheie in vazute or cheie in morti:
            continue
        vazute.add(cheie)
        for cal in _calificari(graf, r.act.id):
            atinge = (
                cal.este_intregul_act
                or r.locator.id == cal.locator
                or (r.locator.id and r.locator.id.startswith(cal.locator + "."))
            )
            if atinge:
                gasite.append(
                    CitareCalificata(
                        r.text,
                        r.act.id,
                        r.locator.id,
                        cal,
                        _peste_republicare(cal.locator, cal.de_la, rep.get(r.act.id)),
                    )
                )
                break
    return gasite
