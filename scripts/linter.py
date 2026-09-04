"""The three reports, in the order they should be trusted.

The ordering is the argument this package makes. A linter of this kind is usually built in
pipeline order — scrape, parse, graph, then ask a model — which puts the least reliable output
in front of the reader first and the most reliable one last, if at all. Ranked by value over
risk instead, it inverts:

1. **Unfulfilled obligations.** Arithmetic over dates and edges. No model. Every row carries the
   article, the deadline, the search that failed and what the corpus cannot rule out. This is the
   report to lead with and the one that survives being checked in public.
2. **Terminology.** A dictionary lookup against the act's own definition articles, on stems so
   that Romanian inflection is not mistaken for drift. Cheap, precise, and immediately actionable
   by whoever is drafting.
3. **Contradictions.** The one that needs a language model, and the one where a small model
   working in legal Romanian will produce fluent, well-formatted findings about provisions that
   do not exist. It runs last, behind `validare.valideaza`, and it is labelled experimental
   wherever it is shown.

**Section 3 does not silently disappear when no model is configured.** It reports that it did not
run. An empty contradictions section and a contradictions section that was never executed look
identical to a reader, and the difference is the whole meaning of the result.

Run the worked example: `python -m scripts.linter`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts.definitii import Avertisment, Termen, definitii, jargon
from scripts.referinte import Act, Locator
from scripts.termene import Obligatie, obligatii
from scripts.text import normalizeaza
from scripts.validare import Rezultat, citeste, valideaza
from scripts.vid import ActCunoscut, Corpus, Vid, raport, vid_legislativ

EXEMPLU = Path(__file__).resolve().parent.parent / "data" / "exemplu.json"

PROMPT = """Ești un asistent care compară un proiect de act normativ cu textele de lege primite.

REGULI, în ordinea importanței:
1. Poți cita EXCLUSIV proviziile din secțiunea CONTEXT de mai jos. Nu invoca niciun articol
   care nu apare acolo, nici dacă știi că există.
2. Fiecare constatare trebuie să conțină un citat LITERAL, copiat cuvânt cu cuvânt din provizia
   citată. Nu reformula. O constatare fără citat literal va fi aruncată.
3. Dacă textele primite nu sunt suficiente, răspunde cu lista goală. „Nu pot stabili" este un
   răspuns corect și preferabil unei presupuneri.

Răspunde exclusiv cu JSON, o listă de obiecte cu cheile:
  tip       - "contradictie"
  provizie  - identificatorul exact al proviziei, așa cum apare în CONTEXT
  citat     - citatul literal din acea provizie
  motiv     - în ce anume se contrazice cu proiectul
  fragment_proiect - fragmentul din proiect care intră în conflict

CONTEXT:
{context}

PROIECT:
{proiect}
"""


@dataclass(frozen=True)
class Raport:
    """The three sections, each knowing whether it ran."""

    vid: tuple[Vid, ...]
    jargon: tuple[Avertisment, ...]
    contradictii: Rezultat | None
    context: dict[str, str]

    def text(self) -> str:
        linii = [
            "1. OBLIGAȚII NEÎNDEPLINITE  (determinist, fără model)",
            "",
            raport(list(self.vid)),
            "",
            "2. TERMINOLOGIE  (determinist, fără model)",
            "",
        ]
        if self.jargon:
            linii += [f"   {a.explicatie}" for a in self.jargon]
        else:
            linii.append("   Nicio abatere de la termenii definiți.")
        linii += ["", "3. CONTRADICȚII  (experimental — necesită verificare umană)", ""]
        if self.contradictii is None:
            linii.append(
                "   Nu a rulat: niciun model configurat. O secțiune goală și una care nu a fost "
                "executată\n   nu înseamnă același lucru, așa că aceasta o spune."
            )
        else:
            linii.append("   " + self.contradictii.raport().replace("\n", "\n   "))
            for c in self.contradictii.acceptate:
                linii.append(f'   • [{c.provizie}] „{c.citat}" — {c.motiv}')
        return "\n".join(linii)


def context_din_corpus(corpus: Corpus, provizii: dict[str, str]) -> dict[str, str]:
    """The provisions handed to the model, which is also what the validator will hold it to."""
    return {k: normalizeaza(v) for k, v in provizii.items() if k.split()[0] in corpus.acte}


def analizeaza(
    proiect: str,
    corpus: Corpus,
    obligatii_corpus: list[Obligatie],
    termeni: list[Termen],
    provizii: dict[str, str],
    la_data: date | None = None,
    model: Callable[[str], str] | None = None,
) -> Raport:
    """Run all three passes. `model` is any callable taking a prompt and returning its output.

    Left as a plain callable on purpose: Ollama, a free-tier endpoint and a recorded fixture are
    all the same shape, and a framework in between would be one more thing to debug in an
    afternoon that does not have one to spare.
    """
    la_data = la_data or date.today()
    context = context_din_corpus(corpus, provizii)

    contradictii = None
    if model is not None:
        brut = model(
            PROMPT.format(
                context="\n".join(f"[{k}] {v}" for k, v in context.items()), proiect=proiect
            )
        )
        constatari, respinse_forma = citeste(brut)
        rezultat = valideaza(constatari, context)
        contradictii = Rezultat(rezultat.acceptate, (*respinse_forma, *rezultat.respinse))

    return Raport(
        vid=tuple(vid_legislativ(obligatii_corpus, corpus, la_data)),
        jargon=tuple(jargon(proiect, termeni)),
        contradictii=contradictii,
        context=context,
    )


def _incarca(cale: Path = EXEMPLU) -> dict[str, Any]:
    return json.loads(cale.read_text(encoding="utf-8"))


def din_exemplu(
    cale: Path = EXEMPLU,
) -> tuple[Corpus, list[Obligatie], list[Termen], dict[str, str]]:
    """The worked example, assembled from the committed fixture rather than from the portal."""
    date_ = _incarca(cale)
    acte: dict[str, ActCunoscut] = {}
    obligatii_corpus: list[Obligatie] = []
    termeni: list[Termen] = []
    provizii: dict[str, str] = {}

    for brut in date_["acte"]:
        act = Act(brut["tip"], brut["numar"], brut["an"])
        acte[act.id] = ActCunoscut(
            act=act,
            titlu=brut["titlu"],
            publicat=date.fromisoformat(brut["publicat"]) if brut.get("publicat") else None,
            vigoare=date.fromisoformat(brut["vigoare"]) if brut.get("vigoare") else None,
            referinte_la=frozenset(brut.get("referinte_la", [])),
        )
        for prov in brut.get("provizii", []):
            provizii[f"{act.id} {prov['locator']}"] = prov["text"]
            locator = Locator(articol=prov["locator"].removeprefix("art").split(".")[0])
            obligatii_corpus += obligatii(prov["text"], act=act, locator=locator)
            termeni += definitii(prov["text"], act=act, locator=locator)

    return (
        Corpus(acte=acte, complet_pentru=frozenset(date_.get("complet_pentru", []))),
        obligatii_corpus,
        termeni,
        provizii,
    )


if __name__ == "__main__":  # pragma: no cover
    corpus, obligatii_corpus, termeni, provizii = din_exemplu()
    exemplu = _incarca()
    print(
        analizeaza(
            proiect=exemplu["proiect"],
            corpus=corpus,
            obligatii_corpus=obligatii_corpus,
            termeni=termeni,
            provizii=provizii,
            la_data=date(2026, 9, 4),
        ).text()
    )
