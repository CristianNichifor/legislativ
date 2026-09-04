"""Obligations the corpus cannot show were ever discharged.

This is the finding the linter should lead with. It needs no language model, it is arithmetic
over dates and edges, and it can be handed to a committee in the form a committee can use: *this
law required implementing norms within 30 days of entry into force in 2016; no act issuing them
appears in the corpus; that is N days.* Every clause of that sentence is checkable, and the ones
that are not facts about the law are declared as facts about the data.

**Absence is only evidence if the corpus is complete for what is absent.** A missing hotărâre de
Guvern in a scrape that never collected hotărâri means nothing whatsoever, and a linter that
reports it as a legislative gap is producing exactly the confident, plausible, wrong output that
makes a research team stop trusting the tool. So `Corpus` carries `complet_pentru`: the act types
it claims to have collected exhaustively. An obligation whose expected instrument falls outside
that set still produces a finding — silence would be worse — but the finding is `blocking` and
says on its face that it cannot distinguish a gap in the law from a gap in the scrape.

**A near miss is more useful than a clean negative.** When an implementing act references the
right law but is the wrong instrument, or the right instrument published years late, that is a
different political fact from nothing at all, and it is the one a researcher will be asked about
first. Candidates are therefore returned with the finding rather than filtered out of it.

**Overdue is counted from a real anchor or not at all.** If the host act's entry into force is
unknown, `zile_intarziere` is `None` and stays `None`. A gap of "about eight years" computed from
an assumed date is the kind of number that survives one meeting and then collapses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from scripts.referinte import Act
from scripts.termene import Obligatie


@dataclass(frozen=True)
class ActCunoscut:
    """An act the corpus actually holds, with the dates the arithmetic needs."""

    act: Act
    titlu: str = ""
    publicat: date | None = None
    vigoare: date | None = None
    referinte_la: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Corpus:
    """What has been collected, and what it claims to be complete about."""

    acte: dict[str, ActCunoscut] = field(default_factory=dict)
    complet_pentru: frozenset[str] = field(default_factory=frozenset)

    def implementari(self, tinta: str, tip: str | None, dupa: date | None) -> list[ActCunoscut]:
        """Acts that point at `tinta`, optionally of one type, optionally published after a date."""
        gasite = [
            a
            for a in self.acte.values()
            if tinta in a.referinte_la
            and a.act.id != tinta
            and (tip is None or a.act.tip == tip)
            and (dupa is None or a.publicat is None or a.publicat >= dupa)
        ]
        return sorted(gasite, key=lambda a: (a.publicat or date.min, a.act.id))


@dataclass(frozen=True)
class Vid:
    """An obligation with nothing in the corpus to discharge it."""

    obligatie: Obligatie
    scadenta: date | None
    zile_intarziere: int | None
    cautat: str
    candidati: tuple[str, ...]
    severitate: str
    limitari: tuple[str, ...]

    @property
    def increderea(self) -> str:
        """`verbatim` is never right here: the obligation is quoted, but the *absence* is always
        derived from what happens to have been collected."""
        return "derived"


def _limitari(ob: Obligatie, corpus: Corpus, scadenta: date | None) -> tuple[list[str], str]:
    limitari: list[str] = []
    severitate = "material"
    if ob.tip_asteptat is None:
        limitari.append(
            "Instrumentul cerut nu a fost recunoscut, așa că absența lui nu a putut fi căutată "
            "pe tip; s-a căutat orice act care trimite la actul-gazdă."
        )
    if ob.tip_asteptat is not None and ob.tip_asteptat not in corpus.complet_pentru:
        limitari.append(
            f"Corpusul nu se declară complet pentru actele de tip «{ob.tip_asteptat}». "
            "Lipsa lui nu distinge un vid legislativ de o lipsă a colectării."
        )
        severitate = "blocking"
    if scadenta is None:
        limitari.append(
            "Actul-gazdă nu are dată de intrare în vigoare cunoscută, deci întârzierea nu poate "
            "fi calculată."
        )
    return limitari, severitate


def vid_legislativ(
    obligatii: list[Obligatie],
    corpus: Corpus,
    la_data: date,
) -> list[Vid]:
    """Which of these obligations the corpus cannot show were met, worst overdue first.

    An obligation is treated as discharged by any act of the expected type that references the
    host act and was published no earlier than it. That is a generous test on purpose: the cost
    of missing a real gap is a quieter report, while the cost of inventing one is a researcher
    standing up in public behind a finding that dissolves on contact.
    """
    gasite: list[Vid] = []
    for ob in obligatii:
        if ob.act is None:
            continue
        gazda = corpus.acte.get(ob.act.id)
        scadenta = ob.scadenta(
            vigoare=gazda.vigoare if gazda else None,
            publicare=gazda.publicat if gazda else None,
        )
        implementari = corpus.implementari(
            ob.act.id, ob.tip_asteptat, gazda.publicat if gazda else None
        )
        if implementari:
            continue

        oricare = corpus.implementari(ob.act.id, None, None)
        limitari, severitate = _limitari(ob, corpus, scadenta)
        intarziere = (la_data - scadenta).days if scadenta and la_data > scadenta else None
        gasite.append(
            Vid(
                obligatie=ob,
                scadenta=scadenta,
                zile_intarziere=intarziere,
                cautat=(
                    f"act de tip «{ob.tip_asteptat}» care trimite la {ob.act.id}"
                    if ob.tip_asteptat
                    else f"orice act care trimite la {ob.act.id}"
                ),
                candidati=tuple(a.act.id for a in oricare),
                severitate=severitate,
                limitari=tuple(limitari),
            )
        )
    return sorted(
        gasite,
        key=lambda v: (-(v.zile_intarziere or 0), v.obligatie.act.id if v.obligatie.act else ""),
    )


def raport(vids: list[Vid]) -> str:
    """The table as it goes in front of a room, with every caveat attached to its own row."""
    if not vids:
        return "Nicio obligație neîndeplinită în corpusul încărcat."
    linii = []
    for v in vids:
        ob = v.obligatie
        unde = f"{ob.act.id} {ob.locator.id}".strip() if ob.act else "?"
        cand = f"{v.scadenta:%d.%m.%Y}" if v.scadenta else "scadență necunoscută"
        intarziere = (
            f"{v.zile_intarziere} zile" if v.zile_intarziere is not None else "necalculabilă"
        )
        linii.append(f"{unde} — scadent {cand}, întârziere {intarziere} [{v.severitate}]")
        linii.append(f'    „{ob.text[:150]}"')
        linii.append(f"    căutat: {v.cautat}")
        if v.candidati:
            linii.append(f"    candidați apropiați: {', '.join(v.candidati)}")
        for lim in v.limitari:
            linii.append(f"    ⚠ {lim}")
    return "\n".join(linii)
