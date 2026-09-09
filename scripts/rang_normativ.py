"""Deterministic hierarchy labels for Romanian legal instrument types.

This is a hierarchy of act *types*, not a classifier for substantive domains. In particular, a row
whose type is `lege` cannot be split into organic versus ordinary law from the corpus metadata
alone.
"""

from __future__ import annotations

from typing import Final

RANG: Final[dict[str, int]] = {
    "constitutie": 0,
    "lege": 1,
    "decret-lege": 1,
    "oug": 1,
    "og": 1,
    "decret": 2,
    "hg": 3,
    "ordin": 4,
    "norma": 4,
    "instructiuni": 4,
}

CATEGORII: Final[dict[int, tuple[str, str]]] = {
    0: ("constitutional", "rang constituțional"),
    1: ("primar", "rang primar"),
    2: ("decret", "decret"),
    3: ("secundar", "rang secundar"),
    4: ("administrativ", "rang administrativ"),
    9: ("necunoscut", "rang necunoscut"),
}

NOTA_LEGE = "organic/ordinar neprecizat în corpus"


def rang(tip: str | None) -> int:
    return RANG.get(tip or "", 9)


def categorie(tip: str | None) -> str:
    return CATEGORII.get(rang(tip), CATEGORII[9])[0]


def eticheta(tip: str | None) -> str:
    return CATEGORII.get(rang(tip), CATEGORII[9])[1]


def info(tip: str | None) -> dict:
    tip = tip or ""
    out = {
        "tip": tip,
        "rang": rang(tip),
        "categorie": categorie(tip),
        "eticheta": eticheta(tip),
    }
    if tip == "lege":
        out["nota"] = NOTA_LEGE
    return out


def poate_modifica(din_tip: str | None, catre_tip: str | None) -> bool:
    """Whether an act of the first type can amend one of the second type."""
    if din_tip is None or catre_tip is None:
        return True
    return rang(din_tip) <= rang(catre_tip)
