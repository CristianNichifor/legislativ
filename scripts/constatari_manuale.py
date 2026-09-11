"""Shared vocabulary for user-authored legislative gap notes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TipConstatareManuala:
    cheie: str
    eticheta: str
    descriere: str


TIPURI: tuple[TipConstatareManuala, ...] = (
    TipConstatareManuala(
        "lacuna",
        "Lacună",
        "O obligație, procedură sau instituție necesară pare absentă ori neacoperită.",
    ),
    TipConstatareManuala(
        "loophole",
        "Loophole",
        "Textul pare să permită evitarea unei obligații printr-o omisiune sau excepție.",
    ),
    TipConstatareManuala(
        "contradictie",
        "Contradicție",
        "Două prevederi par să impună reguli incompatibile pentru aceeași situație.",
    ),
    TipConstatareManuala(
        "necorelare",
        "Necorelare",
        "Acte sau trimiteri conexe par nealiniate, incomplete sau rămase în urmă.",
    ),
    TipConstatareManuala(
        "risc_ue",
        "Risc UE",
        "Textul poate necesita verificare față de o obligație sau sursă UE.",
    ),
    TipConstatareManuala(
        "constitutionalitate",
        "Constituționalitate",
        "Textul poate necesita verificare față de Constituție sau jurisprudența CCR.",
    ),
)

STARI = {
    "draft": "Ciornă",
    "needs_evidence": "Necesită dovezi",
    "ready_for_review": "Pregătită pentru revizie",
    "reviewed": "Revizuită",
    "resolved": "Rezolvată",
}


def tipuri() -> list[dict[str, str]]:
    return [vars(tip) for tip in TIPURI]


def normalize_tip(value: object) -> str:
    key = str(value or "").strip().lower().replace("-", "_")
    if key not in {tip.cheie for tip in TIPURI}:
        raise ValueError("Tip de constatare manuală invalid.")
    return key


def normalize_stare(value: object) -> str:
    key = str(value or "draft").strip().lower().replace("-", "_")
    if key not in STARI:
        raise ValueError("Stare de constatare manuală invalidă.")
    return key
