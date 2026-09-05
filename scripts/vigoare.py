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
corpus, so this can miss a repeal not yet collected — it never invents one. And it does not model
republication renumbering: after a law is republished, "art. 15" means a different provision than
before, and this package records the republication date (`ActParsat.republicat_din`) but does not
yet remap locators across it. So a repeal is reported with its date and its source act, for a
human to weigh, and where the data cannot reach the answer is "not known repealed", never "in
force" asserted.

Read-only on the graph, so it runs while the corpus and graph fill.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from scripts.graf import _muchie
from scripts.referinte import referinte


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
    """A reference in a draft to something the graph shows repealed."""

    text: str
    act_id: str
    locator: str
    abrogare: Abrogare

    @property
    def motiv(self) -> str:
        cand = f" ({self.abrogare.de_la:%d.%m.%Y})" if self.abrogare.de_la else ""
        de = f" prin {self.abrogare.de_catre}" if self.abrogare.de_catre else ""
        if self.abrogare.este_intregul_act:
            return f"actul {self.act_id} este abrogat în întregime{de}{cand}"
        return f"{self.act_id} {self.locator} este abrogat{de}{cand}"


def citari_moarte(draft: str, graf: sqlite3.Connection) -> list[CitareMoarta]:
    """Every reference in the draft that points at a repealed act or article.

    A whole-act repeal condemns any citation into that act; an article repeal condemns a citation
    to that article or anything under it. The point is narrow and load-bearing: do not let a draft
    build on law that is gone.
    """
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
            gasite.append(CitareMoarta(r.text, r.act.id, r.locator.id, intreg))
            continue
        if r.locator.id:
            abrogati = locatori_abrogati(graf, r.act.id)
            # a citation to art7.alin2 is dead if art7.alin2 or its parent art7 was repealed
            for loc, ab in abrogati.items():
                if r.locator.id == loc or r.locator.id.startswith(loc + "."):
                    gasite.append(CitareMoarta(r.text, r.act.id, r.locator.id, ab))
                    break
    return gasite
