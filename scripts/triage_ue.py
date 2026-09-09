"""Rule-based triage hints for EU-law retrieval.

The labels here do not decide compatibility. They only name why a row is shown and which
manual checks are still blocked by missing local CELEX data.
"""

from __future__ import annotations

from scripts.text import cheie

DEROGARE_EXPRESII = (
    ("prin derogare", "prin derogare"),
    ("se deroga", "se derogă"),
    ("nu se aplica", "nu se aplică"),
    ("nu sunt aplicabile", "nu sunt aplicabile"),
    ("exceptie de la", "excepție de la"),
    ("exceptia de la", "excepția de la"),
    ("se suspenda aplicarea", "se suspendă aplicarea"),
)


def triere_rezultat(rand: dict) -> dict:
    """Label a returned EU provision by the deterministic reason it was retrieved."""
    if rand.get("potrivire") == "referinta":
        return {
            "nivel": "referinta",
            "eticheta": "referință UE citată",
            "explicatie": (
                "Proiectul citează explicit acest act CELEX; verifică prevederile afișate."
            ),
        }
    return {
        "nivel": "materie",
        "eticheta": "aceeași materie",
        "explicatie": (
            "Prevederea folosește termeni apropiați de proiect; nu implică o contradicție."
        ),
    }


def triere_referinta_lipsa(ref: dict) -> dict:
    """Label an explicit EU citation that cannot yet be inspected locally."""
    celex = ref.get("celex") or "CELEX"
    return {
        "nivel": "neimportat",
        "eticheta": "act UE neimportat",
        "explicatie": f"{celex} este citat explicit, dar lipsește din eu.db.",
    }


def semnale_draft(text: str, referinte: list[dict]) -> list[dict]:
    """Draft-level EU triage signals that are visible before any AI/legal judgement."""
    text_cheie = cheie(text or "")
    expresii = [afisaj for cautare, afisaj in DEROGARE_EXPRESII if cautare in text_cheie]
    if not expresii:
        return []

    return [
        {
            "nivel": "posibila_derogare",
            "eticheta": "posibilă derogare de la drept UE",
            "explicatie": (
                "Textul folosește formulări de derogare sau excepție; verifică manual actele UE "
                "citate ori candidate."
            ),
            "expresii": expresii,
            "referinte": sorted({r["celex"] for r in referinte if r.get("celex")}),
        }
    ]


def aplica_triere(rezultate: list[dict]) -> list[dict]:
    """Attach row-level triage labels in place and return the same list."""
    for rand in rezultate:
        rand["triere"] = triere_rezultat(rand)
    return rezultate


def aplica_triere_lipsa(referinte: list[dict]) -> list[dict]:
    """Attach missing-import labels in place and return the same list."""
    for ref in referinte:
        ref["triere"] = triere_referinta_lipsa(ref)
    return referinte
