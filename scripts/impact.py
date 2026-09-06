"""Raza de impact — the true downstream reach of an amendment, so a small change with a large
effect cannot hide.

The linter says what a draft *cites*. This says what it *does downstream* — the gap where a
"trojan horse" lives: an edit that looks like a typo but moves the whole system. It measures reach,
deterministically, from data the package already holds, and the measurement is symmetric: the same
number that tells a drafter their reform reaches far tells a reader that a rival's innocuous-looking
amendment reaches further than it admits. Its value is transparency, not concealment.

Three kinds of reach, each a fact:

- **Structural** — how many other acts reference the act being changed (the amendment graph's
  inbound edges). Editing a provision that dozens of laws cite is high-leverage by construction.
- **Definitional** — a change that redefines a term reaches every provision that uses the term.
  Redefining «interes public» in one line shifts the meaning of everything downstream of it; the
  count of corpus usages is that reach, where the corpus is available to count it.
- **Obligational** — the duties the new text creates, and the provisions it repeals (a quietly
  removed reporting duty is a rollback that looks like a deletion).

The **trojan signal** is the ratio: a small payload with a large reach. It is a heuristic and says
so; every component is reported alongside it so a reader can see what drove the number, never just
a verdict. Standard library only, no model — like the rest of the package.
"""

from __future__ import annotations

from collections.abc import Callable

from scripts.amendamente import amendamente
from scripts.definitii import definitii
from scripts.termene import obligatii
from scripts.text import cheie

# reach weights: a redefined term and a repealed provision each reach further than one more
# citation, so they count for more than a single structural edge. Tunable, not load-bearing — the
# components are always reported next to the total, so a reader can reweigh by eye.
_GREUTATE_TERMEN = 10
_GREUTATE_ABROGARE = 5
# a removed obligation reaches like a repeal: a quietly-deleted reporting/accountability duty is the
# rollback that hides as a deletion, so it weighs the same as an abrogation.
_GREUTATE_ELIMINARE = 5
_MIC = (
    400  # a payload this small or smaller "looks innocent"; big reach under it is the trojan case
)

# An amendment payload is a bare `a) termen - definiție;` entry, not a whole definition article, so
# `definitii` — which only reads entries inside an «În sensul …» chapeau — would miss it. Prepending
# a synthetic chapeau lets the tested extractor recognise the entry; a payload that is not a
# definition (no `termen - text` shape) still yields nothing, so recall widens without inventing.
_CHAPEAU = "În sensul prezentei legi, termenii de mai jos au următoarele semnificații:\n"


# Plain-language "X-ray": the same amendments, restated as what they plainly do, so a dense page of
# cross-references reads as a numbered list of concrete effects. Deterministic — the structure comes
# from `amendamente`, the wording is a template, no model.
_TIP_RO = {
    "lege": "Legea",
    "oug": "OUG",
    "og": "OG",
    "hg": "HG",
    "ordin": "Ordinul",
    "decizie": "Decizia",
    "decret": "Decretul",
    "ordonanta": "Ordonanța",
    "hotarare": "Hotărârea",
}


def _cita_act(act) -> str:
    if act is None:
        return "actul vizat"
    baza = _TIP_RO.get(act.tip, act.tip.capitalize())
    return f"{baza} nr. {act.numar}/{act.an}" if act.numar else baza


def _loc_ro(loc) -> str:
    if not loc:
        return ""
    parti = []
    if loc.articol:
        parti.append(f"articolul {loc.articol}")
    if loc.alineat:
        parti.append(f"alineatul ({loc.alineat})")
    if loc.litera:
        parti.append(f"litera {loc.litera})")
    if loc.punct:
        parti.append(f"punctul {loc.punct}")
    return ", ".join(parti)


def _explica_op(a) -> str:
    """One amendment as a plain sentence: what it does, to what, in words a lay reader follows."""
    tinta = _cita_act(a.act_tinta)
    loc = _loc_ro(a.locator)
    unde = f"{loc} din {tinta}" if loc else tinta
    citat = f" — text nou: „{a.continut_nou[:120]}”" if a.continut_nou else ""
    if a.fel == "modifica":
        return f"Rescrie {unde}{citat}"
    if a.fel == "abroga":
        return f"Abrogă (elimină) {unde}"
    if a.fel == "completeaza":
        return f"Completează {unde}{citat}"
    if a.fel == "introduce":
        return f"Introduce o prevedere nouă după {unde}{citat}"
    return f"Operația «{a.fel}» asupra {unde}"


def _scor(dimensiune: int, raza: int) -> dict:
    """A categorical reach level plus the trojan flag (small payload, large reach). Heuristic."""
    if raza <= 0:
        return {"nivel": "neutru", "raza": 0, "troian": False}
    nivel = "ridicat" if raza >= 200 else "mediu" if raza >= 40 else "scazut"
    troian = 0 < dimensiune <= _MIC and raza >= 40
    return {
        "nivel": nivel,
        "raza": raza,
        "densitate": round(raza / max(dimensiune, 1), 3),
        "troian": troian,
    }


def raza_de_impact(
    draft: str,
    citari_fn: Callable[[str], tuple[int, int]] | None = None,
    numara_termen: Callable[[str], int | None] | None = None,
    text_original: Callable[[str, str], str | None] | None = None,
    categorii_fn: Callable[[str], list[dict]] | None = None,
) -> dict:
    """The downstream reach of the amendments in `draft`.

    `citari_fn(act_id)` returns `(referințe_totale, doar_amendamente)` for an act — the structural
    reach, from the graph, injected so the engine stays testable and transport-free. `numara_termen`
    counts a term's corpus usages for the definitional reach, or returns `None` where the corpus is
    not available to count (the browser ships no corpus) — a missing count is a gap, not a zero.
    `text_original(act_id, locator)` returns a provision's current text so the obligation *removed*
    by a change can be found — the hidden rollback that a deletion hides; `None` where unavailable.
    """
    ams = amendamente(draft)
    pe_act: dict[str, list] = {}
    for a in ams:
        if a.act_tinta is not None:
            pe_act.setdefault(a.act_tinta.id, []).append(a)

    tinte: list[dict] = []
    citari_total = 0
    payloads: list[str] = []
    for act_id, lista in pe_act.items():
        citari, amend = citari_fn(act_id) if citari_fn else (0, 0)
        citari_total += citari
        tinte.append(
            {
                "act_id": act_id,
                "operatii": [
                    {"fel": a.fel, "locator": a.locator.id if a.locator else ""} for a in lista
                ],
                "abrogari": [a.locator.id for a in lista if a.fel == "abroga" and a.locator],
                "citari": citari,
                "citari_amendatoare": amend,
            }
        )
        payloads += [a.continut_nou for a in lista if a.continut_nou]

    text_nou = "\n".join(payloads)
    termeni: list[dict] = []
    for t in definitii(_CHAPEAU + text_nou if text_nou else ""):
        termeni.append(
            {
                "termen": t.termen,
                "definitie": t.definitie[:200],
                "utilizari": numara_termen(t.termen) if numara_termen else None,
            }
        )
    obligatii_noi = [
        {"text": o.text[:200], "instrument": o.tip_asteptat, "termen_zile": o.termen_zile}
        for o in obligatii(text_nou)
    ]

    # Obligations the change removes: an `abroga` deletes every duty the provision held; a
    # `modifica` deletes each obligation whose sentence is gone from the new text. Folded-text,
    # so a kept-but-reworded duty is not falsely reported gone — the safe direction for a claim that
    # a rollback hides in a deletion. Needs the provision's current text, so silent without it.
    obligatii_eliminate: list[dict] = []
    if text_original:
        for a in ams:
            if a.act_tinta is None or a.locator is None or a.fel not in ("abroga", "modifica"):
                continue
            orig = text_original(a.act_tinta.id, a.locator.id)
            if not orig:
                continue
            vechi = obligatii(orig)
            if a.fel == "abroga":
                sterse = vechi
            elif a.continut_nou:
                pastrate = {cheie(o.text) for o in obligatii(a.continut_nou)}
                sterse = [o for o in vechi if cheie(o.text) not in pastrate]
            else:
                sterse = []
            obligatii_eliminate += [
                {
                    "act_id": a.act_tinta.id,
                    "locator": a.locator.id,
                    "text": o.text[:200],
                    "instrument": o.tip_asteptat,
                    "termen_zile": o.termen_zile,
                }
                for o in sterse
            ]

    abrogari_total = sum(len(t["abrogari"]) for t in tinte)
    raza = (
        citari_total
        + sum((t["utilizari"] or 0) for t in termeni)
        + _GREUTATE_TERMEN * len(termeni)
        + _GREUTATE_ABROGARE * abrogari_total
        + _GREUTATE_ELIMINARE * len(obligatii_eliminate)
    )
    # a term in the new text that is a near-miss of a defined one — how a bill quietly opens a
    # second legal category beside the one the law already defines (see `definitii.jargon`)
    categorii_paralele = categorii_fn(text_nou) if categorii_fn and text_nou else []

    rezumat = [{"fel": a.fel, "text": _explica_op(a)} for a in ams if a.act_tinta is not None]
    return {
        "rezumat": rezumat,
        "tinte": tinte,
        "termeni_redefiniti": termeni,
        "categorii_paralele": categorii_paralele,
        "obligatii_noi": obligatii_noi,
        "obligatii_eliminate": obligatii_eliminate,
        "dimensiune": len(text_nou),
        "scor": _scor(len(text_nou), raza),
    }
